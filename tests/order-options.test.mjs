import test from 'node:test';import assert from 'node:assert/strict';
import {workFitsBuilding,employeeFitsOrder} from '../web/order-options.js';

test('custom order equipment is checked against staff capacity',()=>{
 const person={profiles:['INSTALL'],technologies:['FTTB'],height_permit:false,equipment_capacity:{ONT:0,ROUTER:2,STB:0}};
 const building={building_type:'MKD',technology:'FTTB'},work={code:'INST_FTTB_MKD',profiles:['INSTALL']};
 assert.equal(employeeFitsOrder(person,building,work,{ONT:0,ROUTER:2,STB:0}),true);
 assert.equal(employeeFitsOrder(person,building,work,{ONT:0,ROUTER:3,STB:0}),false);
 assert.equal(employeeFitsOrder(person,building,work,{ONT:0,ROUTER:1,STB:1}),false);
});
const building={building_type:'MKD',technology:'FTTB',overhead_line:false};
const install={code:'INST_FTTB_MKD',profiles:['INSTALL']};
const repair={code:'REPAIR',profiles:['LTP3']};
const worker={profiles:['LTP3'],technologies:['PON','FTTB'],height_permit:false,equipment_capacity:{ONT:2,ROUTER:2,STB:0}};
test('screenshot address cannot use private overhead installation',()=>{
 assert.equal(workFitsBuilding(building,{code:'INST_PRIVATE_VLS'}),false);
 assert.equal(workFitsBuilding(building,{code:'INST_PON_MKD'}),false);
 assert.equal(workFitsBuilding(building,install),true);
 assert.equal(employeeFitsOrder(worker,building,install),false);
 assert.equal(employeeFitsOrder(worker,building,repair),true);
});
test('overhead work requires installation profile and height permit',()=>{
 const privateHome={building_type:'PRIVATE',technology:'PON',overhead_line:true},work={code:'INST_PRIVATE_VLS',profiles:['INSTALL']};
 const installer={...worker,profiles:['INSTALL']};
 assert.equal(employeeFitsOrder(installer,privateHome,work),false);
 assert.equal(employeeFitsOrder({...installer,height_permit:true},privateHome,work),true);
});
