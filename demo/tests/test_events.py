from copy import deepcopy
from datetime import date,datetime,timedelta
from fastapi.testclient import TestClient
import pytest
from api.main import create_app
from api.repository import DemoRepository
from api.settings import Settings
from api.contracts import validate
from planner.events import apply_event,EventError
from planner.solver import build_plan

@pytest.fixture
def case():
    repo=DemoRepository();order=deepcopy(repo.read('orders_train.json')[0]);order.pop('fact',None)
    reference=dict(staff=[repo.read('staff.json')[0]],service_centers=repo.read('service_centers.json'),access_nodes=repo.read('access_nodes.json'),work_types=repo._works())
    day=dict(date='2026-10-12',now='2026-10-12T08:30:00+05:00',orders=[order]);matrix=repo.read('travel_matrix.json')
    plan=build_plan(reference,day,matrix,1)
    return reference,day,matrix,plan

def test_delay_freezes_visit_and_preserves_lunch(case):
    ref,day,matrix,old=case;visit=next(s for s in old['routes'][0]['stops'] if s['type']=='VISIT')
    event=dict(event_id='delay',type='VISIT_DELAYED',staff_id='ST-001',order_id=visit['order_id'],timestamp=(datetime.fromisoformat(visit['start'])+timedelta(minutes=10)).isoformat(),expected_end=(datetime.fromisoformat(visit['end'])+timedelta(minutes=20)).isoformat())
    state,plan=apply_event(ref,day,matrix,old,event,.1)
    new=next(s for s in plan['routes'][0]['stops'] if s['type']=='VISIT')
    assert all(new[k]==visit[k] for k in ['start','arrival','location_id','order_id'])
    assert new['end']==event['expected_end'];assert plan['plan_version']==2
    validate('Plan',plan)

def test_cancellation_before_and_after_visit_start(case):
    ref,day,matrix,old=case;oid=day['orders'][0]['order_id']
    event=dict(event_id='cancel',type='ORDER_CANCELLED',order_id=oid,timestamp='2026-10-12T08:40:00+05:00',reason='CUSTOMER_REQUEST')
    _,plan=apply_event(ref,day,matrix,old,event,.1)
    assert plan['cancelled'][0]['order_id']==oid and plan['summary']['visits_planned']==0
    event['timestamp']='2026-10-12T09:30:00+05:00'
    _,plan=apply_event(ref,day,matrix,old,event,.1)
    assert not plan['cancelled'] and plan['summary']['visits_planned']==1

def test_unavailability_preserves_started_visit(case):
    ref,day,matrix,old=case
    event=dict(event_id='out',type='STAFF_UNAVAILABLE',staff_id='ST-001',timestamp='2026-10-12T09:30:00+05:00',reason='ILLNESS',until='2026-10-12T11:30:00+05:00')
    _,plan=apply_event(ref,day,matrix,old,event,.1)
    assert plan['summary']['visits_planned']==1
    assert all(not datetime.fromisoformat(event['timestamp'])<=datetime.fromisoformat(s['start'])<datetime.fromisoformat(event['until']) for s in plan['routes'][0]['stops'])
    event['until']=None
    with pytest.raises(EventError,match='') as exc:apply_event(ref,day,matrix,old,event,.1)
    assert exc.value.code=='UNAVAILABILITY_BREAK_CONFLICT'

def test_new_order_and_transfer(case):
    ref,day,matrix,old=case;order=deepcopy(day['orders'][0]);order['order_id']='ORD-20261012-9000';order['registered_at']='2026-10-12T08:40:00+05:00'
    event=dict(event_id='new',type='NEW_ORDER',timestamp=order['registered_at'],order=order)
    state,plan=apply_event(ref,day,matrix,old,event,.2)
    assert len(state['orders'])==2 and plan['summary']['orders_total']==2
    visit=next(s for s in old['routes'][0]['stops'] if s['type']=='VISIT')
    event=dict(event_id='transfer',type='ORDER_TRANSFERRED',staff_id='ST-001',order_id=visit['order_id'],timestamp='2026-10-12T09:30:00+05:00',actual_end='2026-10-12T09:30:00+05:00',transferred_to='STATION_EQUIPMENT')
    _,plan=apply_event(ref,day,matrix,old,event,.1)
    assert next(s for s in plan['routes'][0]['stops'] if s['type']=='VISIT')['end']==event['actual_end']

def test_idempotency_conflict_and_time_validation():
    repo=DemoRepository();client=TestClient(create_app(Settings(source='demo'),repo))
    repo.calculate(date(2026,10,12),1)
    event=dict(event_id='tick',type='TIME_TICK',timestamp='2026-10-12T08:45:00+05:00')
    r=client.post('/api/v1/days/2026-10-12/events',json=event)
    assert r.status_code==200,r.text
    validate('EventResult',r.json())
    again=client.post('/api/v1/days/2026-10-12/events',json=event)
    assert again.json()['duplicate'] and again.json()['plan_version']==2
    conflict=client.post('/api/v1/days/2026-10-12/events',json=dict(event,timestamp='2026-10-12T08:46:00+05:00'))
    assert conflict.status_code==409
    assert client.post('/api/v1/days/2026-10-12/events',json=dict(event,event_id='early',timestamp='2026-10-12T08:40:00+05:00')).status_code==409
    assert client.post('/api/v1/days/2026-10-12/plan',json={'time_limit_sec':1}).status_code==409
    assert client.post('/api/v1/days/2026-10-12/events',json={'type':'OTHER'}).status_code==400
    assert client.post('/api/v1/days/2026-10-12/events',json=[]).status_code==400


def test_outage_before_shift_defers_unstarted_depot(case):
    ref,day,matrix,_=deepcopy(case)
    person=ref['staff'][0]
    person['shift']=dict(start='12:00',end='21:00',break_duration_min=60,break_window={'from':'15:00','to':'18:00'})
    order=day['orders'][0]
    order.update(slot=dict(start='2026-10-12T15:00:00+05:00',end='2026-10-12T17:00:00+05:00'),latest_start='2026-10-12T17:00:00+05:00',deadline='2026-10-13T08:00:00+05:00')
    initial=build_plan(ref,day,matrix,1)
    event=dict(event_id='before-shift',type='STAFF_UNAVAILABLE',staff_id=person['staff_id'],timestamp='2026-10-12T09:00:00+05:00',until='2026-10-12T12:30:00+05:00',reason='VEHICLE_BREAKDOWN')
    state,plan=apply_event(ref,day,matrix,initial,event,.2)
    route=plan['routes'][0]
    assert route['stops'][0]['start']>=event['until']
    assert any(s['type']=='VISIT' for s in route['stops'])
    from planner.validate import validate_plan
    assert validate_plan(ref,state,matrix,plan,initial,event)


def test_unknown_event_reference_is_422_and_does_not_advance_plan():
    repo=DemoRepository()
    with TestClient(create_app(Settings(source='demo'),repo)) as client:
        before=repo.calculate(date(2026,10,12),1)
        for key,value in [('order_id','ORD-20261012-9999'),('staff_id','ST-999')]:
            event=dict(event_id='unknown-'+key,timestamp='2026-10-12T08:40:00+05:00')
            if key=='order_id':event.update(type='ORDER_CANCELLED',order_id=value,reason='CUSTOMER_REQUEST')
            else:event.update(type='STAFF_UNAVAILABLE',staff_id=value,reason='ILLNESS')
            response=client.post('/api/v1/days/2026-10-12/events',json=event)
            assert response.status_code==422,response.text
            assert repo.plans['2026-10-12']==before
            assert repo.journal=={}
