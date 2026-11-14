import test from 'node:test';
import assert from 'node:assert/strict';
import {projectDay} from '../web/dispatch-model.js';
const at=t=>`2026-10-12T${t}:00+05:00`;
const stop=(type,start,end,extra={})=>({type,arrival:at(start),start:at(start),end:at(end),travel_sec:0,...extra});
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
