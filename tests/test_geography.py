import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from fetch_real_buildings import interior, inside, distance_m

def test_interior_point_for_concave_building():
    # Bounding-box center is outside this L-shaped footprint.
    ring=[(0,0),(4,0),(4,1),(1,1),(1,4),(0,4),(0,0)]
    assert not inside(2,2,ring)
    x,y=interior(ring)
    assert inside(x,y,ring)

def test_selected_buildings_are_inside_district():
    import json
    root=Path(__file__).resolve().parents[1]
    locations=json.loads((root/'data/provenance/real_locations.json').read_text(encoding='utf-8'))
    points=list(locations['buildings'].values())+list(locations['service_centers'].values())
    assert len(points)==85
    for p in points:
        assert inside(p['lon'],p['lat'],p['ring'])
        assert any(inside(p['lon'],p['lat'],r) for r in locations['district_rings'])
        assert p['tags']['addr:street'] and p['tags']['addr:housenumber']

def test_spatial_sample_is_not_a_depot_neighborhood():
    import json
    root=Path(__file__).resolve().parents[1]
    locations=json.loads((root/'data/provenance/real_locations.json').read_text(encoding='utf-8'))
    homes=list(locations['buildings'].values());depots=list(locations['service_centers'].values())
    assert len({p['tags']['addr:street'] for p in homes})>=30
    assert sum(min(distance_m(p,c) for c in depots)<500 for p in homes)<40
    for i,p in enumerate(homes):
        assert all(distance_m(p,q)>=100 for q in homes[i+1:] if p['building_type']==q['building_type'])
