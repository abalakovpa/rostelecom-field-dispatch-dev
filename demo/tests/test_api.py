from datetime import date
from fastapi.testclient import TestClient
from api.main import create_app
from api.repository import DemoRepository,PostgresRepository,StoreUnavailable
from api.settings import Settings

def client():return TestClient(create_app(Settings(source='demo')))

def test_map_reads_full_day_without_training_labels():
    with client() as c:
        bootstrap=c.get('/api/ui/bootstrap').json()
        assert bootstrap['data_source']=='demo'
        assert len(bootstrap['days'])==10
        assert len(bootstrap['staff'])==40
        assert len(bootstrap['service_centers'])==5
        day=c.get('/api/ui/days/'+bootstrap['days'][0]['date']).json()
        assert len(day['orders'])==350
        assert day['plan'] is None
        assert all('fact' not in order for order in day['orders'])
        assert day['orders'][0]['slot_start'].endswith('+05:00')

def test_missing_plan_is_not_fabricated():
    with client() as c:
        r=c.get('/api/v1/days/2026-10-12/plan')
        assert r.status_code==404
        assert r.json()['error']['code']=='PLAN_NOT_BUILT'
        assert c.get('/api/ui/days/2026-01-01').status_code==404
        assert c.get('/api/ui/days/not-a-date').status_code==422

def test_unavailable_store_is_reported_without_file_fallback():
    class BrokenStore:
        source='postgres'
        def health(self):raise StoreUnavailable('База недоступна')
    with TestClient(create_app(Settings(),repository=BrokenStore())) as c:
        for endpoint in ['/api/ui/bootstrap','/api/v1/health']:
            response=c.get(endpoint)
            assert response.status_code==503
            assert response.json()=={'error':{'code':'DATABASE_UNAVAILABLE','message':'База недоступна'}}

def test_driver_failure_hides_credentials(monkeypatch):
    import psycopg
    def fail(**kwargs):raise psycopg.OperationalError('password=super-secret')
    monkeypatch.setattr('api.repository.psycopg.connect',fail)
    with TestClient(create_app(Settings(password='super-secret'))) as c:
        response=c.get('/api/v1/health')
        assert response.status_code==503
        assert 'super-secret' not in response.text

def test_frontend_and_local_leaflet_are_served():
    with client() as c:
        assert c.get('/').status_code==200
        assert c.get('/static/vendor/leaflet.js').status_code==200
        assert 'openapi: 3.0.3' in c.get('/case-api.yaml').text
        assert c.get('/api/v1/health').json()['status']=='ok'
