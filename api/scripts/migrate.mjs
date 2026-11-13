import pg from 'pg';
import { readdir, readFile } from 'node:fs/promises';
const client = new pg.Client();
try {
  await client.connect();
  await client.query('SELECT pg_advisory_lock(506001)');
  await client.query('CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())');
  for (const name of (await readdir('/app/migrations')).filter(n => n.endsWith('.sql')).sort()) {
    if ((await client.query('SELECT 1 FROM schema_migrations WHERE name=$1', [name])).rowCount) continue;
    await client.query('BEGIN');
    try {
      await client.query(await readFile(`/app/migrations/${name}`, 'utf8').then(sql => sql.replace(/^\uFEFF/, '')));
      await client.query('INSERT INTO schema_migrations(name) VALUES ($1)', [name]);
      await client.query('COMMIT');
      console.log(`Applied ${name}`);
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    }
  }
} catch (error) {
  console.error('Migration failed:', error.message);
  process.exitCode = 1;
} finally {
  await client.end();
}
