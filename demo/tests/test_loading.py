"""The same HTTP scenarios exercise memory and an explicitly isolated PostgreSQL DB.

Set RUN_POSTGRES_LOAD_TESTS=1 to include PostgreSQL (destructive to dispatcher_next* only).
"""
from copy import deepcopy
from datetime import date, datetime, timezone
import os
import pytest
from fastapi.testclient import TestClient
from api.main import create_app
from api.repository import DemoRepository, PostgresRepository
from api.settings import ROOT, Settings

@pytest.fixture(params=['memory','postgres'])
def store(request):
    if request.param=='memory':return DemoRepository(empty=True)
    if os.getenv('RUN_POSTGRES_LOAD_TESTS')!='1':pytest.skip('Isolated PostgreSQL tests are opt-in')
    from dotenv import dotenv_values
    env=dotenv_values(ROOT/'.env')
    assert env['POSTGRES_DB'].startswith('dispatcher_next'), 'Refusing to reset another database'
    return PostgresRepository(Settings(host=env['POSTGRES_HOST'],port=int(env['POSTGRES_PORT']),
        database=env['POSTGRES_DB'],user=env['POSTGRES_USER'],password=env['POSTGRES_PASSWORD']))

@pytest.fixture
def inputs():
    demo=DemoRepository()
    ref=deepcopy(demo.full_reference());ref['staff']=ref['staff'][:1]
    day=dict(date='2026-10-12',now='2026-10-12T08:30:00+05:00',orders=[deepcopy(demo.read('orders_train.json')[0])])
    return ref,deepcopy(demo.read('travel_matrix.json')),day

def upload(client,inputs):
    ref,matrix,day=inputs
    assert client.put('/api/v1/reference',json=ref).status_code==200
    assert client.put('/api/v1/reference/travel-matrix',json=matrix).status_code==200
    response=client.put('/api/v1/days/'+day['date'],json=day)
    assert response.status_code==200,response.text

def test_load_plan_event_reset_and_reference_reset(store,inputs):
    with TestClient(create_app(repository=store)) as c:
        upload(c,inputs);path='/api/v1/days/2026-10-12'
        assert c.post(path+'/plan',json={'time_limit_sec':1}).status_code==200
        event=dict(event_id='load-tick',type='TIME_TICK',timestamp='2026-10-12T08:40:00+05:00')
        response=c.post(path+'/events',json=event)
        assert response.status_code==200,response.text
        assert c.get(path+'/plan').json()['plan_version']==2
        # Another loaded day survives this day's replacement.
        other=dict(date='2026-10-13',now='2026-10-13T08:00:00+05:00',orders=[])
        assert c.put('/api/v1/days/2026-10-13',json=other).status_code==200
        assert c.put(path,json=inputs[2]).status_code==200
        assert c.get(path+'/plan').status_code==404
        assert c.get('/api/ui/days/2026-10-13').status_code==200
        assert c.post(path+'/plan',json={'time_limit_sec':1}).status_code==200
        # Old event IDs can be reused after a day reset: its journal was deleted.
        assert c.post(path+'/events',json=event).status_code==200
        assert c.put('/api/v1/reference',json=inputs[0]).status_code==200
        assert c.get('/api/ui/bootstrap').json()['days']==[]

def test_invalid_load_preserves_everything(store,inputs):
    with TestClient(create_app(repository=store)) as c:
        upload(c,inputs);before=c.get('/api/ui/bootstrap').json()
        broken=deepcopy(inputs[0]);broken['staff'][0]['service_center_id']='SC-99'
        assert c.put('/api/v1/reference',json=broken).status_code==422
        assert c.get('/api/ui/bootstrap').json()==before
        broken=deepcopy(inputs[1]);broken['durations_sec'][0][0]=1
        assert c.put('/api/v1/reference/travel-matrix',json=broken).status_code==422
        broken=deepcopy(inputs[2]);broken['orders'][0]['access_node_id']='AN-9999'
        assert c.put('/api/v1/days/2026-10-12',json=broken).status_code==422
        assert len(c.get('/api/ui/days/2026-10-12').json()['orders'])==1
        assert c.put('/api/v1/reference',json={}).status_code==400
        assert c.put('/api/v1/reference',content='{',headers={'Content-Type':'application/json'}).status_code==400

def test_matrix_first_unknown_fields_and_offsets(store,inputs):
    with TestClient(create_app(repository=store)) as c:
        # Reset first, then remove explicit reference in memory; PG prerequisites
        # are checked separately on a fresh migration by the smoke script.
        assert c.put('/api/v1/reference',json=inputs[0]).status_code==200
        ref,matrix,day=deepcopy(inputs)
        ref['staff'][0]['shift']['future_field']='ignored'
        ref['staff'][0]['equipment_start']['future_field']=17
        assert c.put('/api/v1/reference/travel-matrix',json=matrix).status_code==200
        assert c.put('/api/v1/reference',json=ref).status_code==200
        day['now']=datetime.fromisoformat(day['now']).astimezone(timezone.utc).isoformat()
        for order in day['orders']:
            for key in ['registered_at','latest_start','deadline']:
                order[key]=datetime.fromisoformat(order[key]).astimezone(timezone.utc).isoformat()
            order['slot']={k:datetime.fromisoformat(v).astimezone(timezone.utc).isoformat() for k,v in order['slot'].items()}
        assert c.put('/api/v1/days/2026-10-12',json=day).status_code==200
        assert len(c.get('/api/ui/days/2026-10-12').json()['orders'])==1
        assert c.post('/api/v1/days/2026-10-12/plan',json={'time_limit_sec':1}).status_code==200

def test_matrix_replacement_pins_existing_day(store,inputs):
    with TestClient(create_app(repository=store)) as c:
        upload(c,inputs)
        if isinstance(store,DemoRepository):prior=deepcopy(store.day_matrices['2026-10-12'])
        else:prior=store.fetch('SELECT m.payload FROM dispatch.planning_days d JOIN dispatch.travel_matrices m USING(matrix_id)')[0]['payload']
        matrix=deepcopy(inputs[1]);matrix['durations_sec'][0][1]+=999
        assert c.put('/api/v1/reference/travel-matrix',json=matrix).status_code==200
        if isinstance(store,DemoRepository):pinned=store.day_matrices['2026-10-12']
        else:pinned=store.fetch('SELECT m.payload FROM dispatch.planning_days d JOIN dispatch.travel_matrices m USING(matrix_id)')[0]['payload']
        assert pinned['durations_sec']==prior['durations_sec']
        assert c.put('/api/v1/days/2026-10-12',json=inputs[2]).status_code==200

def test_missing_prerequisites_and_matrix_before_reference(inputs):
    with TestClient(create_app(repository=DemoRepository(empty=True))) as c:
        path='/api/v1/days/2026-10-12'
        assert c.put(path,json=inputs[2]).status_code==409
        assert c.put('/api/v1/reference/travel-matrix',json=inputs[1]).status_code==200
        assert c.put(path,json=inputs[2]).status_code==409
        assert c.put('/api/v1/reference',json=inputs[0]).status_code==200
        assert c.put(path,json=inputs[2]).status_code==200

def test_postgres_rollback_and_lock(store,inputs,monkeypatch):
    if not isinstance(store,PostgresRepository):pytest.skip('PostgreSQL transaction checks')
    import psycopg
    from api import postgres_loading
    s=store.settings
    with TestClient(create_app(repository=store)) as c:
        upload(c,inputs)
        before=store.fetch('SELECT input_snapshot FROM dispatch.planning_days')
        def fail(*args,**kwargs):raise psycopg.IntegrityError('injected write failure')
        with monkeypatch.context() as patch:
            patch.setattr(postgres_loading,'insert',fail)
            assert c.put('/api/v1/days/2026-10-12',json=inputs[2]).status_code==422
        assert store.fetch('SELECT input_snapshot FROM dispatch.planning_days')==before
        with psycopg.connect(host=s.host,port=s.port,dbname=s.database,user=s.user,password=s.password) as lock:
            lock.execute('SELECT pg_advisory_xact_lock(%s)',(postgres_loading.DATASET_LOCK,))
            assert c.put('/api/v1/reference',json=inputs[0]).status_code==422
            assert c.post('/api/v1/days/2026-10-12/plan',json={'time_limit_sec':1}).status_code==409
