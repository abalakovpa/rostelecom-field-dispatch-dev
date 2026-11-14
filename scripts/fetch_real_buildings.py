"""Select addressed residential OSM footprints and strictly interior marker points."""
import json
import ssl
import os
import math
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import certifi
from generate_data import ANCHORS, OUT, reference, dump

def inside(x,y,ring):
    result=False
    for a,b in zip(ring,ring[1:]):
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:result=not result
    return result

def interior(ring):
    # Pick a scanline between vertex latitudes, then the midpoint of an interior span.
    levels=sorted(set(p[1] for p in ring));middle=(levels[0]+levels[-1])/2
    for y in sorted([(a+b)/2 for a,b in zip(levels,levels[1:])],key=lambda y:abs(y-middle)):
        xs=sorted(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]) for a,b in zip(ring,ring[1:]) if (a[1]>y)!=(b[1]>y))
        spans=list(zip(xs[::2],xs[1::2]))
        if spans:
            a,b=max(spans,key=lambda ab:ab[1]-ab[0]);x=(a+b)/2
            if b>a and inside(x,y,ring):return x,y
    raise ValueError('No interior point')

def distance_m(a,b):
    return math.hypot((a['lat']-b['lat'])*111320,(a['lon']-b['lon'])*111320*0.55)

def select_spread(candidates,count,rng,used,min_distance=100):
    """Sample occupied 600 m cells, independently of service-center locations.

    Square-root density weights preserve some real density variation without
    allowing a handful of dense streets to dominate the small sample.
    """
    pool=sorted([p for p in candidates if p['osm_id'] not in used],key=lambda p:p['osm_id'])
    chosen=[];streets={};cells={}
    for p in pool:
        key=(math.floor(p['lon']*111320*0.55/600),math.floor(p['lat']*111320/600))
        cells.setdefault(key,[]).append(p)
    while len(chosen)<count:
        options={}
        for key,rows in cells.items():
            valid=[p for p in rows if p['osm_id'] not in used
                and streets.get(p['tags']['addr:street'],0)<5
                and all(distance_m(p,q)>=min_distance for q in chosen)]
            if valid:options[key]=valid
        if not options:raise ValueError('Insufficient distinct buildings for spatial sample')
        # Prefer cells not yet represented, retaining a stochastic density weight.
        counts={key:sum(math.floor(p['lon']*111320*0.55/600)==key[0] and math.floor(p['lat']*111320/600)==key[1] for p in chosen) for key in options}
        keys=list(options)
        key=rng.choices(keys,weights=[math.sqrt(len(options[k]))/(1+counts[k])**2 for k in keys])[0]
        p=rng.choice(options[key]);chosen.append(p);used.add(p['osm_id'])
        street=p['tags']['addr:street'];streets[street]=streets.get(street,0)+1
    rng.shuffle(chosen)
    return chosen

def main():
    cache=OUT/'provenance'/'osm_ordzhonikidzevsky_raw.json'
    if not cache.exists() and os.getenv('OSM_DIRECT')=='1':
        context=ssl.create_default_context(cafile=certifi.where())
        def download(url):
            cache_path=OUT/'provenance'/('osm_download_'+__import__('hashlib').sha256(url.encode()).hexdigest()[:16]+'.cache')
            if cache_path.exists():return cache_path.read_bytes()
            with urlopen(Request(url,headers={'User-Agent':'DispatcherHackathon/1.0'}),timeout=45,context=context) as stream:data=stream.read()
            cache_path.parent.mkdir(parents=True,exist_ok=True);cache_path.write_bytes(data);return data
        full=json.loads(download('https://api.openstreetmap.org/api/0.6/relation/5819002/full.json'))
        points={e['id']:(e['lon'],e['lat']) for e in full['elements'] if e['type']=='node'}
        ways={e['id']:e for e in full['elements'] if e['type']=='way'}
        district=next(e for e in full['elements'] if e['type']=='relation' and e['id']==5819002)
        for m in district['members']:
            if m['type']=='way':m['geometry']=[dict(lon=points[n][0],lat=points[n][1]) for n in ways[m['ref']]['nodes']]
        buildings={}
        for bbox in [f'{x},{y},{x+0.03:.3f},{y+0.02:.3f}' for x in [60.56,60.59,60.62,60.65] for y in [56.88,56.90,56.92]]:
            xml=ET.fromstring(download('https://api.openstreetmap.org/api/0.6/map?bbox='+bbox))
            points={int(n.attrib['id']):(float(n.attrib['lon']),float(n.attrib['lat'])) for n in xml.findall('node')}
            for way in xml.findall('way'):
                tags={t.attrib['k']:t.attrib['v'] for t in way.findall('tag')}
                if tags.get('building') not in ('apartments','house','detached','terrace','residential') or not tags.get('addr:street') or not tags.get('addr:housenumber'):continue
                ring=[points[int(n.attrib['ref'])] for n in way.findall('nd')]
                buildings[int(way.attrib['id'])]=dict(type='way',id=int(way.attrib['id']),tags=tags,geometry=[dict(lon=x,lat=y) for x,y in ring])
        dump(cache,dict(elements=[district,*buildings.values()],source='https://api.openstreetmap.org/api/0.6',osm3s={}))
    if not cache.exists():
        query='[out:json][timeout:45];rel(5819002)->.district;.district out geom;.district map_to_area->.a;way(area.a)["building"~"^(apartments|house|detached|terrace|residential)$"]["addr:street"]["addr:housenumber"];out tags geom;'
        url=os.getenv('OVERPASS_ENDPOINT','https://overpass.private.coffee/api/interpreter')+'?'+urlencode({'data':query})
        with urlopen(Request(url,headers={'User-Agent':'DispatcherHackathon/1.0'}),timeout=55,context=ssl.create_default_context(cafile=certifi.where())) as stream:raw=json.load(stream)
        if raw.get('remark'):raise ValueError(raw['remark'])
        dump(cache,raw)
    raw=json.loads(cache.read_text(encoding='utf-8'));candidates=[]
    district=next(e for e in raw['elements'] if e['type']=='relation' and e['id']==5819002)
    if any(m.get('role')=='inner' for m in district['members']):
        raise ValueError('District has holes: explicit inner-ring handling required')
    segments=[[(p['lon'],p['lat']) for p in m['geometry']] for m in district['members'] if m.get('role')=='outer' and m.get('geometry')]
    rings=[]
    while segments:
        ring=segments.pop(0)
        while ring[0]!=ring[-1]:
            for i,s in enumerate(segments):
                if s[0]==ring[-1]:ring+=s[1:];segments.pop(i);break
                if s[-1]==ring[-1]:ring+=list(reversed(s))[1:];segments.pop(i);break
            else:raise ValueError('District boundary is not closed')
        rings.append(ring)
    for element in raw['elements']:
        if element['type']!='way':continue
        ring=[(p['lon'],p['lat']) for p in element.get('geometry',[])]
        if len(ring)<4 or ring[0]!=ring[-1]:continue
        try:x,y=interior(ring)
        except ValueError:continue
        if not any(inside(x,y,r) for r in rings):continue
        tags=element['tags']
        candidates.append(dict(osm_id=element['id'],osm_type='way',lon=x,lat=y,ring=ring,
            building_type='PRIVATE' if tags['building'] in ('house','detached','terrace') else 'MKD',
            address='Екатеринбург, '+tags['addr:street']+', '+tags['addr:housenumber'],tags=tags))
    used=set();selected={};centers={};rng=random.Random(20261114)
    pools={kind:select_spread([p for p in candidates if p['building_type']==kind],count,rng,used)
        for kind,count in [('MKD',30),('PRIVATE',50)]}
    for z in range(5):
        for t in range(4):
            for b in range(4):
                kind='PRIVATE' if t in (2,3) or t==0 and b>=2 else 'MKD'
                selected[f'B-{z*16+t*4+b+1:05}']=pools[kind].pop()
    # Centers are sampled only AFTER the homes, from different real buildings.
    depot_points=select_spread([p for p in candidates if p['building_type']=='MKD'],5,random.Random(982714),used,min_distance=900)
    centers={f'SC-{i+1:02}':p for i,p in enumerate(depot_points)}
    nearest=[min(distance_m(p,c) for c in depot_points) for p in selected.values()]
    dump(OUT/'provenance'/'spatial_distribution.json',dict(method='stochastic occupied-cell sample, independent of depots',
        cell_size_m=600,min_same_type_spacing_m=100,homes=80,streets=len({p['tags']['addr:street'] for p in selected.values()}),
        nearest_depot_median_m=round(sorted(nearest)[40]),homes_within_500m_of_any_depot=sum(d<500 for d in nearest)))
    dump(OUT/'provenance'/'real_locations.json',dict(source=raw.get('source','OpenStreetMap / Overpass API'),
        osm_timestamp=raw.get('osm3s',{}).get('timestamp_osm_base'),district='Орджоникидзевский район',district_relation=5819002,district_rings=rings,buildings=selected,service_centers=centers,
        note='Centers and telecom attributes are synthetic; only addresses and building footprints come from OSM.'))
    print('Selected 80 addressed homes + 5 distinct building locations for synthetic centers; all points inside footprints.')

if __name__=='__main__':main()
