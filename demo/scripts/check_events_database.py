"""Exercise real PostgreSQL event writes, then roll back every change."""
import sys,json,time
from pathlib import Path
from datetime import date,datetime,timedelta
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'demo/backend'))
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from api.settings import Settings
from api.event_store import postgres_event

def main():
    load_dotenv(ROOT/'.env');s=Settings.from_env()
    connect=psycopg.connect
    conn=connect(host=s.host,port=s.port,dbname=s.database,user=s.user,password=s.password,connect_timeout=3,row_factory=dict_row)
    class NoCommit:
        def __enter__(self):return conn
        def __exit__(self,*args):return False
    try:
        row=conn.execute('''SELECT d.*,p.payload AS plan FROM dispatch.planning_days d JOIN dispatch.current_plans p USING(date)
            ORDER BY d.date LIMIT 1''').fetchone()
        if not row:raise RuntimeError('A day with a saved plan is required')
        day=row['date'];baseline=row['plan'];events=conn.execute('SELECT count(*) AS n FROM dispatch.events').fetchone()['n']
        initial=row['input_snapshot'];now=initial['now'];timestamp=(datetime.fromisoformat(now)+timedelta(minutes=15)).isoformat();version=baseline['plan_version']
        event=dict(event_id='EV-ROLLBACK-INTEGRATION-TICK',type='TIME_TICK',timestamp=timestamp)
        with patch('api.event_store.psycopg.connect',return_value=NoCommit()):
            first=postgres_event(s,day,event);duplicate=postgres_event(s,day,event)
            assert first['plan_version']==version+1 and duplicate['duplicate']
            assert conn.execute('SELECT max(plan_version) AS n FROM dispatch.plans WHERE date=%s',(day,)).fetchone()['n']==version+1
            order=dict(initial['orders'][0]);order['order_id']=f'ORD-{day:%Y%m%d}-9997';order['registered_at']=timestamp;order['is_repeat']=False;order['previous_order_id']=None
            second=postgres_event(s,day,dict(event_id='EV-ROLLBACK-INTEGRATION-NEW',type='NEW_ORDER',timestamp=timestamp,order=order))
            assert second['plan_version']==version+2
            assert conn.execute('SELECT 1 FROM dispatch.orders WHERE date=%s AND order_id=%s',(day,order['order_id'])).fetchone()
        conn.rollback()
        assert conn.execute('SELECT payload FROM dispatch.current_plans WHERE date=%s',(day,)).fetchone()['payload']==baseline
        assert conn.execute('SELECT count(*) AS n FROM dispatch.events').fetchone()['n']==events
        report=dict(status='PASS',day=str(day),checks=['real event insert','plan version insert','duplicate idempotency','new order insert','complete rollback'],
            tick_ms=first['processing_ms'],new_order_ms=second['processing_ms'],user_data_unchanged=True)
        (ROOT/'data/events_database_validation_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    finally:conn.rollback();conn.close()

if __name__=='__main__':main()
