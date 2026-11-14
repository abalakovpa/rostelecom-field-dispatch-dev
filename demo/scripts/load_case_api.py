"""Upload the local case files through the organizer API (replaces all loaded days)."""
import argparse
import csv
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8083')
    args=parser.parse_args()
    def read(name):return json.loads((ROOT/'data'/name).read_text(encoding='utf-8'))
    def put(path,payload):
        request=Request(args.url.rstrip('/')+'/api/v1/'+path,data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),
            method='PUT',headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=60) as response:result=json.load(response)
        print(path+': '+json.dumps(result,ensure_ascii=False))
    with (ROOT/'data/work_types.csv').open(encoding='utf-8',newline='') as stream:works=list(csv.DictReader(stream))
    for work in works:
        work['profiles']=work['profiles'].split('|')
        for key in ['duration_min','max_start_delay_min','deadline_value','repeat_deadline_value']:
            work[key]=int(work[key]) if work[key] else None
        work['pgp_relevant']=work['pgp_relevant']=='true'
    reference=dict(service_centers=read('service_centers.json'),staff=read('staff.json'),access_nodes=read('access_nodes.json'),work_types=works)
    put('reference',reference)
    put('reference/travel-matrix',read('travel_matrix.json'))
    orders=read('orders_train.json')
    from datetime import datetime
    for day in sorted({o['slot']['start'][:10] for o in orders}):
        now=day+'T08:30:00+05:00'
        known=[o for o in orders if o['slot']['start'][:10]==day and datetime.fromisoformat(o['registered_at'])<=datetime.fromisoformat(now)]
        put('days/'+day,dict(date=day,now=now,orders=known))

if __name__=='__main__':main()
