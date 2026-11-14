"""Internal calculation service; state remains owned by Fastify."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from planner_openapi import plan_openapi

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length',0))
            if not 0<size<=100*1024*1024: raise ValueError('Invalid body size')
            request=json.loads(self.rfile.read(size))
            previous=request.get('previous_plan')
            event=request.get('event')
            cancelled=list((previous or {}).get('cancelled',[]))
            if event and event['type']=='ORDER_CANCELLED':
                begun=any(s.get('order_id')==event['order_id'] and s['start']<event['timestamp'] for r in previous['routes'] for s in r['stops'])
                if not begun and not any(c['order_id']==event['order_id'] for c in cancelled):
                    cancelled.append(dict(order_id=event['order_id'],cancelled_at=event['timestamp'],event_id=event['event_id']))
            result=plan_openapi(request['reference'],request['matrix'],request['day'],previous=previous,event=event,
                cancelled=cancelled,pgp_groups=(previous or {}).get('pgp_groups',[]),time_limit_sec=request.get('time_limit_sec',7 if event else 25))
            self.respond(200,result)
        except Exception as error:
            self.respond(422,{'error':{'code':'CALCULATION_FAILED','message':str(error)}})
    def respond(self,status,result):
        raw=json.dumps(result,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

HTTPServer(('0.0.0.0',8090),Handler).serve_forever()
