import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import { buildApp } from '../dist/app.js';
import { planAction } from '../../web/plan-action.js';
import {inventoryFor,validateInventoryOverrides} from '../dist/inventory.js';
const spec=parse(readFileSync(new URL('../spec/api_spec.yaml',import.meta.url),'utf8'));
const example=name=>structuredClone(spec.components.examples[name].value);
class MemoryStore {
  state={days:{}};
  async transact(fn) { const draft=structuredClone(this.state); const result=await fn(draft); this.state=draft; return result; }
}
const emptyPlanner=async ({day})=>({routes:[],unassigned:day.orders.map(o=>({order_id:o.order_id,reason_code:'OTHER',reason_text:'Test planner',suggested_action:'ESCALATE'})),pgp_groups:[],cancelled:[],alerts:[]});
async function fixture(planner=emptyPlanner) {
  const store=new MemoryStore(),app=buildApp(store,planner);
  await app.ready();
  const send=(method,url,payload)=>app.inject({method,url,payload});
  const ref=example('ReferenceDataExample');
  const day=example('DayInputExample');day.absent_staff_ids=[];
  assert.equal((await send('PUT','/api/v1/reference',ref)).statusCode,200);
  assert.equal((await send('PUT','/api/v1/reference/travel-matrix',example('TravelMatrixExample'))).statusCode,200);
  assert.equal((await send('PUT',`/api/v1/days/${day.date}`,day)).statusCode,200);
  return {app,store,send,day,path:`/api/v1/days/${day.date}`};
}
test('initial plan, time tick, duplicate, event ordering and rebuild conflict',async()=>{
  const {app,send,path}=await fixture();
  try {
    assert.equal((await send('GET',path+'/plan')).statusCode,404);
    {const r=await send('POST',path+'/plan',{});assert.equal(r.statusCode,200,r.body)};
    const event={event_id:'tick1',type:'TIME_TICK',timestamp:'2026-10-26T09:00:00+05:00'};
    const first=await send('POST',path+'/events',event);assert.equal(first.statusCode,200,first.body);assert.equal(first.json().plan_version,2);
    const duplicate=await send('POST',path+'/events',event);assert.equal(duplicate.json().duplicate,true);assert.equal(duplicate.json().plan_version,2);
    assert.equal((await send('POST',path+'/events',{...event,event_id:'old',timestamp:'2026-10-26T08:00:00+05:00'})).statusCode,409);
    assert.equal((await send('POST',path+'/plan')).statusCode,409);
    assert.equal((await send('GET',path+'/plan')).json().plan_version,2);
  } finally {await app.close();}
});
test('planner failure rolls back event, time and new order',async()=>{
  let fail=false;
  const {app,send,store,path,day}=await fixture(async input=>{if(fail)throw new Error('down');return emptyPlanner(input);});
  try {
    await send('POST',path+'/plan',{});const before=structuredClone(store.state);fail=true;
    const event={event_id:'new1',type:'NEW_ORDER',timestamp:'2026-10-26T09:00:00+05:00',order:{...day.orders[0],order_id:'ORD-20261026-9999'}};
    {const r=await send('POST',path+'/events',event);assert.equal(r.statusCode,500,r.body)};
    assert.deepEqual(store.state,before);
  } finally {await app.close();}
});
test('invalid dimensions and unknown references do not replace existing state',async()=>{
  const {app,send,store,path}=await fixture();
  try {
    const before=structuredClone(store.state),matrix=example('TravelMatrixExample');matrix.durations_sec[0].pop();
    assert.equal((await send('PUT','/api/v1/reference/travel-matrix',matrix)).statusCode,422);
    assert.deepEqual(store.state,before);
    assert.equal((await send('POST',path+'/events',{type:'TIME_TICK'})).statusCode,400);
    assert.equal((await send('GET','/api/v1/days/invalid/plan')).statusCode,400);
  } finally {await app.close();}
});




test('day accepts equivalent UTC timestamps across calendar boundary',async()=>{
  const {app,send,day}=await fixture();
  try {
    // 00:30 in Ekaterinburg is 19:30 UTC on the previous calendar day.
    const order=day.orders[0];
    order.slot={start:'2026-10-25T19:30:00Z',end:'2026-10-25T21:30:00Z'};
    order.latest_start=order.slot.end;
    day.now='2026-10-25T19:00:00Z';
    day.orders=[order];
    const response=await send('PUT',`/api/v1/days/${day.date}`,day);
    assert.equal(response.statusCode,200,response.body);
  } finally {await app.close();}
});

test('event IDs inherited from Object.prototype are accepted once',async()=>{
  const {app,send,path}=await fixture();
  try {
    await send('POST',path+'/plan',{});
    const event={event_id:'__proto__',type:'TIME_TICK',timestamp:'2026-10-26T09:00:00+05:00'};
    const response=await send('POST',path+'/events',event);
    assert.equal(response.statusCode,200,response.body);
    assert.equal(response.json().duplicate,false);
    assert.equal(response.json().plan_version,2);
    assert.equal((await send('POST',path+'/events',event)).json().duplicate,true);
  } finally {await app.close();}
});


test('panel catalog reflects active database reference rather than bundled files',async()=>{
 const {app,store}=await fixture();
 try {
  store.state.reference.access_nodes[0].buildings[0].address='ACTIVE-DATABASE-ADDRESS';
  const response=await app.inject({method:'GET',url:'/api/ui/catalog'});
  assert.equal(response.statusCode,200);
  assert.equal(response.json().buildings[0].address,'ACTIVE-DATABASE-ADDRESS');
  assert.equal(response.json().staff.length,store.state.reference.staff.length);
 }finally{await app.close();}
});

test('UI plan button builds once and safely replans after events at the same model time',async()=>{
 const {app,send,path,day}=await fixture();
 try{
  let snapshot=(await send('GET','/api/ui/days/'+day.date)).json();
  let action=planAction(snapshot,'UI-initial');assert.equal(action.url,path+'/plan');
  assert.equal((await send('POST',action.url,action.body)).statusCode,200);
  const now=snapshot.model_now;
  for(const id of ['UI-replan-1','UI-replan-2']){
   snapshot=(await send('GET','/api/ui/days/'+day.date)).json();action=planAction(snapshot,id);
   assert.equal(action.url,path+'/events');
   const response=await send('POST',action.url,action.body);assert.equal(response.statusCode,200,response.body);
   const updated=(await send('GET','/api/ui/days/'+day.date)).json();
   assert.equal(updated.model_now,now);assert.equal(updated.plan.plan_version,snapshot.plan.plan_version+1);
  }
  assert.equal((await send('POST',path+'/plan',{})).statusCode,409);
 }finally{await app.close();}
});

test('debug identifiers include historical orders and resolve retries without reusing transferred IDs',async()=>{
 const {app,store,send,path,day}=await fixture();
 try{
  await send('POST',path+'/plan',{});
  const id=`ORD-${day.date.replaceAll('-','')}-9999`;
  const event={event_id:'LOCAL-load-request',type:'NEW_ORDER',timestamp:day.now,order:{...day.orders[0],order_id:id}};
  const first=await send('POST',path+'/events',event);assert.equal(first.statusCode,200,first.body);
  const endpoint=`/api/ui/days/${day.date}/debug-orders/load-request`;
  let usage=(await send('GET',endpoint)).json();assert.equal(usage.order_id,id);assert.ok(usage.used_order_ids.includes(day.orders[0].order_id));
  // A source order can leave input.orders when moved to a future day.
  store.state.days[day.date].input.orders=store.state.days[day.date].input.orders.filter(o=>o.order_id!==id);
  usage=(await send('GET',endpoint)).json();assert.ok(usage.used_order_ids.includes(id));assert.equal(usage.order_id,id);
  const retry=await send('POST',path+'/events',event);assert.equal(retry.json().duplicate,true);
  const collision=await send('POST',path+'/events',{...event,event_id:'OTHER'});assert.equal(collision.json().error.code,'DUPLICATE_ORDER');
 }finally{await app.close();}
});

test('inventory overrides are day-specific, capacity-checked and locked after events',async()=>{
 const {app,store,send}=await fixture();
 try{
  const original=structuredClone(store.state.reference.staff[0]);
  const date='2026-11-02',url=`/api/ui/days/${date}/inventory`;
  const start={ONT:0,ROUTER:1,STB:0};
  const response=await send('POST',url,{staff_id:original.staff_id,equipment_start:start});assert.equal(response.statusCode,200,response.body);
  assert.deepEqual((await send('GET',url)).json().staff[0].current,start);
  assert.deepEqual(store.state.reference.staff[0],original);
  const before=structuredClone(store.state);
  const invalid=await send('POST',url,{staff_id:original.staff_id,equipment_start:{...start,ROUTER:original.equipment_capacity.ROUTER+1}});
  assert.equal(invalid.statusCode,422);assert.deepEqual(store.state,before);
  assert.equal((await send('POST',`/api/v1/days/${date}/plan`,{})).statusCode,200);
  assert.equal((await send('POST',`/api/v1/days/${date}/events`,{event_id:'clock',type:'TIME_TICK',timestamp:date+'T09:00:00+05:00'})).statusCode,200);
  assert.equal((await send('POST',url,{staff_id:original.staff_id,equipment_start:start})).statusCode,409);
 }finally{await app.close();}
});

test('inventory display consumes at visit start and replenishes only at depot completion',()=>{
 const start={ONT:0,ROUTER:1,STB:0},empty={...start,ROUTER:0},full={...start,ROUTER:3};
 const worker={staff_id:'S',equipment_start:start,equipment_capacity:full};
 const at=t=>`2026-11-02T${t}:00+05:00`;
 const plan={routes:[{staff_id:'S',stops:[{type:'VISIT',start:at('09:00'),end:at('10:00'),equipment_after:empty},{type:'RESTOCK',start:at('10:30'),end:at('10:45'),equipment_after:full}]}]};
 assert.deepEqual(inventoryFor({now:at('08:59')},plan,worker).current,start);
 assert.deepEqual(inventoryFor({now:at('09:00')},plan,worker).current,empty);
 assert.deepEqual(inventoryFor({now:at('10:35')},plan,worker).current,empty);
 assert.deepEqual(inventoryFor({now:at('10:45')},plan,worker).current,full);
});

test('malformed internal stock overrides cannot bypass capacity checks',()=>{
 const reference={staff:[{staff_id:'S',equipment_capacity:{ONT:1,ROUTER:2,STB:0}}]};
 for(const value of [null,[],{UNKNOWN:{ONT:0,ROUTER:0,STB:0}},{S:{ONT:0,ROUTER:3,STB:0}},{S:{ONT:0,ROUTER:-1,STB:0}},{S:{ONT:0,ROUTER:1.5,STB:0}},{S:{ONT:0,ROUTER:1}}])assert.throws(()=>validateInventoryOverrides({_equipment_start_by_staff:value},reference));
 validateInventoryOverrides({_equipment_start_by_staff:{S:{ONT:1,ROUTER:2,STB:0}}},reference);
});
