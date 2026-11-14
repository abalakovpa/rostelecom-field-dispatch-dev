"""Emit one coherent reference+matrix payload; contains no runtime credentials."""
from pathlib import Path
import csv,json
root=Path(__file__).resolve().parents[1];data=root/'data'
def read(name):return json.loads((data/name).read_text(encoding='utf-8-sig'))
with (data/'work_types.csv').open(encoding='utf-8-sig',newline='') as stream:works=list(csv.DictReader(stream))
for work in works:
    work['profiles']=work['profiles'].split('|');work['pgp_relevant']=work['pgp_relevant']=='true'
    for key in ('duration_min','max_start_delay_min','deadline_value','repeat_deadline_value'):work[key]=int(work[key]) if work[key] else None
print(json.dumps({'reference':dict(service_centers=read('service_centers.json'),staff=read('staff.json'),access_nodes=read('access_nodes.json'),work_types=works),'matrix':read('travel_matrix.json')},ensure_ascii=True))
