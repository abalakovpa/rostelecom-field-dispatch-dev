import test from 'node:test';
import assert from 'node:assert/strict';
import {routeFeatures,boundsOf,routeColors} from '../web/map-data.js';

test('directed segments preserve server coordinates and use successive colors',()=>{
  const outward=[[60.61,56.91],[60.62,56.92],[60.63,56.92]],inward=[[60.63,56.92],[60.64,56.91],[60.61,56.91]];
  const result=routeFeatures([{from_stop:'СЦ',to_stop:'1',geometry:{type:'LineString',coordinates:outward}},
    {from_stop:'1',to_stop:'СЦ',geometry:{type:'LineString',coordinates:inward}}]);
  assert.deepEqual(result.features[0].geometry.coordinates,outward);
  assert.deepEqual(result.features[1].geometry.coordinates,inward);
  assert.equal(result.features[0].properties.color,routeColors[0]);
  assert.notEqual(result.features[0].properties.color,result.features[1].properties.color);
  assert.equal(result.features[1].properties.label,'1 → СЦ');
});
test('empty routes have no invented straight-line geometry and invalid coordinates are rejected',()=>{
  assert.deepEqual(routeFeatures([]),{type:'FeatureCollection',features:[]});
  assert.equal(routeFeatures([{geometry:{type:'LineString',coordinates:[]}}]).features.length,0);
  assert.throws(()=>routeFeatures([{geometry:{type:'LineString',coordinates:[[60,56],[NaN,57]]}}]));
});
test('bounds retain longitude-latitude order and handle an empty filter',()=>{
  assert.deepEqual(boundsOf([[60.63,56.9],[60.6,56.94],[60.62,56.88]]),[[60.6,56.88],[60.63,56.94]]);
  assert.equal(boundsOf([]),null);
});
