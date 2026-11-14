"""DEMO/legacy backend only. Production REST API belongs to the Fastify service."""
from datetime import date
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from .repository import DemoRepository, PostgresRepository, StoreUnavailable, PlanConflict
from pydantic import BaseModel, Field
from planner.events import EventError

class PlanRequest(BaseModel):
    time_limit_sec: int = Field(default=300,ge=1,le=300,strict=True)
from .settings import ROOT, Settings

def create_app(settings=None,repository=None):
    settings=settings or Settings.from_env()
    repo=repository or (DemoRepository() if settings.source=='demo' else PostgresRepository(settings))
    app=FastAPI(title='Магистраль · Демонстрационный прототип',version='0.1.0',docs_url='/docs',redoc_url=None)
    app.state.repository=repo

    @app.middleware('http')
    async def refresh_local_assets(request,call_next):
        response=await call_next(request)
        if request.url.path=='/' or request.url.path.startswith('/static/'):
            response.headers['Cache-Control']='no-cache, must-revalidate'
        return response

    def error(code,message,status):return JSONResponse({'error':{'code':code,'message':message}},status_code=status)

    @app.exception_handler(StoreUnavailable)
    async def unavailable(request,exc):return error('DATABASE_UNAVAILABLE',str(exc),503)

    @app.exception_handler(PlanConflict)
    async def plan_conflict(request,exc):return error('PLAN_CONFLICT',str(exc),409)

    @app.exception_handler(EventError)
    async def event_error(request,exc):return error(exc.code,exc.message,exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation(request,exc):
        body_error=any(e['loc'] and e['loc'][0]=='body' for e in exc.errors())
        status=400 if request.method=='PUT' or body_error else 422
        return error('BAD_REQUEST','Некорректный формат параметров запроса.',status)

    @app.exception_handler(HTTPException)
    async def http_error(request,exc):return error('NOT_FOUND' if exc.status_code==404 else 'HTTP_ERROR',str(exc.detail),exc.status_code)

    @app.get('/api/v1/health')
    def health():
        repo.health()
        return {'status':'ok','version':'0.1.0','data_source':repo.source}

    @app.put('/api/v1/reference')
    def put_reference(body:dict):return repo.load('reference',body)

    @app.put('/api/v1/reference/travel-matrix')
    def put_matrix(body:dict):return repo.load('matrix',body)

    @app.put('/api/v1/days/{day}')
    def put_day(day:date,body:dict):return repo.load('day',body,day)

    # /ui endpoints are extensions permitted by the organizer specification.
    @app.get('/api/ui/bootstrap')
    def bootstrap():
        repo.health()
        return dict(data_source=repo.source,days=repo.days(),**repo.reference())

    @app.get('/api/ui/days/{day}')
    def day_map(day:date):
        result=repo.day(day)
        if result is None:raise HTTPException(404,'День не загружен.')
        return dict(data_source=repo.source,**result)

    @app.get('/api/v1/days/{day}/plan')
    def get_plan(day:date):
        result=repo.day(day)
        if result is None:return error('DAY_NOT_LOADED','День не загружен.',404)
        if result['plan'] is None:return error('PLAN_NOT_BUILT','План на этот день ещё не построен.',404)
        return result['plan']

    @app.get('/case-api.yaml',include_in_schema=False)
    def case_api():return FileResponse(ROOT/'api_spec.yaml',media_type='application/yaml')

    @app.post('/api/v1/days/{day}/plan')
    def calculate(day:date,body:PlanRequest|None=None):
        plan=repo.calculate(day,(body or PlanRequest()).time_limit_sec)
        if plan is None:return error('DAY_NOT_LOADED','День не загружен.',404)
        return plan

    @app.post('/api/v1/days/{day}/events')
    def post_event(day:date,body:dict):
        from .contracts import validate
        try:validate('Event',body)
        except EventError as exc:raise EventError(exc.code,exc.message,400) from exc
        return repo.event(day,body)

    @app.get('/api/ui/days/{day}/routes/{staff_id}/geometry')
    def geometry(day:date,staff_id:str):
        result=repo.day(day)
        if result is None or not result['plan']:return error('PLAN_NOT_BUILT','План ещё не построен.',404)
        route=next((r for r in result['plan']['routes'] if r['staff_id']==staff_id),None)
        if route is None:return error('UNKNOWN_STAFF','Маршрут сотрудника не найден.',404)
        points={o['building_id']:(o['lon'],o['lat']) for o in result['orders']}
        points.update({c['service_center_id']:(c['lon'],c['lat']) for c in repo.reference()['service_centers']})
        coordinates=[];labels=[];visit_number=0
        for stop in route['stops']:
            if stop['type']=='VISIT':visit_number+=1
            label=str(visit_number) if stop['type']=='VISIT' else 'СЦ'
            point=points[stop['location_id']]
            if not coordinates or coordinates[-1]!=point:
                coordinates.append(point);labels.append(label)
            elif stop['type']!='BREAK':labels[-1]=label
        from .geometry import road_route
        try:
            roads=road_route(tuple(coordinates))
            return dict(staff_id=staff_id,plan_version=result['plan']['plan_version'],geometry=roads['geometry'],
                segments=[dict(from_stop=labels[i],to_stop=labels[i+1],geometry=leg) for i,leg in enumerate(roads['legs'])])
        except (OSError,ValueError):return error('ROUTING_UNAVAILABLE','OSRM недоступен: назначения сохранены, дорожную линию сейчас получить не удалось.',502)

    app.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')

    @app.get('/',include_in_schema=False)
    def index():return FileResponse(ROOT/'web'/'index.html')

    return app

app=create_app()
