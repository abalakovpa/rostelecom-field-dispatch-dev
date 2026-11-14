"""Internal calculation service; state remains owned by Fastify."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from policies import calculate

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length',0))
            if not 0<size<=100*1024*1024: raise ValueError('Invalid body size')
            request=json.loads(self.rfile.read(size))
            result=calculate(request)
            self.respond(200,result)
        except Exception as error:
            self.respond(422,{'error':{'code':'CALCULATION_FAILED','message':str(error)}})
    def respond(self,status,result):
        raw=json.dumps(result,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

HTTPServer(('0.0.0.0',8090),Handler).serve_forever()

