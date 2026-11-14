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
