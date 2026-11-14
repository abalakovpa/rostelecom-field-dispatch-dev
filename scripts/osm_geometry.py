"""Interior footprint points and spatial sampling for synthetic datasets."""
import math
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
