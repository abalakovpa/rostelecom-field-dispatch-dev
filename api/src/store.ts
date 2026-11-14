import { withTransaction } from './db.js';
export type Document = { reference?: any; matrix?: any; days: Record<string, any> };
export interface Store { transact<T>(fn: (state: Document) => Promise<T>): Promise<T> }
export class PostgresStore implements Store {
  async transact<T>(fn: (state: Document) => Promise<T>): Promise<T> {
    return withTransaction(async client => {
      const { rows } = await client.query('SELECT document FROM api_state WHERE singleton=true FOR UPDATE');
      if (!rows[0]) throw new Error('API state migration has not been applied');
      const state: Document = { days: {}, ...rows[0].document };
      const result = await fn(state);
      await client.query('UPDATE api_state SET document=$1::jsonb WHERE singleton=true', [JSON.stringify(state)]);
      return result;
    });
  }
}
