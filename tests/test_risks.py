from copy import deepcopy
from datetime import timedelta
import time
import pytest
from api.repository import DemoRepository
from api.contracts import validate
from planner.solver import Context,stamp,iso
from planner.events import apply_event
from planner.risks import forecast_routes,update_risk_alerts,feasible_alternative,feasible_slot

def risk_case(late=False,two_staff=True):
    repo=DemoRepository();person=deepcopy(repo.read('staff.json')[0]);person['profiles']=['INSTALL','LTP3'];person['technologies']=['PON']
    spare=deepcopy(person);spare['staff_id']='ST-999'
    ref=dict(service_centers=repo.read('service_centers.json'),access_nodes=repo.read('access_nodes.json'),staff=[person,spare] if two_staff else [person],work_types=repo._works())
    first=deepcopy(repo.read('orders_train.json')[0]);first.pop('fact',None)
    first['slot']={'start':f'2026-10-12T{10 if late else 9:02}:00:00+05:00','end':f'2026-10-12T{12 if late else 11:02}:00:00+05:00'};first['latest_start']=first['slot']['end']
    second=deepcopy(first);second.update(order_id='ORD-20261012-9001',work_type_code='INST_PON_MKD',slot={'start':'2026-10-12T11:00:00+05:00','end':'2026-10-12T13:00:00+05:00'},latest_start='2026-10-12T11:10:00+05:00',deadline='2026-10-12T18:00:00+05:00')
    day=dict(date='2026-10-12',now='2026-10-12T08:30:00+05:00',orders=[first,second]);matrix=repo.read('travel_matrix.json');ctx=Context(ref,day,matrix)
    route=ctx.schedule(person,[first,second]);assert route
    routes=[route]+([ctx.schedule(spare,[])] if two_staff else [])
    plan=dict(date=day['date'],plan_version=1,as_of=day['now'],routes=routes,unassigned=[],cancelled=[],pgp_groups=[],alerts=[])
    visit=next(s for s in route['stops'] if s.get('order_id')==first['order_id'])
    timestamp='2026-10-12T10:45:00+05:00' if late else iso(stamp(visit['start'])+timedelta(minutes=10))
    event=dict(event_id='DELAY-RISK',type='VISIT_DELAYED',timestamp=timestamp,staff_id=person['staff_id'],order_id=first['order_id'],expected_end='2026-10-12T11:35:00+05:00')
    return ref,day,matrix,plan,event,second

def test_forecast_survives_successful_automatic_reassignment():
    ref,day,matrix,old,event,order=risk_case()
    state,plan=apply_event(ref,day,matrix,old,event,.8)
    alert=next(a for a in plan['alerts'] if a['type']=='LATE_RISK')
    assert alert['forecast_start']=='2026-10-12T11:35:00+05:00' and alert['lateness_min']==25
    assert alert['created_at']==event['timestamp'] and alert['warning_deadline']=='2026-10-12T10:30:00+05:00' and alert['timely']
    assert alert['status']=='RESOLVED' and alert['applied'] and alert['suggested_staff_id']=='ST-999'
    validate('Plan',plan)

def test_late_discovery_is_not_backdated():
    ref,day,matrix,old,event,order=risk_case(late=True)
    _,plan=apply_event(ref,day,matrix,old,event,.8)
    alert=next(a for a in plan['alerts'] if a['type']=='LATE_RISK')
    assert not alert['timely'] and alert['created_at']==event['timestamp']

def test_tick_does_not_restart_an_inflight_leg():
    ref,day,matrix,old,event,order=risk_case()
    arrival=old['routes'][0]['stops'][1]['arrival'];departure=old['routes'][0]['stops'][0]['end']
    day['now']=iso(stamp(departure)+(stamp(arrival)-stamp(departure))/2)
    assert forecast_routes(ref,day,matrix,old)=={}

def test_recommendations_respect_qualification_and_hard_deadline():
    ref,day,matrix,old,event,order=risk_case()
    ctx=Context(ref,day,matrix);people={p['staff_id']:p for p in ref['staff']};jobs={p['staff_id']:[] for p in ref['staff']}
    people['ST-999']['height_permit']=False;order['requires_height']=True
    assert feasible_alternative(ctx,order,people,jobs,people['ST-001']['staff_id'],time.monotonic()+.1) is None
    order['deadline']=order['slot']['end']
    assert feasible_slot(ctx,order,people,jobs,time.monotonic()+.1) is None

def test_unavailable_staff_has_no_fabricated_eta():
    ref,day,matrix,old,event,order=risk_case()
    day.update(now=event['timestamp'],_unavailable={'ST-001':{'from':event['timestamp'],'until':None}})
    risk=forecast_routes(ref,day,matrix,old)[order['order_id']]
    assert risk['forecast_start'] is None and risk['lateness_min'] is None and not risk['forecast_available']

def test_active_alert_keeps_first_detection_and_closes_after_recovery():
    ref,day,matrix,old,event,order=risk_case(two_staff=False);state,plan=apply_event(ref,day,matrix,old,event,.8)
    a=next(a for a in plan['alerts'] if a['type']=='LATE_RISK');assert a['status']=='ACTIVE';created=a['created_at'];alert_id=a['alert_id']
    event2=dict(event_id='TICK-LATER',type='TIME_TICK',timestamp=iso(stamp(event['timestamp'])+timedelta(minutes=1)))
    state2,plan2=apply_event(ref,state,matrix,plan,event2,.8)
    prior=next(a for a in plan2['alerts'] if a['alert_id']==alert_id)
    assert prior['created_at']==created
    # Explicitly cancel an unstarted job: the existing warning is resolved, not removed.
    event3=dict(event_id='CANCEL-RISK',type='ORDER_CANCELLED',timestamp=event2['timestamp'],order_id=order['order_id'],reason='CUSTOMER_REQUEST')
    _,plan3=apply_event(ref,state2,matrix,plan2,event3,.8)
    assert next(a for a in plan3['alerts'] if a['alert_id']==alert_id)['status']=='RESOLVED'
