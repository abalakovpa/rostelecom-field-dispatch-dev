"""Disposable integration smoke check: Fastify + PostgreSQL + Pavel planner + UI."""
import argparse,json
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:18081');parser.add_argument('--allow-reset',action='store_true');args=parser.parse_args()
if not args.allow_reset: parser.error('Requires --allow-reset against a disposable service')
root=Path(__file__).resolve().parents[1]
example=json.loads((root/'docs/examples/planner-openapi.json').read_text(encoding='utf-8-sig'))
def call(method,path,data=None,expected=200):
    raw=json.dumps(data).encode() if data is not None else None
    try:
        with urlopen(Request(args.url+path,data=raw,method=method,headers={'Content-Type':'application/json'}),timeout=60) as response: status=response.status;body=json.load(response)
    except HTTPError as error: status=error.code;body=json.load(error)
    assert status==expected,(method,path,status,body)
    print(method,path,status,flush=True);return body
call('GET','/api/v1/health')
call('PUT','/api/v1/reference',example['reference'])
call('PUT','/api/v1/reference/travel-matrix',example['matrix'])
day=example['day'];path='/api/v1/days/'+day['date']
call('PUT',path,day)
plan=call('POST',path+'/plan',{'time_limit_sec':10})
assert plan['plan_version']==1
bootstrap=call('GET','/api/ui/bootstrap');assert bootstrap['days'][0]['date']==day['date']
ui=call('GET','/api/ui/days/'+day['date']);assert ui['plan']['plan_version']==1
updated=call('POST',path+'/events',example['event']);assert updated['plan_version']==2
assert call('GET',path+'/plan')['plan_version']==2
assert call('POST',path+'/events',example['event'])['duplicate']
before=call('GET',path+'/plan')
call('POST',path+'/events',{'event_id':'bad','type':'TIME_TICK'},400)
assert call('GET',path+'/plan')==before
with urlopen(args.url+'/') as r:assert b'<html' in r.read().lower()
with urlopen(args.url+'/static/app.js') as r:assert r.status==200
print('INTEGRATION SMOKE PASSED')
# Explicitly exercise interruption and preserve the record outside completed visits.
outage={'event_id':'OUTAGE-SMOKE','type':'STAFF_UNAVAILABLE','timestamp':'2026-10-26T09:40:00+05:00','staff_id':'ST-001','until':'2026-10-26T10:30:00+05:00','reason':'ILLNESS'}
response=call('POST',path+'/events',outage);assert response['plan_version']==3
outage_plan=call('GET',path+'/plan');assert outage_plan['interrupted_visits']
assert outage_plan['interrupted_visits'][0]['staff_id']=='ST-001'
print('INTERRUPTION SMOKE PASSED')

# Automatic new slot must be persisted, and UI must read the same slot.
# Earlier outage interrupts the first visit; the original window is already missed.
assert outage_plan['automatic_reschedules'],outage_plan
ui=call('GET','/api/ui/days/'+day['date'])
for change in outage_plan['automatic_reschedules']:
    order=next(o for o in ui['orders'] if o['order_id']==change['order_id'])
    assert order['slot_start']==change['slot']['start']
print('AUTOMATIC RESCHEDULE PERSISTENCE PASSED')

# Independent incident fixture: four repair-like orders linked as metadata,
# each still accounted once by an individual visit or unassigned record.
from copy import deepcopy
incident_ref=deepcopy(example['reference'])
for work in incident_ref['work_types']:work['pgp_relevant']=True
call('PUT','/api/v1/reference',incident_ref)
call('PUT','/api/v1/reference/travel-matrix',example['matrix'])
incident_day=deepcopy(example['day'])
for o in incident_day['orders']:o['registered_at']=incident_day['now']
call('PUT',path,incident_day)
initial=call('POST',path+'/plan',{'time_limit_sec':5})
assert len(initial['incident_groups'])==1
identity=initial['incident_groups'][0]['group_id']
fourth=deepcopy(incident_day['orders'][0]);fourth['order_id']='ORD-20261026-0999'
event={'event_id':'FOURTH-INCIDENT','type':'NEW_ORDER','timestamp':incident_day['now'],'order':fourth}
call('POST',path+'/events',event)
expanded=call('GET',path+'/plan')
assert expanded['incident_groups'][0]['group_id']==identity
assert len(expanded['incident_groups'][0]['order_ids'])==4
assert not expanded['pgp_groups']
assert sum(s['type']=='VISIT' for r in expanded['routes'] for s in r['stops'])+len(expanded['unassigned'])==4
print('INCIDENT EXPANSION PERSISTENCE PASSED')

# Next-day transfer must reserve the destination calendar and survive duplicate delivery.
import sys
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/'tests'))
sys.path.insert(0,str(root/'planner-service'))
from test_automatic_policy import FutureCalendarTest
request=FutureCalendarTest().request(True)
call('PUT','/api/v1/reference',request['reference'])
call('PUT','/api/v1/reference/travel-matrix',request['matrix'])
target=request['calendar']['2026-10-27']['input']
call('PUT','/api/v1/days/2026-10-27',target)
booked=call('POST','/api/v1/days/2026-10-27/plan',{'time_limit_sec':5})
source=deepcopy(request['day']);source['now']='2026-10-26T08:30:00+05:00'
call('PUT',path,source);call('POST',path+'/plan',{'time_limit_sec':5})
call('POST',path+'/events',request['event'])
source_plan=call('GET',path+'/plan');assert source_plan['transferred_orders']
transfer=source_plan['transferred_orders'][0];assert transfer['to_date']=='2026-10-27'
future_ui=call('GET','/api/ui/days/2026-10-27')
assert any(o['order_id']==transfer['order_id'] for o in future_ui['orders'])
future_plan=call('GET','/api/v1/days/2026-10-27/plan')
assert any(s.get('order_id')==transfer['order_id'] for r in future_plan['routes'] for s in r['stops'])
old={(r['staff_id'],s['order_id'],s['start'],s['end']) for r in booked['routes'] for s in r['stops'] if s['type']=='VISIT'}
new={(r['staff_id'],s['order_id'],s['start'],s['end']) for r in future_plan['routes'] for s in r['stops'] if s['type']=='VISIT'}
assert old<=new
assert call('POST',path+'/events',request['event'])['duplicate']
assert call('GET','/api/v1/days/2026-10-27/plan')==future_plan
print('NEXT-DAY CALENDAR PERSISTENCE PASSED')

# A tick during the return leg must preserve a feasible ETA after transfer.
return_day = json.loads(json.dumps(example['day']))
return_day['date'] = '2026-10-28'
def return_time(clock):
    return f"{return_day['date']}T{clock}:00+05:00"

return_day['now'] = return_time('11:30')
order = return_day['orders'][0]
order.update(
    order_id='ORD-20261028-0001',
    registered_at=return_time('11:00'),
    slot={'start': return_time('19:29'), 'end': return_time('21:29')},
    latest_start=return_time('19:39'),
    deadline=return_time('21:00'),
)
return_day['orders'] = [order]
reference = json.loads(json.dumps(example['reference']))
reference['staff'][0]['shift'].update(
    start='12:00', end='21:00', break_window={'from': '15:00', 'to': '17:00'},
)
matrix = json.loads(json.dumps(example['matrix']))
home = reference['staff'][0]['service_center_id']
origin = matrix['points'].index(order['building_id'])
destination = matrix['points'].index(home)
matrix['durations_sec'][origin][destination] = 45 * 60
call('PUT', '/api/v1/reference', reference)
call('PUT', '/api/v1/reference/travel-matrix', matrix)
return_path = '/api/v1/days/' + return_day['date']
call('PUT', return_path, return_day)
initial = call('POST', return_path + '/plan', {'time_limit_sec': 10})
route = initial['routes'][0]
visit = next(stop for stop in route['stops'] if stop.get('order_id') == order['order_id'])
assert visit['start'] == return_time('19:29') and visit['end'] == return_time('20:14')
assert route['stops'][-1]['arrival'] == return_time('20:59')
transfer = {
    'type': 'ORDER_TRANSFERRED', 'event_id': 'RETURN-TRANSFER',
    'timestamp': return_time('20:10'), 'actual_end': return_time('20:10'),
    'staff_id': route['staff_id'], 'order_id': order['order_id'],
    'transferred_to': 'TRUNK_CABLE',
}
assert call('POST', return_path + '/events', transfer)['plan_version'] == 2
after_transfer = call('GET', return_path + '/plan')
transferred_route = after_transfer['routes'][0]
transferred_visit = next(stop for stop in transferred_route['stops'] if stop.get('order_id') == order['order_id'])
assert transferred_route['staff_id'] == route['staff_id']
assert all(transferred_visit[field] == visit[field] for field in ('order_id', 'location_id', 'arrival', 'start'))
assert transferred_visit['end'] == transfer['actual_end']
return_stop = transferred_route['stops'][-1]
assert return_stop['type'] == 'DEPOT_END' and return_stop['location_id'] == home
assert return_time('20:55') <= return_stop['arrival'] <= return_time('21:00')

tick = {'type': 'TIME_TICK', 'event_id': 'RETURN-TICK', 'timestamp': return_time('20:30')}
assert call('POST', return_path + '/events', tick)['plan_version'] == 3
after_tick = call('GET', return_path + '/plan')
assert after_tick['as_of'] == tick['timestamp']
assert after_tick['routes'][0]['staff_id'] == transferred_route['staff_id']
assert after_tick['routes'][0]['stops'] == transferred_route['stops'], after_tick['routes'][0]['stops']
print('IN-FLIGHT RETURN AFTER ORDER_TRANSFERRED PASSED')

