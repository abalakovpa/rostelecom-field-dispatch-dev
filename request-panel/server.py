"""Local-only order entry tool. Uses the real REST API; no direct DB writes."""
import json,csv,uuid,os
from pathlib import Path
from datetime import datetime,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
ROOT=Path('/app')
API_URL=os.environ.get('API_URL','http://api:8080')
def api(method,path,payload=None):
    request=Request(API_URL+path,data=json.dumps(payload).encode() if payload is not None else None,method=method,headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=330) as response:return json.load(response)
def data(name):return json.loads((ROOT/'data'/name).read_text(encoding='utf-8-sig'))
works=list(csv.DictReader((ROOT/'data/work_types.csv').open(encoding='utf-8-sig')))
for work in works:
    work['profiles']=work['profiles'].split('|');work['pgp_relevant']=work['pgp_relevant']=='true'
    for key in ['duration_min','max_start_delay_min','deadline_value','repeat_deadline_value']:work[key]=int(work[key]) if work[key] else None
reference=dict(service_centers=data('service_centers.json'),staff=data('staff.json'),access_nodes=data('access_nodes.json'),work_types=works)
buildings=[dict(b,access_node_id=n['access_node_id'],technology=n['technology']) for n in reference['access_nodes'] for b in n['buildings']]
class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def send(self,status,body,kind='application/json; charset=utf-8'):
        raw=body.encode() if isinstance(body,str) else json.dumps(body,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def proxy(self):
        if not self.path.startswith(('/api/','/static/')) and self.path!='/map':self.send(404,{'error':'Not found'});return
        path='/' if self.path=='/map' else self.path
        try:
            raw=None
            if self.command=='POST':
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<2*1024*1024:self.send(400,{'error':'Invalid body size'});return
                raw=self.rfile.read(size)
            request=Request(API_URL+path,data=raw,method=self.command,headers={'Content-Type':'application/json'})
            with urlopen(request,timeout=330) as response:
                raw=response.read();self.send_response(response.status);self.send_header('Content-Type',response.headers.get('Content-Type','application/octet-stream'));self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        except HTTPError as error:self.send(error.code,json.load(error))
    def do_GET(self):
        if self.path=='/map' or self.path.startswith(('/api/','/static/')):self.proxy();return
        if self.path=='/catalog':self.send(200,{'buildings':buildings,'works':works});return
        if self.path=='/':self.send(200,(Path(__file__).parent/'index.html').read_text(encoding='utf-8-sig'),'text/html; charset=utf-8');return
        self.send(404,{'error':'Not found'})
    def do_POST(self):
        if self.path.startswith('/api/'):
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':self.send(415,{'error':'JSON required'});return
            self.proxy();return
        if self.headers.get('X-Requested-With')!='request-panel':self.send(403,{'error':'Panel header required'});return
        if self.path=='/seed':
            try:
                current=api('GET','/api/ui/bootstrap')
                if current['days'] or current['staff']:self.send(409,{'error':'Database already has reference data; automatic replacement is blocked'});return
                api('PUT','/api/v1/reference/travel-matrix',data('travel_matrix.json'));api('PUT','/api/v1/reference',reference)
                self.send(200,{'status':'loaded','staff':len(reference['staff']),'addresses':len(buildings)})
            except HTTPError as error:self.send(error.code,json.load(error))
            return
        if self.path!='/create':self.send(404,{'error':'Not found'});return
        try:
            size=int(self.headers.get('Content-Length',0));assert 0<size<65536
            body=json.loads(self.rfile.read(size));building=next(b for b in buildings if b['building_id']==body['building_id'])
            work=next(w for w in works if w['code']==body['work_type_code'])
            day=body['date'];start=datetime.fromisoformat(day+'T'+body['time']+':00+05:00');end=start+timedelta(hours=2)
            days=api('GET','/api/ui/bootstrap')['days'];loaded=next((d for d in days if d['date']==day),None)
            if loaded is None:
                now=day+'T00:00:00+05:00';api('PUT','/api/v1/days/'+day,dict(date=day,now=now,orders=[]));api('POST','/api/v1/days/'+day+'/plan',{'time_limit_sec':20})
            else:
                now=loaded['model_now'];existing=api('GET','/api/ui/days/'+day)
                if existing['plan'] is None:api('POST','/api/v1/days/'+day+'/plan',{'time_limit_sec':20})
            order_id='ORD-'+day.replace('-','')+'-'+str(int(uuid.uuid4().hex[:6],16)%9000+1000)
            order={k:building[k] for k in ['building_id','address','lat','lon','building_type','access_node_id','technology']}
            latest=start+timedelta(minutes=work['max_start_delay_min'] if work['max_start_delay_min'] is not None else 120)
            order.update(order_id=order_id,work_type_code=work['code'],requires_height=bool(building.get('overhead_line')),registered_at=now,slot={'start':start.isoformat(),'end':end.isoformat()},latest_start=latest.isoformat(),deadline=(start+timedelta(days=3)).isoformat(),required_equipment={'ONT':1 if building['technology']=='PON' else 0,'ROUTER':1,'STB':0},is_repeat=False,previous_order_id=None)
            result=api('POST','/api/v1/days/'+day+'/events',dict(event_id='LOCAL-'+str(uuid.uuid4()),type='NEW_ORDER',timestamp=now,order=order))
            bootstrap=api('GET','/api/ui/bootstrap');assignment=None;reason=None
            for entry in bootstrap['days']:
                plan=api('GET','/api/ui/days/'+entry['date'])['plan']
                for route in (plan or {}).get('routes',[]):
                    for stop in route['stops']:
                        if stop.get('order_id')==order_id:assignment=dict(date=entry['date'],staff_id=route['staff_id'],start=stop['start'],end=stop['end'])
                for item in (plan or {}).get('unassigned',[]):
                    if item['order_id']==order_id:reason=item
            self.send(200,dict(order_id=order_id,assignment=assignment,reason=reason,result=result))
        except HTTPError as error:self.send(error.code,json.load(error))
        except Exception as error:self.send(400,{'error':str(error)})
print('Request panel listening on port 8082',flush=True)
ThreadingHTTPServer(('0.0.0.0',8082),Handler).serve_forever()



