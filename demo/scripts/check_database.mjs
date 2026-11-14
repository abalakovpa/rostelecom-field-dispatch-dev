// Install the optional checker with:
// npm install --prefix tmp/pg-check --ignore-scripts --no-audit --no-fund @electric-sql/pglite@0.5.16
import { PGlite } from '../../tmp/pg-check/node_modules/@electric-sql/pglite/dist/index.js';
import { readFile, writeFile } from 'node:fs/promises';
const root=new URL('../../',import.meta.url);
const db=new PGlite();
try {
  const migration=await readFile(new URL('db/proposals/001_dispatch_schema.sql',root),'utf8');
  const seed=await readFile(new URL('demo/db/seeds/001_generated_data.sql',root),'utf8');
  await db.exec(migration);
  console.log('Migration applied');
  await db.exec(seed);
  console.log('All generated data imported');
  const counts=(await db.query(`SELECT 'service_centers' AS entity,count(*)::int AS count FROM dispatch.service_centers
    UNION ALL SELECT 'staff',count(*)::int FROM dispatch.staff
    UNION ALL SELECT 'orders',count(*)::int FROM dispatch.orders
    UNION ALL SELECT 'planning_days',count(*)::int FROM dispatch.planning_days
    UNION ALL SELECT 'training_orders',count(*)::int FROM dispatch.training_orders`)).rows;
  const expected={service_centers:5,staff:40,orders:3500,planning_days:10,training_orders:3500};
  for(const row of counts)if(row.count!==expected[row.entity])throw new Error('Wrong count: '+row.entity);
  // A second import must reject without overwriting the first dataset.
  let rejected=false;
  try {await db.exec(seed);} catch(error) {rejected=error.message.includes('Import requires empty tables');await db.exec('ROLLBACK;');}
  if(!rejected)throw new Error('Repeated seed was not rejected safely');
  const invalid=[
    [`SELECT '{"ONT":-1,"ROUTER":0,"STB":0}'::jsonb::dispatch.equipment_counts`, '23514'],
    [`SELECT '{"ONT":0,"ROUTER":0}'::jsonb::dispatch.equipment_counts`, '23514'],
    [`UPDATE dispatch.staff SET service_center_id='SC-99' WHERE staff_id='ST-001'`, '23503'],
  ];
  for(const [sql,code] of invalid) {
    let caught=false;
    try {await db.exec(sql);} catch(error) {caught=error.code===code;}
    if(!caught)throw new Error('Invalid data was not rejected: '+sql);
  }
  const factLeaks=(await db.query(`SELECT count(*)::int AS count FROM dispatch.planning_days,
    LATERAL jsonb_array_elements(input_snapshot->'orders') o WHERE o ? 'fact'`)).rows[0].count;
  if(factLeaks!==0)throw new Error('Training facts leaked into planner input');
  const engine=(await db.query('SELECT version() AS version')).rows[0].version;
  const report={status:'PASS',engine,counts,checks:['migration execution','full seed import',
    'repeat import rejection and rollback','equipment domain checks','foreign key check','training fact isolation'],
    limitation:'Embedded PostgreSQL via PGlite; Docker and pgAdmin connection not exercised'};
  await writeFile(new URL('data/database_validation_report.json',root),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
} catch(error) {
  console.error(JSON.stringify({message:error.message,code:error.code,detail:error.detail}));
  process.exitCode=1;
} finally {await db.close();}
