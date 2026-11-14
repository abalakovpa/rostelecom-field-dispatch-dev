from copy import deepcopy
from datetime import date
import pytest
from fastapi.testclient import TestClient
from api.main import create_app
from api.repository import DemoRepository
from api.settings import Settings
from planner.solver import build_plan
from planner.validate import validate_plan

@pytest.fixture
def input_case():
    repo=DemoRepository();person=deepcopy(repo.read('staff.json')[0]);person['equipment_start']={'ONT':0,'ROUTER':0,'STB':0}
    order=deepcopy(repo.read('orders_train.json')[0]);order.pop('fact',None)
    return (dict(staff=[person],service_centers=repo.read('service_centers.json'),work_types=repo._works()),
        dict(date='2026-10-12',now='2026-10-12T08:30:00+05:00',orders=[order]),repo.read('travel_matrix.json'))

def test_plan_has_reload_lunch_return_and_equipment_trace(input_case):
    reference,day,matrix=input_case;plan=build_plan(reference,day,matrix,1)
    assert plan['summary']['visits_planned']==1
    kinds=[s['type'] for s in plan['routes'][0]['stops']]
    assert kinds[0]=='DEPOT_START' and kinds[-1]=='DEPOT_END'
    assert 'RESTOCK' in kinds and kinds.count('BREAK')==1
    broken=deepcopy(plan);visit=next(s for s in broken['routes'][0]['stops'] if s['type']=='VISIT');visit['start']='2026-10-12T07:00:00+05:00'
    with pytest.raises(ValueError):validate_plan(reference,day,matrix,broken)

def test_missing_qualification_and_absent_staff(input_case):
    reference,day,matrix=input_case;reference['staff'][0]['technologies']=[]
    plan=build_plan(reference,day,matrix,1)
    assert plan['unassigned'][0]['reason_code']=='NO_QUALIFIED_STAFF'
    day['absent_staff_ids']=[reference['staff'][0]['staff_id']]
    plan=build_plan(reference,day,matrix,1)
    assert plan['routes']==[] and len(plan['unassigned'])==1

def test_full_day_plan_endpoint_and_persistence():
    repo=DemoRepository()
    with TestClient(create_app(Settings(source='demo'),repo)) as client:
        assert client.post('/api/v1/days/2026-10-12/plan',json={'time_limit_sec':0}).status_code==400
        response=client.post('/api/v1/days/2026-10-12/plan',json={'time_limit_sec':2})
        assert response.status_code==200
        plan=response.json();assert plan['summary']['visits_planned']>0
        assert plan['summary']['visits_planned']+len(plan['unassigned'])+sum(len(g['order_ids']) for g in plan['pgp_groups'])==350
        assert len(plan['routes'])==40 and plan['summary']['pgp_orders']==3
        assert client.get('/api/v1/days/2026-10-12/plan').json()==plan
