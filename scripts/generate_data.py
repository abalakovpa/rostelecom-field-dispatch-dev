"""Reproducible synthetic case data. Road matrix requires an OSRM table response."""
import argparse
import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data'
TZ = timezone(timedelta(hours=5))
SEED = 20261113
TECHS = ['PON', 'FTTB', 'XDSL', 'DOCSIS']
ANCHORS = [(56.8941,60.6105),(56.8698,60.6510),(56.8380,60.5970),
           (56.8070,60.6100),(56.8220,60.5500)]
FIELDS = ['code','name','profiles','duration_min','max_start_delay_min',
          'deadline_kind','deadline_value','repeat_deadline_value','pgp_relevant']
WORK = [
 ('INST_PON_MKD','Инсталляция ШПД/IPTV, МКД, PON',['INSTALL'],90,10,'WORKING_DAYS',3,None,False),
 ('INST_FTTB_MKD','Инсталляция ШПД/IPTV, МКД, FTTB',['INSTALL'],60,10,'WORKING_DAYS',3,None,False),
 ('INST_PRIVATE_VLS','Инсталляция, частный сектор, с ВЛС',['INSTALL'],180,10,'WORKING_DAYS',5,None,False),
 ('ADD_SERVICE','Доподключение услуги (IPTV, Wi-Fi-роутер)',['INSTALL'],40,10,'SLOT',None,None,False),
 ('SURVEY_PRIVATE','Обследование (частный сектор)',['INSTALL','LTP3'],45,None,'WORKING_DAYS',2,None,False),
 ('REPAIR','Устранение неисправности (обращение абонента)',['LTP3'],60,None,'HOURS',24,12,True),
 ('DEGRADATION','Устранение деградации, выявленной системой мониторинга качества',['LTP3'],45,None,'HOURS',48,None,True),
 ('DISMANTLE','Демонтаж АО',['LTP3'],30,None,'WORKING_DAYS',5,None,False),
]

def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def dt(day, hour, minute=0):
    return datetime.combine(day, datetime.min.time(), TZ).replace(hour=hour, minute=minute)

def iso(value):
    return value.isoformat(timespec='seconds')

def working_add(value, count):
    # Generated dates are in October 2026: no Russian public holidays in this range.
    while count:
        value += timedelta(days=1)
        if value.weekday() < 5:
            count -= 1
    return value

def reference():
    centers, nodes, staff = [], [], []
    for z, (lat, lon) in enumerate(ANCHORS):
        sid = f'SC-{z+1:02}'
        centers.append(dict(service_center_id=sid, name=f'Синтетический СЦ {z+1}',
            address=f'Екатеринбург, синтетическая площадка СЦ №{z+1}', lat=lat,lon=lon,
            opening_hours={'open':'08:00','close':'21:00'}, restock_duration_min=15))
        for t, tech in enumerate(TECHS):
            buildings = []
            for b in range(4):
                idx = z*16+t*4+b+1
                private = tech in ('XDSL','DOCSIS') or (tech=='PON' and b>=2)
                buildings.append(dict(building_id=f'B-{idx:05}',
                    address=f'Екатеринбург, синтетический адрес №{idx:03}',
                    lat=round(lat+(t-1.5)*0.003+(b-1.5)*0.001,6),
                    lon=round(lon+(b-1.5)*0.004+(t-1.5)*0.001,6),
                    building_type='PRIVATE' if private else 'MKD',
                    overhead_line=private and b%2==0,zone_service_center_id=sid))
            nodes.append(dict(access_node_id=f'AN-{z*4+t+1:04}',
                node_type=['OLT','SWITCH','DSLAM','CMTS'][t],technology=tech,
                name=f'Синтетический узел {z+1}/{tech}',lat=lat,lon=lon,buildings=buildings))
    for i in range(40):
        late = i%2==1
        staff.append(dict(staff_id=f'ST-{i+1:03}', display_name=f'Сотрудник {i+1:03}',
            service_center_id=f'SC-{i%5+1:02}',profiles=['LTP3' if i<28 else 'INSTALL'],
            technologies=TECHS[:] if i%4==0 else (['PON','FTTB'] if i%4<3 else ['XDSL','DOCSIS']),
            height_permit=i%3!=0,shift={'start':'12:00' if late else '09:00',
                'end':'21:00' if late else '18:00','break_duration_min':60,
                'break_window':{'from':'15:00' if late else '12:00','to':'18:00' if late else '15:00'}},
            equipment_start={'ONT':3,'ROUTER':4,'STB':2},
            equipment_capacity={'ONT':6,'ROUTER':6,'STB':4},experience_years=round(0.5+i%12*0.7,1)))
    locations_path=OUT/'provenance'/'real_locations.json'
    if not locations_path.exists():
        raise RuntimeError('Real addressed buildings are required. Run scripts/fetch_real_buildings.py first.')
    locations=json.loads(locations_path.read_text(encoding='utf-8'))
    for center in centers:
        point=locations['service_centers'][center['service_center_id']]
        center.update({k:point[k] for k in ('lat','lon','address')})
    for node in nodes:
        for building in node['buildings']:
            point=locations['buildings'][building['building_id']]
            if point['building_type']!=building['building_type']:raise ValueError('OSM building type mismatch')
            building.update({k:point[k] for k in ('lat','lon','address')})
        node.update({k:node['buildings'][0][k] for k in ('lat','lon')})
    return centers, staff, nodes

def matrix(centers, nodes, fetch):
    pts = centers+[b for n in nodes for b in n['buildings']]
    ids = [p.get('service_center_id',p.get('building_id')) for p in pts]
    coords = ';'.join(f"{p['lon']},{p['lat']}" for p in pts)
    endpoint = 'http://router.project-osrm.org'
    url = endpoint+'/table/v1/driving/'+coords+'?annotations=duration,distance'
    coord_hash = hashlib.sha256(coords.encode()).hexdigest()
    cache = ROOT/'tmp'/'geodata-cache'/('osrm-'+coord_hash+'.json')
    if fetch:
        with urlopen(Request(url,headers={'User-Agent':'HackathonSyntheticDataset/1.0'}),timeout=55) as response:
            raw = json.load(response)
        if raw.get('code') != 'Ok':
            raise ValueError(raw)
        dump(cache, {'coordinate_sha256':coord_hash,'response':raw})
    if not cache.exists():
        raise RuntimeError('No road data. Run once with --fetch-osrm. No straight-line fallback is allowed.')
    cached = json.loads(cache.read_text(encoding='utf-8'))
    if cached['coordinate_sha256']!=coord_hash:
        raise ValueError('OSRM cache coordinates differ from current reference')
    raw = cached['response']
    n = len(pts)
    for key in ['durations','distances']:
        values=raw[key]
        if len(values)!=n or any(len(row)!=n for row in values):
            raise ValueError('Non-square OSRM response')
        if any(x is None or x<0 for row in values for x in row):
            raise ValueError('Unreachable points; do not invent road connections')
    # Fixed synthetic 180 s for parking and walking, included once per distinct-point trip.
    durations=[[0 if i==j else math.ceil(x)+180 for j,x in enumerate(row)] for i,row in enumerate(raw['durations'])]
    distances=[[0 if i==j else math.ceil(x) for j,x in enumerate(row)] for i,row in enumerate(raw['distances'])]
    locations=json.loads((OUT/'provenance'/'real_locations.json').read_text(encoding='utf-8'))
    result=dict(matrix_id='ekb-city-osm-v1' if locations.get('city_relation') else 'ekb-ordzhonikidzevsky-osm-v3',points=ids,durations_sec=durations,distances_m=distances)
    return result, dict(endpoint=endpoint,service='table/v1/driving',
        coordinate_sha256=coord_hash,parking_and_walking_sec=180,
        data_version=raw.get('data_version'),rounding='ceil; diagonal=0',point_count=n,
        max_snap_distance_m=max(x['distance'] for x in raw['sources']))

def generate_orders(nodes, rng):
    works={w[0]:dict(zip(FIELDS,w)) for w in WORK}
    homes=[(n,b) for n in nodes for b in n['buildings']]
    by_code={}
    for code in works:
        by_code[code]=[(n,b) for n,b in homes if
            (code!='INST_PON_MKD' or n['technology']=='PON' and b['building_type']=='MKD') and
            (code!='INST_FTTB_MKD' or n['technology']=='FTTB' and b['building_type']=='MKD') and
            (code!='INST_PRIVATE_VLS' or b['building_type']=='PRIVATE' and b['overhead_line']) and
            (code!='SURVEY_PRIVATE' or b['building_type']=='PRIVATE')]
    orders, days, incidents = [], [], []
    current=date(2026,10,12)
    while len(days)<10:
        if current.weekday()<5: days.append(current)
        current+=timedelta(days=1)
    # For each day/node, all ordinary PGP-relevant registrations are >60 min apart.
    # Exactly three explicit incident orders are planted on one reserved node per day.
    for day_index, day in enumerate(days):
        reserved=nodes[day_index%len(nodes)]
        reg_slots={n['access_node_id']:[dt(day,7)-timedelta(minutes=75*k) for k in range(20)] for n in nodes}
        incident_ids=[]
        for i in range(350):
            incident=i<3
            repeat=False
            if incident:
                code='REPAIR'; node=reserved; building=node['buildings'][i]
                registered=dt(day,7,10)+timedelta(minutes=15*i)
            else:
                code=rng.choices(list(works),[8,8,3,9,6,43,17,6])[0]
                if works[code]['pgp_relevant']:
                    candidates=[(n,b) for n,b in by_code[code]
                        if n!=reserved and reg_slots[n['access_node_id']]]
                    if not candidates: raise ValueError('Not enough non-colliding PGP registration slots')
                    node,building=rng.choice(candidates)
                    registered=reg_slots[node['access_node_id']].pop(0)
                else:
                    node,building=rng.choice(by_code[code]); registered=dt(day,7)
            work=works[code]
            # Repeats reference an actual completed predecessor on the same synthetic subscriber/technology.
            predecessors=[o for o in orders if o['building_id']==building['building_id']
                and o['technology']==node['technology'] and o['work_type_code']==code
                and o.get('fact',{}).get('outcome')=='COMPLETED'
                and 0<(registered-datetime.fromisoformat(o['fact']['actual_start'])).total_seconds()<6*86400]
            repeat=bool(predecessors) and code=='REPAIR' and not incident and rng.random()<0.2
            hour=rng.choice([9,11,13,15] if repeat else [9,11,13,15,17])
            if code=='INST_PRIVATE_VLS': hour=rng.choice([9,13,15])
            start=dt(day,hour); end=start+timedelta(hours=2)
            latest=start+timedelta(minutes=work['max_start_delay_min']) if work['max_start_delay_min'] is not None else end
            needed_end=latest+timedelta(minutes=work['duration_min'])
            if work['deadline_kind']=='HOURS':
                hours=work['repeat_deadline_value'] if repeat else work['deadline_value']
                # Preserve ordinary >60 min spacing by choosing a slot compatible with its deadline.
                valid=[h for h in [9,11,13,15,17] if dt(day,h)+timedelta(hours=2,minutes=work['duration_min'])<=registered+timedelta(hours=hours)]
                if not valid:
                    # Very old registrations are DEGRADATION (48h), not expired REPAIRs.
                    code='DEGRADATION'; work=works[code]; repeat=False; hours=48
                    valid=[h for h in [9,11,13,15,17] if dt(day,h)+timedelta(hours=2,minutes=45)<=registered+timedelta(hours=48)]
                hour=rng.choice(valid);start=dt(day,hour);end=start+timedelta(hours=2);latest=end
                deadline=registered+timedelta(hours=hours)
            elif work['deadline_kind']=='WORKING_DAYS':
                registered=dt(day,7)-timedelta(days=1 if day.weekday()!=0 else 3)
                deadline=working_add(registered,work['deadline_value'])
            else: deadline=end
            eq={'ONT':0,'ROUTER':0,'STB':0}
            if code.startswith('INST_'):
                eq['ONT']=int(node['technology']=='PON');eq['ROUTER']=1;eq['STB']=rng.randrange(2)
            elif code in ('REPAIR','DEGRADATION','ADD_SERVICE'):
                eq[rng.choice(['ROUTER','STB']+(['ONT'] if node['technology']=='PON' else []))]=1
            oid=f'ORD-{day:%Y%m%d}-{i+1:04}'
            item=dict(order_id=oid,work_type_code=code,technology=node['technology'],
                building_id=building['building_id'],address=building['address'],lat=building['lat'],lon=building['lon'],
                building_type=building['building_type'],requires_height=building['overhead_line'],
                access_node_id=node['access_node_id'],registered_at=iso(registered),
                slot={'start':iso(start),'end':iso(end)},latest_start=iso(latest),deadline=iso(deadline),
                required_equipment=eq,is_repeat=repeat,previous_order_id=predecessors[-1]['order_id'] if repeat else None)
            # Optional historical labels are filled by simulate_history(), never used in planner input.
            orders.append(item)
            if incident: incident_ids.append(oid)
        incidents.append(dict(date=str(day),access_node_id=reserved['access_node_id'],order_ids=incident_ids))
        # Complete labels for this day before later days choose repeat predecessors.
        # Simulation called by main after matrix is available (see historical_day callback).
        if historical_day is not None: historical_day(day,orders[-350:],incidents[-1])
    return orders, days, incidents

historical_day = None

def simulate_history(day, orders, incident, staff, travel, rng):
    index={pid:i for i,pid in enumerate(travel['points'])}
    def trip(a,b):return timedelta(seconds=travel['durations_sec'][index[a]][index[b]])
    states={s['staff_id']:dict(time=dt(day,int(s['shift']['start'][:2])),
        location=s['service_center_id'],equipment=s['equipment_start'].copy(),break_taken=False) for s in staff}
    for order in sorted(orders,key=lambda o:o['slot']['start']):
        if order['order_id'] in incident['order_ids']:
            order['fact']={'outcome':'PGP_GROUPED','pgp_incident_id':f'PGP-{day:%Y%m%d}-01'};continue
        work=next(w for w in WORK if w[0]==order['work_type_code'])
        candidates=[]
        for person in staff:
            if not set(person['profiles'])&set(work[2]) or order['technology'] not in person['technologies'] or order['requires_height'] and not person['height_permit']:continue
            state=states[person['staff_id']];time=state['time'];loc=state['location'];stock=state['equipment'].copy()
            took_break=state['break_taken'];break_from=dt(day,int(person['shift']['break_window']['from'][:2]));break_to=dt(day,int(person['shift']['break_window']['to'][:2]))
            # Take lunch before any later work would make its start miss the allowed window.
            projected_start=max(time+trip(loc,order['building_id']),datetime.fromisoformat(order['slot']['start']))
            if not took_break and projected_start+timedelta(minutes=work[3])>=break_from:
                time=max(time,break_from)
                if time>break_to:continue
                time+=timedelta(hours=1);took_break=True
            if any(stock[k]<v for k,v in order['required_equipment'].items()):
                time+=trip(loc,person['service_center_id'])+timedelta(minutes=15);loc=person['service_center_id'];stock=person['equipment_capacity'].copy()
            arrival=time+trip(loc,order['building_id']);start=max(arrival,datetime.fromisoformat(order['slot']['start']))
            duration=work[3] # Synthetic normative history, not predictions or a solver benchmark.
            end=start+timedelta(minutes=duration)
            shift_end=dt(day,int(person['shift']['end'][:2]))
            # Reserve a full lunch if still not taken, plus travel home.
            reserve=timedelta(hours=0 if took_break else 1)
            if start>datetime.fromisoformat(order['latest_start']) or end>datetime.fromisoformat(order['deadline']) or end+trip(order['building_id'],person['service_center_id'])+reserve>shift_end:continue
            candidates.append((start,person['staff_id'],end,stock,took_break))
        if not candidates:
            order['fact']={'outcome':'RESCHEDULED'};continue
        start,sid,end,stock,took_break=min(candidates,key=lambda x:(x[0],x[1]))
        for key,count in order['required_equipment'].items():stock[key]-=count
        states[sid]=dict(time=end,location=order['building_id'],equipment=stock,break_taken=took_break)
        order['fact']={'outcome':'COMPLETED','staff_id':sid,'actual_start':iso(start),'actual_duration_min':work[3]}

def scenario(orders, day, nodes):
    today=[o for o in orders if o['slot']['start'][:10]==str(day)]
    base=today[30]
    def new_order(number, node, building, timestamp):
        item={k:v for k,v in base.items() if k!='fact'}
        item.update(order_id=f'ORD-{day:%Y%m%d}-{number:04}',work_type_code='REPAIR',
            technology=node['technology'],building_id=building['building_id'],access_node_id=node['access_node_id'],
            address=building['address'],lat=building['lat'],lon=building['lon'],building_type=building['building_type'],
            requires_height=building['overhead_line'],registered_at=iso(timestamp),
            slot={'start':iso(dt(day,15)),'end':iso(dt(day,17))},latest_start=iso(dt(day,17)),
            deadline=iso(timestamp+timedelta(hours=24)),is_repeat=False,previous_order_id=None,
            required_equipment={'ONT':0,'ROUTER':1,'STB':0})
        return item
    events=[]
    def add(kind,time,**kwargs):events.append(dict(event_id=f'EV-{day:%Y%m%d}-{len(events)+1:04}',type=kind,timestamp=iso(time),**kwargs))
    add('TIME_TICK',dt(day,9))
    # Reserve a different node from initial incident. Three new orders within 40 min.
    node=nodes[-1]
    for i in range(3):
        time=dt(day,10)+timedelta(minutes=20*i)
        add('NEW_ORDER',time,order=new_order(350+i+1,node,node['buildings'][i],time))
    cancellation=next(o for o in today[3:] if o['slot']['start'][11:13]>='15')
    add('ORDER_CANCELLED',dt(day,11),order_id=cancellation['order_id'],reason='CUSTOMER_REQUEST')
    add('STAFF_UNAVAILABLE',dt(day,11,30),staff_id='ST-001',until=iso(dt(day,14)),reason='VEHICLE_BREAKDOWN')
    add('TIME_TICK',dt(day,14))
    add('STAFF_UNAVAILABLE',dt(day,16),staff_id='ST-002',until=None,reason='ILLNESS')
    add('TIME_TICK',dt(day,20,30))
    eligible=[o for o in today[3:] if o['work_type_code']=='REPAIR' and o['order_id']!=cancellation['order_id']]
    triggers=[dict(trigger_id=f'TR-{day:%Y%m%d}-01',type='VISIT_DELAYED',order_id=eligible[0]['order_id'],fire_after_start_min=15,extra_duration_min=30),
              dict(trigger_id=f'TR-{day:%Y%m%d}-02',type='ORDER_TRANSFERRED',order_id=eligible[1]['order_id'],fire_after_start_min=10,transferred_to='STATION_EQUIPMENT'),
              dict(trigger_id=f'TR-{day:%Y%m%d}-03',type='ORDER_TRANSFERRED',order_id=eligible[2]['order_id'],fire_after_start_min=10,transferred_to='TRUNK_CABLE')]
    return dict(date=str(day),now=iso(dt(day,8,30)),events=events,triggers=triggers)

def main():
    global OUT
    parser=argparse.ArgumentParser();parser.add_argument('--fetch-osrm',action='store_true');parser.add_argument('--data-dir',type=Path,default=OUT);args=parser.parse_args()
    OUT=args.data_dir.resolve()
    rng=random.Random(SEED);centers,staff,nodes=reference()
    travel,source=matrix(centers,nodes,args.fetch_osrm)
    global historical_day
    historical_day=lambda day,rows,incident:simulate_history(day,rows,incident,staff,travel,rng)
    orders,days,incidents=generate_orders(nodes,rng)
    for name,value in [('service_centers',centers),('staff',staff),('access_nodes',nodes),('travel_matrix',travel),('orders_train',orders),('events_example',scenario(orders,days[0],nodes))]:
        dump(OUT/(name+'.json'),value)
    with (OUT/'work_types.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(FIELDS)
        for row in WORK:
            writer.writerow(['|'.join(x) if isinstance(x,list) else '' if x is None else str(x).lower() if isinstance(x,bool) else x for x in row])
    dump(OUT/'provenance'/'incidents.json',incidents)
    files=['service_centers.json','staff.json','access_nodes.json','work_types.csv','travel_matrix.json','orders_train.json','events_example.json']
    dump(OUT/'manifest.json',dict(seed=SEED,synthetic=True,days=[str(d) for d in days],
        geography={**{k:v for k,v in json.loads((OUT/'provenance'/'real_locations.json').read_text(encoding='utf-8')).items() if k in ('city','city_relation','district','district_relation')},'locations':'provenance/real_locations.json'},
        counts={'service_centers':len(centers),'staff':len(staff),'access_nodes':len(nodes),
            'buildings':80,'orders':len(orders),'orders_per_day':350},routing=source,
        hashes={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in files}))
    print('Generated: 5 centers, 40 staff, 20 nodes, 80 buildings, 3500 orders, 85x85 road matrix.')

if __name__=='__main__':main()
