import test from 'node:test';
import assert from 'node:assert/strict';
import { createEventId } from '../web/uuid.js';
test('event IDs work without secure-context randomUUID',()=>{
  const source={getRandomValues(bytes){bytes.fill(123);return bytes;}};
  assert.match(createEventId(source),/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  const ids=new Set(Array.from({length:100},()=>createEventId(null)));assert.equal(ids.size,100);
  assert.equal(createEventId({randomUUID:()=> 'native-id'}),'native-id');
});
