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

