"""Update the generated local dataset atomically, preserving IDs and backing up DB rows."""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'demo/backend'))
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from api.settings import Settings

TABLE_KEYS={'service_centers':'service_center_id','staff':'staff_id','buildings':'building_id',
    'access_nodes':'access_node_id','access_node_buildings':'access_node_id,building_id',
    'work_types':'code','travel_matrices':'matrix_id','training_orders':'order_id',
    'planning_days':'date','orders':'date,order_id'}

def main():
    load_dotenv(ROOT/'.env');s=Settings.from_env()
    seed=(ROOT/'demo/db/seeds/001_generated_data.sql').read_text(encoding='utf-8')
    with psycopg.connect(host=s.host,port=s.port,dbname=s.database,user=s.user,password=s.password,connect_timeout=5,row_factory=dict_row) as conn:
        conn.execute("SET LOCAL search_path=dispatch,public")
        conn.execute('LOCK TABLE '+','.join(TABLE_KEYS)+' IN SHARE ROW EXCLUSIVE MODE')
        if conn.execute('SELECT (SELECT count(*) FROM plans)+(SELECT count(*) FROM events) AS n').fetchone()['n']:
            raise RuntimeError('Plans/events exist: stop and migrate their geometry explicitly instead of invalidating history.')
        expected={o['order_id'] for o in json.loads((ROOT/'data/orders_train.json').read_text(encoding='utf-8'))}
        actual={r['order_id'] for r in conn.execute('SELECT order_id FROM orders')}
        if actual!=expected:raise RuntimeError('DB contains a different dataset; update aborted.')
        backup={table:conn.execute('SELECT * FROM '+table).fetchall() for table in TABLE_KEYS}
        path=ROOT/'tmp/backups'/('db_before_real_geography_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(backup,ensure_ascii=False,default=str),encoding='utf-8')
        for line in seed.splitlines():
            if not line.startswith('INSERT INTO '):continue
            table=line.split()[2];columns=line.split('(',1)[1].split(')',1)[0].split(',')
            keys=TABLE_KEYS[table].split(',');updates=','.join(f'{c}=EXCLUDED.{c}' for c in columns if c not in keys)
            suffix=' DO UPDATE SET '+updates if updates else ' DO NOTHING'
            conn.execute(line.rstrip(';')+' ON CONFLICT ('+','.join(keys)+')'+suffix)
        conn.execute('''DO $$ BEGIN IF EXISTS(SELECT 1 FROM orders o JOIN buildings b USING(building_id)
            WHERE o.lat<>b.lat OR o.lon<>b.lon OR o.address<>b.address) THEN
            RAISE EXCEPTION 'Order/building geography mismatch'; END IF; END $$''')
        print('Updated real geography and regenerated inputs; backup:',path)
    print('Transaction committed. Existing IDs preserved. No plans or events removed.')

if __name__=='__main__':main()
