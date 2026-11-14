import test from 'node:test';
import assert from 'node:assert/strict';
import {planAction} from '../web/plan-action.js';
test('only a day without a plan uses the initial calculation endpoint',()=>{
 const request=planAction({date:'2026-11-16',plan:null},'unused');
 assert.equal(request.url,'/api/v1/days/2026-11-16/plan');assert.equal(request.body.time_limit_sec,30);
});
test('existing plans of any version are updated through a same-time event',()=>{
 for(const plan_version of [1,2,11]){
  const day={date:'2026-11-16',model_now:'2026-11-16T10:30:00+05:00',plan:{plan_version}};
  const original=structuredClone(day),request=planAction(day,'UI-unique');
  assert.equal(request.url,'/api/v1/days/2026-11-16/events');
  assert.deepEqual(request.body,{event_id:'UI-unique',type:'TIME_TICK',timestamp:day.model_now});
  assert.deepEqual(day,original);
 }
});
