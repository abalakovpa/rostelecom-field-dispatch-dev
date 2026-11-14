import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import { buildApp } from '../dist/app.js';
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

