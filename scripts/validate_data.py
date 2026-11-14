"""Validate supplied data against original OpenAPI 3.0 schemas and case invariants."""
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
# Optional local installation used on machines without a configured virtual environment.
if (ROOT/'tmp'/'check-deps').exists():sys.path.insert(0,str(ROOT/'tmp'/'check-deps'))
import yaml
from jsonschema import Draft7Validator, FormatChecker
from generate_data import WORK, FIELDS, TZ, working_add

DATA=ROOT/'data'

def require(value,message):
    if not value:raise ValueError(message)

def read(name):return json.loads((DATA/name).read_text(encoding='utf-8'))

def convert(value):
    """Translate OpenAPI 3.0 nullable into JSON Schema without editing the source."""
    if isinstance(value,list):return [convert(x) for x in value]
    if not isinstance(value,dict):return value
    result={k:convert(v) for k,v in value.items() if k not in ('nullable','discriminator','example','xml')}
    return {'anyOf':[result,{'type':'null'}]} if value.get('nullable') else result

def work_rows():
    with (DATA/'work_types.csv').open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream)
        require(reader.fieldnames==FIELDS,'CSV header must match WorkType fields')
        rows=[]
        for row in reader:
            row['profiles']=row['profiles'].split('|')
            for key in ['duration_min','max_start_delay_min','deadline_value','repeat_deadline_value']:
                row[key]=None if row[key]=='' else int(row[key])
            require(row['pgp_relevant'] in ('true','false'),'CSV boolean')
            row['pgp_relevant']=row['pgp_relevant']=='true';rows.append(row)
        return rows

def main():
    source=yaml.safe_load((ROOT/'api_spec.yaml').read_text(encoding='utf-8'))
    document=convert({'components':source['components']})
    def schema(name,value):
        validator=Draft7Validator(dict(document,**{'$ref':f'#/components/schemas/{name}'}),format_checker=FormatChecker())
        errors=list(validator.iter_errors(value))
        if errors:raise ValueError(f'{name}: {list(errors[0].absolute_path)}: {errors[0].message}')
    centers=read('service_centers.json');staff=read('staff.json');nodes=read('access_nodes.json')
    orders=read('orders_train.json');matrix=read('travel_matrix.json');scenario=read('events_example.json');works=work_rows()
    for name,value in [('ServiceCentersFile',centers),('StaffFile',staff),('AccessNodesFile',nodes),
        ('OrdersFile',orders),('TravelMatrix',matrix),('EventScenarioFile',scenario)]:schema(name,value)
    for row in works:schema('WorkType',row)
    schema('ReferenceData',dict(service_centers=centers,staff=staff,access_nodes=nodes,work_types=works))
    require(works==[dict(zip(FIELDS,row)) for row in WORK],'Norms must match PDF case table')
    require(len(centers)==5 and len(staff)==40 and len(orders)==3500,'Case scale')
    require(Counter(p['profiles'][0] for p in staff)=={'LTP3':28,'INSTALL':12},'28 LTP3 + 12 INSTALL')
    lookup={row['code']:row for row in works};scids={c['service_center_id'] for c in centers}
    people={s['staff_id']:s for s in staff}
    require(len(scids)==5 and len(people)==40,'Unique center/staff IDs')
    from osm_geometry import inside
    locations=read('provenance/real_locations.json')
    location_points=list(locations['buildings'].values())+list(locations['service_centers'].values())
    require(len({p['osm_id'] for p in location_points})==85,'Unique real OSM buildings')
    for point in location_points:
        require(inside(point['lon'],point['lat'],point['ring']),'Marker must be inside building footprint')
        require(any(inside(point['lon'],point['lat'],ring) for ring in locations.get('city_outer_rings',locations.get('district_rings',[]))),'Marker outside geography')
        require(not any(inside(point['lon'],point['lat'],ring) for ring in locations.get('city_inner_rings',[])),'Marker in city boundary hole')
    for center in centers:
        point=locations['service_centers'][center['service_center_id']]
        require(all(center[k]==point[k] for k in ['lat','lon','address']),'Real service center building location')
    homes={};node_lookup={n['access_node_id']:n for n in nodes}
    require(len(node_lookup)==len(nodes),'Unique nodes')
    for n in nodes:
        require(dict(OLT='PON',SWITCH='FTTB',DSLAM='XDSL',CMTS='DOCSIS')[n['node_type']]==n['technology'],'Node technology')
        for b in n['buildings']:
            point=locations['buildings'][b['building_id']]
            require(all(b[k]==point[k] for k in ['lat','lon','address','building_type']),'Real addressed building location')
            require(b['building_id'] not in homes or homes[b['building_id']]==b,'Repeated building conflict')
            homes[b['building_id']]=b
    for p in staff:
        require(p['service_center_id'] in scids,'Staff center reference')
        require(p['shift']['break_duration_min']==60,'Case lunch = 60 min')
        require((p['shift']['start'],p['shift']['end']) in [('09:00','18:00'),('12:00','21:00')],'Case shifts')
        require(all(p['equipment_start'][k]<=p['equipment_capacity'][k] for k in ['ONT','ROUTER','STB']),'Equipment capacity')
    ids=matrix['points'];n=len(ids)
    require(set(ids)==scids|set(homes) and len(ids)==len(set(ids)),'Matrix point coverage')
    for key in ['durations_sec','distances_m']:
        require(len(matrix[key])==n and all(len(row)==n for row in matrix[key]),'Matrix NxN')
        require(all(matrix[key][i][i]==0 for i in range(n)),'Zero matrix diagonal')
    by_day=defaultdict(list);by_id={o['order_id']:o for o in orders}
    require(len(by_id)==3500,'Unique order IDs')
    for order in orders:
        b=homes[order['building_id']];node=node_lookup[order['access_node_id']];w=lookup[order['work_type_code']]
        require(b in node['buildings'] and order['technology']==node['technology'],'Order node/building/technology')
        for key in ['address','lat','lon','building_type']:require(order[key]==b[key],f'Building {key}')
        require(order['requires_height']==b['overhead_line'],'Height requirement')
        start=datetime.fromisoformat(order['slot']['start']);end=datetime.fromisoformat(order['slot']['end'])
        registered=datetime.fromisoformat(order['registered_at']);latest=datetime.fromisoformat(order['latest_start']);deadline=datetime.fromisoformat(order['deadline'])
        require(end-start==timedelta(hours=2),'Two-hour slot')
        expected=min(end,start+timedelta(minutes=w['max_start_delay_min'])) if w['max_start_delay_min'] is not None else end
        require(latest==expected and latest+timedelta(minutes=w['duration_min'])<=deadline,'Latest start and deadline')
        value=w['repeat_deadline_value'] if order['is_repeat'] and w['repeat_deadline_value'] else w['deadline_value']
        expected_deadline=end if w['deadline_kind']=='SLOT' else registered+timedelta(hours=value) if w['deadline_kind']=='HOURS' else working_add(registered,value)
        require(deadline==expected_deadline,'Deadline rule')
        if order['is_repeat']:
            prev=by_id[order['previous_order_id']]
            require(prev['fact']['outcome']=='COMPLETED' and prev['building_id']==order['building_id'] and prev['technology']==order['technology'],'Repeat predecessor')
            closed=datetime.fromisoformat(prev['fact']['actual_start'])+timedelta(minutes=prev['fact']['actual_duration_min'])
            require(timedelta(0)<registered-closed<=timedelta(days=7),'Repeat within 7 days after closure')
        fact=order['fact']
        if fact['outcome']=='COMPLETED':
            person=people[fact['staff_id']];actual=datetime.fromisoformat(fact['actual_start'])
            require(set(person['profiles'])&set(w['profiles']) and order['technology'] in person['technologies'],'Historical qualification')
            require(not order['requires_height'] or person['height_permit'],'Historical height permit')
            require(start<=actual<=latest and actual+timedelta(minutes=fact['actual_duration_min'])<=deadline,'Historical visit window')
        by_day[str(start.astimezone(TZ).date())].append(order)
    require(len(by_day)==10 and set(map(len,by_day.values()))=={350},'10 days x 350 orders')
    require(all(datetime.fromisoformat(d).weekday()<5 for d in by_day),'Working days')
    for day, rows in by_day.items():
        now=day+'T08:30:00+05:00'
        require(all(datetime.fromisoformat(o['registered_at'])<=datetime.fromisoformat(now) for o in rows),'Initial availability')
        schema('DayInput',dict(date=day,now=now,orders=[{k:v for k,v in o.items() if k!='fact'} for o in rows],absent_staff_ids=[]))
    # Verify all planted groups and absence of accidental 3-in-60-min windows.
    incidents=read('provenance/incidents.json');expected_groups={(x['date'],x['access_node_id']):set(x['order_ids']) for x in incidents}
    for day, rows in by_day.items():
        for node_id in node_lookup:
            relevant=sorted([o for o in rows if o['access_node_id']==node_id and lookup[o['work_type_code']]['pgp_relevant']],key=lambda o:o['registered_at'])
            for i,order in enumerate(relevant):
                t=datetime.fromisoformat(order['registered_at'])
                group={o['order_id'] for o in relevant[i:] if datetime.fromisoformat(o['registered_at'])-t<=timedelta(hours=1)}
                if len(group)>=3:require(group==expected_groups.get((day,node_id)),f'Accidental PGP: {day}/{node_id}')
        incident=next(x for x in incidents if x['date']==day)
        require(all(by_id[oid]['fact']['outcome']=='PGP_GROUPED' for oid in incident['order_ids']),'PGP labels')
    events=scenario['events'];event_ids=[e['event_id'] for e in events]
    require(len(event_ids)==len(set(event_ids)),'Unique event IDs')
    require([e['timestamp'] for e in events]==sorted(e['timestamp'] for e in events),'Chronological events')
    known={o['order_id'] for o in by_day[scenario['date']]}
    for e in events:
        if e['type']=='NEW_ORDER':
            require(e['order']['order_id'] not in known,'New order collision');known.add(e['order']['order_id'])
            require(e['order']['registered_at']==e['timestamp'],'New order registration')
        if 'order_id' in e:require(e['order_id'] in known,'Event order reference')
        if 'staff_id' in e:require(e['staff_id'] in people,'Event staff reference')
    require({e['type'] for e in events}|{t['type'] for t in scenario['triggers']}==set(source['components']['schemas']['EventType']['enum']),'All event types covered')
    for trigger in scenario['triggers']:require(trigger['order_id'] in known,'Trigger reference')
    manifest=read('manifest.json')
    for name,digest in manifest['hashes'].items():require(hashlib.sha256((DATA/name).read_bytes()).hexdigest()==digest,'Checksum '+name)
    outcomes=Counter(o['fact']['outcome'] for o in orders)
    report=dict(status='PASS',openapi_version=source['info']['version'],orders=len(orders),days=len(by_day),staff=len(staff),
        service_centers=len(centers),matrix_points=n,repeat_orders=sum(o['is_repeat'] for o in orders),
        planted_pgp_groups=len(incidents),events=len(events),triggers=len(scenario['triggers']),historical_outcomes=dict(outcomes),
        checks=['OSM building footprints and geography membership','OpenAPI schemas','PDF norms and scale','foreign references','slots and deadlines','repeat predecessors',
            'matrix coverage and dimensions','PGP registration windows','event chronology and types','file checksums'],
        limitations=['Not a hidden organizer dataset','No solver or event processing run has been evaluated'])
    (DATA/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,default=DATA);args=parser.parse_args()
    DATA=args.data_dir.resolve();sys.stdout.reconfigure(encoding='utf-8');main()
