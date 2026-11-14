import pg from 'pg';
import { Ajv } from 'ajv';
import addFormats from 'ajv-formats';
import { definitions } from '../dist/openapi.js';
const chunks=[];for await(const chunk of process.stdin)chunks.push(chunk);
const payload=JSON.parse(Buffer.concat(chunks).toString('utf8').replace(/^\uFEFF/,''));
const validator=new Ajv({strict:false});addFormats(validator);for(const schema of Object.values(definitions))validator.addSchema(schema);
for(const [key,name] of [['reference','ReferenceData'],['matrix','TravelMatrix']])if(!validator.getSchema(`urn:dispatch:${name}`)(payload[key]))throw new Error(`Invalid ${key}`);
const ref=payload.reference,matrix=payload.matrix;
const required=[...ref.service_centers.map(c=>c.service_center_id),...ref.access_nodes.flatMap(n=>n.buildings.map(b=>b.building_id))];
if(required.some(id=>!matrix.points.includes(id)))throw new Error('Incomplete matrix');
for(const key of ['durations_sec','distances_m'])if(matrix[key].length!==matrix.points.length||matrix[key].some((row,i)=>row.length!==matrix.points.length||row[i]!==0))throw new Error('Invalid dimensions');
const client=new pg.Client();
try{
 await client.connect();await client.query('BEGIN');
 const locked=await client.query('SELECT document FROM api_state WHERE singleton=true FOR UPDATE');if(locked.rowCount!==1)throw new Error('Missing API state row; run migrations first');
 await client.query('UPDATE api_state SET document=$1::jsonb WHERE singleton=true',[JSON.stringify({reference:ref,matrix,days:{}})]);
 await client.query('COMMIT');console.log(`Loaded coherent dataset: ${ref.staff.length} staff, ${required.length} points. Days cleared by explicit request.`);
}catch(error){try{await client.query('ROLLBACK');}catch{}throw error;}finally{await client.end();}

