"""Prepare a citywide sample in tmp/city-data; existing data remains untouched.

OSM building download caches are kept only in ignored tmp/geodata-cache.
The five service centers remain fictional, on real addressed buildings.
"""
import hashlib
import json
import random
import sys
from pathlib import Path
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from osm_geometry import inside, interior, select_spread, distance_m
from generate_data import dump

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'tmp'/'city-data'
CACHE=ROOT/'tmp'/'geodata-cache'
ZONES=[('north',60.60,56.90),('northeast',60.65,56.88),
       ('center',60.60,56.835),('west',60.535,56.825),
       ('southwest',60.52,56.785),('south',60.605,56.775),
       ('southeast',60.68,56.80),('east',60.675,56.845)]

def download(url):
    cache=CACHE/(hashlib.sha256(url.encode()).hexdigest()+'.cache')
    if cache.exists():return cache.read_bytes()
    print('Fetching '+url,flush=True)
    with urlopen(Request(url,headers={'User-Agent':'FieldDispatchHackathon/1.0'}),timeout=45) as response:
        raw=response.read()
    cache.parent.mkdir(parents=True,exist_ok=True);cache.write_bytes(raw)
    return raw

def city_rings():
    raw=json.loads(download('https://api.openstreetmap.org/api/0.6/relation/6564910/full.json'))
    nodes={e['id']:(e['lon'],e['lat']) for e in raw['elements'] if e['type']=='node'}
    ways={e['id']:e for e in raw['elements'] if e['type']=='way'}
    city=next(e for e in raw['elements'] if e['type']=='relation' and e['id']==6564910)
    assert city['tags']['name']=='Екатеринбург'
    def join(role):
        parts=[[nodes[n] for n in ways[m['ref']]['nodes']] for m in city['members'] if m['type']=='way' and m['role']==role]
        rings=[]
        while parts:
            ring=parts.pop()
            while ring[0]!=ring[-1]:
                for i,p in enumerate(parts):
                    if p[0]==ring[-1]:ring+=p[1:];parts.pop(i);break
                    if p[-1]==ring[-1]:ring+=p[-2::-1];parts.pop(i);break
                else:raise ValueError('Open city boundary')
            rings.append(ring)
        return rings
    return join('outer'),join('inner')

def main():
    outer,inner=city_rings();candidates={}
    for zone,x,y in ZONES:
        bbox=f'{x-.018},{y-.013},{x+.018},{y+.013}'
        xml=ET.fromstring(download('https://api.openstreetmap.org/api/0.6/map?bbox='+bbox))
        nodes={int(n.attrib['id']):(float(n.attrib['lon']),float(n.attrib['lat'])) for n in xml.findall('node')}
        count=0
        for way in xml.findall('way'):
            tags={t.attrib['k']:t.attrib['v'] for t in way.findall('tag')}
            if tags.get('building') not in ('apartments','house','detached','terrace','residential') or not tags.get('addr:street') or not tags.get('addr:housenumber'):continue
            ring=[nodes[int(n.attrib['ref'])] for n in way.findall('nd')]
            if len(ring)<4 or ring[0]!=ring[-1]:continue
            try:lon,lat=interior(ring)
            except ValueError:continue
            if not any(inside(lon,lat,r) for r in outer) or any(inside(lon,lat,r) for r in inner):continue
            osm_id=int(way.attrib['id'])
            candidates[osm_id]=dict(osm_id=osm_id,osm_type='way',lon=lon,lat=lat,ring=ring,zone=zone,
                building_type='PRIVATE' if tags['building'] in ('house','detached','terrace') else 'MKD',
                address='Екатеринбург, '+tags['addr:street']+', '+tags['addr:housenumber'],tags=tags)
            count+=1
        print(f'{zone}: {count} addressed buildings inside city',flush=True)
    used=set();rng=random.Random(20261115);homes={}
    pools={kind:select_spread([p for p in candidates.values() if p['building_type']==kind],count,rng,used)
           for kind,count in [('MKD',30),('PRIVATE',50)]}
    for z in range(5):
        for t in range(4):
            for b in range(4):
                kind='PRIVATE' if t in (2,3) or t==0 and b>=2 else 'MKD'
                homes[f'B-{z*16+t*4+b+1:05}']=pools[kind].pop()
    assert len({p['zone'] for p in homes.values()})>=7,'Insufficient city coverage'
    centers={}
    for i,zone in enumerate(['north','west','south','east','center'],1):
        options=[p for p in candidates.values() if p['zone']==zone and p['building_type']=='MKD' and p['osm_id'] not in used]
        point=rng.choice(options);used.add(point['osm_id']);centers[f'SC-{i:02}']=point
    assert min(distance_m(a,b) for i,a in enumerate(centers.values()) for b in list(centers.values())[i+1:])>1500
    dump(OUT/'provenance'/'real_locations.json',dict(source='https://api.openstreetmap.org/api/0.6',
        city='Екатеринбург',city_relation=6564910,city_outer_rings=outer,city_inner_rings=inner,
        buildings=homes,service_centers=centers,
        note='Synthetic centers and telecom data; real OSM addresses and strictly interior footprint points.'))
    dump(OUT/'provenance'/'spatial_distribution.json',dict(method='occupied-cell sample independent of depots',
        sample_zones={z:sum(p['zone']==z for p in homes.values()) for z,_,_ in ZONES},
        centers={k:p['zone'] for k,p in centers.items()},homes=80,service_centers=5))
    print('Prepared 80 homes + 5 centers in '+str(OUT),flush=True)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main()
