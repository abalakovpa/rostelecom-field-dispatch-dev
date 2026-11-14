import test from 'node:test';
import assert from 'node:assert/strict';
import {time,fullTime,shiftTime,warningIndicator} from '../web/ui-format.js';

test('visit and staff shift clocks consistently use Moscow time',()=>{
 assert.equal(time('2026-11-16T09:30:00+05:00'),'07:30');
 assert.equal(shiftTime('2026-11-16','09:00'),'07:00');
 assert.equal(shiftTime('2026-11-16','21:00'),'19:00');
 assert.match(fullTime('2026-11-16T01:00:00+05:00'),/15.*23:00/);
});
test('warning indicator distinguishes no plan, active warnings and closed history',()=>{
 assert.equal(warningIndicator(null).state,'unknown');
 assert.equal(warningIndicator({alerts:[]}).state,'clear');
 assert.equal(warningIndicator({alerts:[{status:'RESOLVED'}]}).state,'clear');
 const active=warningIndicator({alerts:[{status:'ACTIVE'},{status:'RESOLVED'},{status:'ACTIVE'}]});
 assert.equal(active.state,'alert');assert.equal(active.count,2);
 assert.match(active.label,/2/);
});
