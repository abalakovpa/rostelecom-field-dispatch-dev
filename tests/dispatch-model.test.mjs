import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {projectDay,planOverview,matchesOrderStatus,markerSummary,projectWarnings} from '../web/dispatch-model.js';
const at=t=>`2026-10-12T${t}:00+05:00`;
const stop=(type,start,end,extra={})=>({type,arrival:at(start),start:at(start),end:at(end),travel_sec:0,...extra});

test('official Plan without optional summary supplies UI counters',()=>{
 const plan={routes:[{stops:[{type:'DEPOT_START'},{type:'VISIT'},{type:'VISIT'}]}],unassigned:[{order_id:'3'}],pgp_groups:[{order_ids:['4','5','6']}]};
 assert.deepEqual(planOverview(plan),{visits:2,unassigned:1,pgp:3});
 assert.deepEqual(planOverview(null),{visits:0,unassigned:0,pgp:0});
});
test('statuses use model time, cancellation and groups; no plan is pending',()=>{
 const day={model_now:at('10:00'),orders:[1,2,3,4,5,6].map(id=>({order_id:String(id)})),plan:{routes:[{staff_id:'S',stops:[stop('VISIT','09:00','09:30',{order_id:'1'}),stop('VISIT','09:45','10:30',{order_id:'2'}),stop('VISIT','11:00','12:00',{order_id:'3'})]}],unassigned:[{order_id:'4'}],cancelled:[{order_id:'5'}],pgp_groups:[{order_ids:['6']} ]}};
 const view=projectDay(day);assert.deepEqual(['1','2','3','4','5','6'].map(view.status),['completed','active','assigned','unassigned','cancelled','pgp']);assert.equal(view.counts.assigned,3);
 assert.equal(projectDay({...day,plan:null}).status('1'),'pending');
});
test('timeline splits travel and waits without overlap and measures utilization',()=>{
 const day={date:'2026-10-12',model_now:at('08:30'),orders:[],plan:{routes:[{staff_id:'S',stops:[stop('DEPOT_START','09:00','09:00'),stop('VISIT','09:30','10:30',{arrival:at('09:10'),travel_sec:600,order_id:'1'}),stop('BREAK','12:00','13:00',{arrival:at('10:30')})]}]}};
 const row=projectDay(day,[{staff_id:'S',shift_start:'09:00',shift_end:'18:00'}]).rows[0];assert.equal(row.travelMin,10);assert.equal(row.workMin,60);assert.equal(row.waitMin,110);assert.equal(row.utilization,70/480);
 const blocks=[...row.blocks].sort((a,b)=>a.start-b.start);for(let i=1;i<blocks.length;i++)assert.ok(blocks[i].start>=blocks[i-1].end);
});
test('risk filter contains active orders only and does not count resolved history twice',()=>{
 const day={orders:[{order_id:'1'},{order_id:'2'}],plan:{routes:[],alerts:[{type:'LATE_RISK',status:'ACTIVE',order_id:'1'},{type:'LATE_RISK',status:'ACTIVE',order_id:'1'},{type:'LATE_RISK',status:'RESOLVED',order_id:'2'},{type:'PGP_DETECTED',status:'ACTIVE',group_id:'G'}]}};
 const view=projectDay(day);assert.equal(view.counts.risk,1);assert.deepEqual([...view.risks],['1']);
});

test('map filters exclude stale plan records and terminal orders from active risks',()=>{
 const day={orders:['A','P','C','R'].map(order_id=>({order_id})),plan:{
 routes:[{staff_id:'S',stops:['A','P','C'].map(order_id=>stop('VISIT','11:00','12:00',{order_id}))}],
 cancelled:[{order_id:'C'},{order_id:'gone'}],pgp_groups:[{order_ids:['P','C','missing']}],
 alerts:['A','P','C','gone'].map(order_id=>({type:'LATE_RISK',status:'ACTIVE',order_id}))}};
 const view=projectDay(day);
 assert.equal(view.counts.assigned,1);assert.equal(view.counts.cancelled,1);assert.equal(view.counts.pgp,1);assert.equal(view.counts.risk,1);
 for(const [filter,expected]of [['risk',['A']],['pgp',['P']],['cancelled',['C']],['assigned',['A']]]){
   const found=day.orders.filter(o=>matchesOrderStatus(view,o.order_id,filter));
   assert.deepEqual(found.map(o=>o.order_id),expected);assert.equal(found.length,view.counts[filter]);
 }
 const marker=markerSummary(day.orders,view);assert.deepEqual(marker.counts,{risk:1,pgp:1,cancelled:1});
 assert.equal(marker.kind,'risk');assert.match(marker.text,/ПГП: 1/);
 assert.equal(markerSummary([{order_id:'C'}],view).kind,'cancelled');
});

test('incident metadata stays assigned, can carry risk, and drives the PGP map filter',()=>{
 const day={date:'2026-10-12',model_now:at('10:00'),orders:['A','B','C'].map(order_id=>({order_id})),plan:{
  routes:[{staff_id:'S',stops:[stop('VISIT','11:00','12:00',{order_id:'A'})]}],unassigned:[{order_id:'B'}],cancelled:[{order_id:'C'}],
  incident_groups:[{group_id:'INC',access_node_id:'AN',order_ids:['A','B','C','missing'],detected_at:at('09:00'),action:'INDIVIDUAL_VISITS'}],
  alerts:[{type:'LATE_RISK',status:'ACTIVE',order_id:'A'}]}};
 const original=JSON.stringify(day);const view=projectDay(day);
 assert.equal(view.status('A'),'assigned');assert.equal(view.counts.assigned,1);assert.equal(view.counts.pgp,2);assert.equal(view.counts.risk,1);
 assert.equal(matchesOrderStatus(view,'A','pgp'),true);assert.equal(matchesOrderStatus(view,'C','pgp'),false);
 assert.equal(markerSummary([{order_id:'B'}],view).kind,'pgp');
 const warnings=projectWarnings(day);assert.equal(warnings.length,2);assert.equal(warnings[1].type,'INCIDENT_GROUP');assert.match(warnings[1].message,/2 нарядов/);
 assert.equal(JSON.stringify(day),original);
 day.model_now=at('13:00');day.plan.cancelled.push({order_id:'B'});
 assert.equal(projectWarnings(day)[1].status,'RESOLVED');
});
test('an existing group alert is not duplicated by UI group projections',()=>{
 const day={orders:[{order_id:'A'}],plan:{alerts:[{group_id:'G',type:'PGP_DETECTED',status:'ACTIVE'}],pgp_groups:[{group_id:'G',order_ids:['A']}]}};
 assert.equal(projectWarnings(day).length,1);
});

test('captured Fastify UI response exposes incidents without double-counting visits',()=>{
 const day=JSON.parse(readFileSync(new URL('../docs/examples/ui-day-incidents.json',import.meta.url),'utf8'));
 const original=JSON.stringify(day),view=projectDay(day);
 assert.equal(view.counts.pgp,3);assert.equal(view.counts.assigned,3);
 assert.deepEqual(day.plan.pgp_groups,[]);
 assert.equal(day.orders.filter(o=>matchesOrderStatus(view,o.order_id,'pgp')).length,3);
 assert.equal(projectWarnings(day).filter(a=>a.type==='INCIDENT_GROUP'&&a.status==='ACTIVE').length,1);
 assert.equal(JSON.stringify(day),original);
});


test('incident membership highlights assigned visits without subtracting assignments',()=>{
 const order={order_id:'O1'};
 const day={date:'2026-11-14',model_now:'2026-11-14T08:00:00+05:00',orders:[order],plan:{routes:[{staff_id:'S1',stops:[{type:'VISIT',order_id:'O1',arrival:'2026-11-14T09:00:00+05:00',start:'2026-11-14T09:00:00+05:00',end:'2026-11-14T10:00:00+05:00'}]}],unassigned:[],cancelled:[],pgp_groups:[],incident_groups:[{group_id:'INC1',order_ids:['O1']}],alerts:[]}};
 const view=projectDay(day);
 assert.equal(view.counts.assigned,1);assert.equal(view.counts.pgp,1);assert.equal(view.status('O1'),'assigned');
 assert.equal(matchesOrderStatus(view,'O1','pgp'),true);assert.equal(matchesOrderStatus(view,'O1','assigned'),true);
 assert.equal(markerSummary([order],view).kind,'pgp');
});
