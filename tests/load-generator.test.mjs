import test from 'node:test';
import assert from 'node:assert/strict';
import {generateRequests} from '../web/load-generator.js';
import {employeeFitsOrder} from '../web/order-options.js';
const catalog={buildings:[{building_id:'B1',building_type:'MKD',technology:'PON'},{building_id:'B2',building_type:'PRIVATE',technology:'FTTB',overhead_line:true}],works:[{code:'INST_PON_MKD',profiles:['INSTALL']},{code:'INST_PRIVATE_VLS',profiles:['INSTALL']},{code:'REPAIR',profiles:['LTP3']}],staff:[
 {staff_id:'S1',profiles:['INSTALL'],technologies:['PON'],height_permit:false,equipment_capacity:{ONT:1,ROUTER:1},shift:{start:'09:00',end:'18:00'}},
 {staff_id:'S2',profiles:['LTP3'],technologies:['FTTB'],height_permit:true,equipment_capacity:{ROUTER:1},shift:{start:'10:00',end:'19:00'}},
 {staff_id:'NO',profiles:['INSTALL'],technologies:['FTTB'],height_permit:false,equipment_capacity:{ROUTER:1}},
]};
const options={count:200,date:'2026-11-25',seed:123,staffIds:['S1','S2','NO'],pin:true};
test('large random batch contains only compatible requests and cycles all eligible staff',()=>{
 const result=generateRequests(catalog,options);
 assert.equal(result.requests.length,200);assert.deepEqual(result.skippedStaffIds,['NO']);
 assert.deepEqual(new Set(result.requests.map(r=>r.staff_id)),new Set(['S1','S2']));
 for(const r of result.requests){
  const staff=catalog.staff.find(p=>p.staff_id===r.staff_id),building=catalog.buildings.find(b=>b.building_id===r.building_id),work=catalog.works.find(w=>w.code===r.work_type_code);
  assert.ok(employeeFitsOrder(staff,building,work));assert.equal(r.date,options.date);
 }
 assert.deepEqual(result,generateRequests(catalog,options));
 assert.notDeepEqual(result.requests,generateRequests(catalog,{...options,seed:124}).requests);
});
test('automatic batch leaves staff assignment to the planner and respects selection',()=>{
 const result=generateRequests(catalog,{...options,pin:false,staffIds:['S1']});
 assert.ok(result.requests.every(r=>r.staff_id===''));
 assert.deepEqual(result.eligibleStaffIds,['S1']);
});
test('invalid load sizes and impossible staff selections are rejected before requests',()=>{
 for(const count of [0,-1,1.5,10001,NaN])assert.throws(()=>generateRequests(catalog,{...options,count}));
 assert.throws(()=>generateRequests(catalog,{...options,staffIds:['NO']}));
});
