"""Road geometry for display only. Solver durations always come from the loaded matrix."""
import json
from functools import lru_cache
from urllib.request import Request,urlopen

@lru_cache(maxsize=256)
def road_route(coordinates):
    if len(coordinates)<2:return {'geometry':{'type':'LineString','coordinates':[]},'legs':[]}
    points=';'.join(f'{lon},{lat}' for lon,lat in coordinates)
    url='http://router.project-osrm.org/route/v1/driving/'+points+'?overview=full&geometries=geojson&steps=true'
    with urlopen(Request(url,headers={'User-Agent':'DispatcherHackathon/1.0'}),timeout=12) as response:
        result=json.load(response)
    if result.get('code')!='Ok' or not result.get('routes'):raise ValueError('OSRM returned no route')
    route=result['routes'][0];legs=[]
    for leg in route['legs']:
        vertices=[]
        for step in leg['steps']:
            for point in step['geometry']['coordinates']:
                if not vertices or vertices[-1]!=point:vertices.append(point)
        legs.append({'type':'LineString','coordinates':vertices})
    return {'geometry':route['geometry'],'legs':legs}

def road_geometry(coordinates):return road_route(coordinates)['geometry']
