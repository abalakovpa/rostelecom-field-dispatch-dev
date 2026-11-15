from compatibility import work_fits_building
from debug_events import make_event
from order_ids import choose_order_id
from deadlines import calculate_deadline
"""Local-only order entry tool. Uses the real REST API; no direct DB writes."""
import json,csv,uuid,os
from pathlib import Path
from datetime import datetime,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit,parse_qs
ROOT=Path('/app')
API_URL=os.environ.get('API_URL','http://api:8080')
def api(method,path,payload=None):
    request=Request(API_URL+path,data=json.dumps(payload).encode() if payload is not None else None,method=method,headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=35) as response:return json.load(response)
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
        raw=body.encode() if isinstance(body,str) else json.dumps(body,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def proxy(self):
        is_map=urlsplit(self.path).path=='/map'
        if not self.path.startswith(('/api/','/static/')) and not is_map:self.send(404,{'error':'Not found'});return
        path='/' if is_map else self.path
        try:
            raw=None
            if self.command=='POST':
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<2*1024*1024:self.send(400,{'error':'Invalid body size'});return
                raw=self.rfile.read(size)
            request=Request(API_URL+path,data=raw,method=self.command,headers={'Content-Type':'application/json'})
            with urlopen(request,timeout=35) as response:
                raw=response.read()
                if is_map and parse_qs(urlsplit(self.path).query).get('debug')==['1']:
                    raw+=b'<script type="module" src="/static/debug-map.js"></script>'
                self.send_response(response.status);self.send_header('Content-Type',response.headers.get('Content-Type','application/octet-stream'));self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        except HTTPError as error:self.send(error.code,json.load(error))
    def do_GET(self):
        if self.path=='/debug.js':self.send(200,(Path(__file__).parent/'debug.js').read_text(encoding='utf-8'),'text/javascript; charset=utf-8');return
        if self.path=='/load.js':self.send(200,(Path(__file__).parent/'load.js').read_text(encoding='utf-8'),'text/javascript; charset=utf-8');return
        if self.path=='/inventory.js':self.send(200,(Path(__file__).parent/'inventory.js').read_text(encoding='utf-8'),'text/javascript; charset=utf-8');return
        if self.path.startswith('/stats?'):
            try:
                date=parse_qs(urlsplit(self.path).query).get('date',[''])[0]
                payload=api('GET','/api/ui/days/'+date);plan=payload.get('plan')
                total=len(payload['orders']);assigned=len({s['order_id'] for r in (plan or {}).get('routes',[]) for s in r['stops'] if s['type']=='VISIT'})
                self.send(200,{'date':date,'total':total,'assigned':assigned,'unassigned':len((plan or {}).get('unassigned',[])),'pending':total if plan is None else 0,'transferred':len((plan or {}).get('transferred_orders',[])),'risks':len({a['order_id'] for a in (plan or {}).get('alerts',[]) if a['type']=='LATE_RISK' and a['status']=='ACTIVE' and a.get('order_id')}),'plan_built':plan is not None})
            except HTTPError as error:
                if error.code==404:self.send(200,{'date':date,'total':0,'assigned':0,'unassigned':0,'pending':0,'transferred':0,'risks':0,'plan_built':False})
                else:self.send(error.code,json.load(error))
            return
        if urlsplit(self.path).path=='/map' or self.path.startswith(('/api/','/static/')):self.proxy();return
        if self.path=='/catalog':self.send(200,api('GET','/api/ui/catalog'));return
        if self.path=='/':self.send(200,(Path(__file__).parent/'index.html').read_text(encoding='utf-8-sig'),'text/html; charset=utf-8');return
        self.send(404,{'error':'Not found'})
    def do_POST(self):
        if self.path.startswith('/api/'):
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':self.send(415,{'error':'JSON required'});return
            self.proxy();return
        if self.headers.get('X-Requested-With')!='request-panel':self.send(403,{'error':'Panel header required'});return
        if self.path=='/debug/event':
            try:
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<65536:raise ValueError('Некорректный размер запроса')
                body=json.loads(self.rfile.read(size));day=body['date']
                snapshot=api('GET','/api/ui/days/'+day)
                event=make_event(body,snapshot)
                result=api('POST','/api/v1/days/'+day+'/events',event)
                self.send(200,{'event':event,'result':result})
            except HTTPError as error:self.send(error.code,json.load(error))
            except TimeoutError:self.send(504,{'error':'Ответ задерживается. Обновите снимок перед повторной отправкой.'})
            except Exception as error:self.send(400,{'error':str(error)})
            return
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
            body=json.loads(self.rfile.read(size));catalog=api('GET','/api/ui/catalog')
            building=next(b for b in catalog['buildings'] if b['building_id']==body['building_id'])
            work=next(w for w in catalog['works'] if w['code']==body['work_type_code'])
            equipment=body.get('required_equipment',{'ONT':1 if building['technology']=='PON' else 0,'ROUTER':1,'STB':0})
            if not isinstance(equipment,dict) or set(equipment)!={'ONT','ROUTER','STB'} or any(type(v) is not int or not 0<=v<=10000 for v in equipment.values()):raise ValueError('Оборудование: ONT, ROUTER и STB должны быть целыми неотрицательными количествами')
            if not work_fits_building(building,work):self.send(422,{'error':{'code':'WORK_BUILDING_MISMATCH','message':'Этот тип работы не подходит адресу: проверьте тип дома и технологию.'}});return
            day=body['date'];start=datetime.fromisoformat(day+'T'+body['time']+':00+05:00');end=start+timedelta(hours=2)
            days=api('GET','/api/ui/bootstrap')['days'];loaded=next((d for d in days if d['date']==day),None)
            if loaded is None:
                now=day+'T00:00:00+05:00';api('PUT','/api/v1/days/'+day,dict(date=day,now=now,orders=[]));api('POST','/api/v1/days/'+day+'/plan',{'time_limit_sec':20})
            else:
                now=loaded['model_now'];existing=api('GET','/api/ui/days/'+day)
                if existing['plan'] is None:api('POST','/api/v1/days/'+day+'/plan',{'time_limit_sec':20})
            request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,str(body['request_id']))) if body.get('request_id') else str(uuid.uuid4())
            usage=api('GET','/api/ui/days/'+day+'/debug-orders/'+request_id)
            order_id=choose_order_id(day,request_id,usage)
            order={k:building[k] for k in ['building_id','address','lat','lon','building_type','access_node_id','technology']}
            latest=start+timedelta(minutes=work['max_start_delay_min'] if work['max_start_delay_min'] is not None else 120)
            order.update(order_id=order_id,work_type_code=work['code'],requires_height=work['code']=='INST_PRIVATE_VLS' or bool(building['building_type']=='PRIVATE' and building.get('overhead_line')),registered_at=now,slot={'start':start.isoformat(),'end':end.isoformat()},latest_start=latest.isoformat(),deadline=calculate_deadline(work,now,end.isoformat()),required_equipment={'ONT':1 if building['technology']=='PON' else 0,'ROUTER':1,'STB':0},is_repeat=False,previous_order_id=None)
            if body.get('staff_id'):order['_test_staff_id']=body['staff_id']
            order['required_equipment']=equipment
            result=api('POST','/api/v1/days/'+day+'/events',dict(event_id='LOCAL-'+request_id,type='NEW_ORDER',timestamp=now,order=order))
            source_plan=api('GET','/api/ui/days/'+day)['plan']
            dates=[day]
            for transfer in reversed((source_plan or {}).get('transferred_orders',[])):
                if transfer['order_id']==order_id:
                    dates.insert(0,transfer['to_date']);break
            assignment=None;reason=None
            for date in dates:
                plan=source_plan if date==day else api('GET','/api/ui/days/'+date)['plan']
                for route in (plan or {}).get('routes',[]):
                    for stop in route['stops']:
                        if stop.get('order_id')==order_id:assignment=dict(date=date,staff_id=route['staff_id'],start=stop['start'],end=stop['end'])
                if assignment:break
                for item in (plan or {}).get('unassigned',[]):
                    if item['order_id']==order_id:reason=item
            self.send(200,dict(order_id=order_id,assignment=assignment,reason=reason,result=result))
        except HTTPError as error:self.send(error.code,json.load(error))
        except TimeoutError:self.send(504,{'error':'API response timed out; check the map before resubmitting the order'})
        except Exception as error:self.send(400,{'error':str(error)})
print('Request panel listening on port 8082',flush=True)
ThreadingHTTPServer(('0.0.0.0',8082),Handler).serve_forever()





