import json
from datetime import date
from functools import lru_cache

import psycopg
from psycopg.rows import dict_row
from .settings import ROOT

class StoreUnavailable(Exception):
    pass

class PlanConflict(Exception):
    pass

class PostgresRepository:
    source='postgres'

    def __init__(self,settings):self.settings=settings

    def fetch(self,sql,params=()):
        s=self.settings
        try:
            with psycopg.connect(host=s.host,port=s.port,dbname=s.database,user=s.user,
                    password=s.password,connect_timeout=3,row_factory=dict_row,
                    options='-c timezone=Asia/Yekaterinburg -c statement_timeout=5000 -c default_transaction_read_only=on') as conn:
                return conn.execute(sql,params).fetchall()
        except psycopg.Error as exc:
            # Never include connection strings, passwords or server detail in HTTP errors.
            raise StoreUnavailable('Не удалось прочитать PostgreSQL. Проверьте подключение и наличие схемы dispatch.') from exc

    def health(self):
        rows=self.fetch("SELECT to_regclass('dispatch.orders') IS NOT NULL AND to_regclass('dispatch.dataset_state') IS NOT NULL AS ready")
        if not rows[0]['ready']:raise StoreUnavailable('Схема dispatch ещё не создана. Примените миграцию.')

    def load(self,kind,payload,day=None):
        from .postgres_loading import load_reference,load_matrix,load_day
        try:
            if kind=='reference':return load_reference(self.settings,payload)
            if kind=='matrix':return load_matrix(self.settings,payload)
            return load_day(self.settings,day,payload)
        except psycopg.IntegrityError as exc:
            from planner.events import EventError
            raise EventError('INVALID_DATA','Данные нарушают ограничения хранения; загрузка полностью отменена.',422) from exc
        except psycopg.Error as exc:raise StoreUnavailable('Ошибка транзакции загрузки. Состояние не изменено.') from exc

    def days(self):
        return self.fetch('''SELECT d.date,d.model_now,count(o.order_id)::int AS orders_count
            FROM dispatch.planning_days d LEFT JOIN dispatch.orders o ON o.date=d.date
            GROUP BY d.date,d.model_now ORDER BY d.date''')

    def reference(self):
        return dict(service_centers=self.fetch('SELECT * FROM dispatch.service_centers ORDER BY service_center_id'),
            staff=self.fetch('''SELECT staff_id,display_name,service_center_id,profiles::text[] AS profiles,
                technologies::text[] AS technologies,height_permit,shift_start::text AS shift_start,
                shift_end::text AS shift_end FROM dispatch.staff ORDER BY staff_id'''),
            work_types=self.fetch('SELECT code,name,duration_min,profiles::text[] AS profiles FROM dispatch.work_types ORDER BY code'))

    def day(self,day:date):
        rows=self.fetch('SELECT date,model_now FROM dispatch.planning_days WHERE date=%s',(day,))
        if not rows:return None
        result=rows[0]
        result['orders']=self.fetch('''SELECT order_id,work_type_code,technology::text AS technology,
            building_id,address,lat,lon,building_type,requires_height,access_node_id,
            registered_at,slot_start,slot_end,latest_start,deadline,required_equipment,is_repeat
            FROM dispatch.orders WHERE date=%s ORDER BY slot_start,order_id''',(day,))
        plans=self.fetch('SELECT payload FROM dispatch.current_plans WHERE date=%s',(day,))
        result['plan']=plans[0]['payload'] if plans else None
        return result

    def calculate(self,day,limit):
        from planner.solver import build_plan
        from psycopg.types.json import Jsonb
        s=self.settings
        try:
            with psycopg.connect(host=s.host,port=s.port,dbname=s.database,user=s.user,password=s.password,connect_timeout=3,row_factory=dict_row,
                    options='-c timezone=Asia/Yekaterinburg -c statement_timeout=330000 -c lock_timeout=1000') as conn:
                from .postgres_loading import DATASET_LOCK
                if not conn.execute('SELECT pg_try_advisory_xact_lock_shared(%s) AS ok',(DATASET_LOCK,)).fetchone()['ok']:raise PlanConflict('Выполняется загрузка данных.')
                row=conn.execute('SELECT * FROM dispatch.planning_days WHERE date=%s FOR UPDATE NOWAIT',(day,)).fetchone()
                if not row:return None
                if conn.execute('SELECT 1 FROM dispatch.events WHERE date=%s LIMIT 1',(day,)).fetchone():
                    raise PlanConflict('После первого события первоначальный план перестраивать нельзя.')
                matrix=conn.execute('SELECT payload FROM dispatch.travel_matrices WHERE matrix_id=%s',(row['matrix_id'],)).fetchone()
                plan=build_plan(row['reference_snapshot'],row['input_snapshot'],matrix['payload'],limit)
                conn.execute('''INSERT INTO dispatch.plans(date,plan_version,as_of,based_on_event_id,computation_ms,payload)
                    VALUES(%s,1,%s,NULL,%s,%s) ON CONFLICT(date,plan_version) DO UPDATE SET
                    as_of=EXCLUDED.as_of,computation_ms=EXCLUDED.computation_ms,payload=EXCLUDED.payload''',
                    (day,plan['as_of'],plan['computation_ms'],Jsonb(plan)))
                return plan
        except psycopg.errors.LockNotAvailable as exc:raise PlanConflict('Расчёт этого дня уже выполняется.') from exc
        except psycopg.Error as exc:raise StoreUnavailable('Не удалось рассчитать или сохранить план в PostgreSQL.') from exc

    def event(self,day,event):
        from .event_store import postgres_event
        try:return postgres_event(self.settings,day,event)
        except psycopg.errors.LockNotAvailable as exc:raise PlanConflict('Другой расчёт этого дня уже выполняется.') from exc
        except psycopg.Error as exc:raise StoreUnavailable('Ошибка транзакции события. Изменения не сохранены.') from exc

class DemoRepository:
    """Explicit file mode for UI development; never an automatic DB fallback."""
    source='demo'

    def __init__(self,empty=False):
        self.plans={}
        self.states={};self.journal={}
        self.dynamic=empty;self.loaded_reference=None;self.loaded_matrix=None;self.loaded_days={};self.day_matrices={}
        from threading import Lock
        self.plan_lock=Lock()

    @staticmethod
    @lru_cache
    def read(name):
        try:return json.loads((ROOT/'data'/name).read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc:raise StoreUnavailable('Не удалось прочитать демонстрационные файлы.') from exc

    def health(self):self.read('orders_train.json')

    def full_reference(self):
        return self.loaded_reference if self.loaded_reference is not None else dict(service_centers=self.read('service_centers.json'),staff=self.read('staff.json'),access_nodes=self.read('access_nodes.json'),work_types=self._works())

    def active_matrix(self):
        return self.loaded_matrix if self.dynamic else self.read('travel_matrix.json')

    def load(self,kind,payload,day=None):
        from copy import deepcopy
        from .loading import reference_data,travel_matrix,day_input,reference_counts
        from planner.events import EventError
        if not self.plan_lock.acquire(blocking=False):raise EventError('DATASET_BUSY','Расчёт или загрузка уже выполняется.',422)
        try:
            if kind=='reference':
                ref,buildings=reference_data(payload);matrix=self.loaded_matrix if self.dynamic else None
                if matrix and not ({c['service_center_id'] for c in ref['service_centers']}|set(buildings))<=set(matrix['points']):matrix=None
                self.loaded_reference=ref;self.loaded_matrix=matrix;self.dynamic=True
                self.plans={};self.states={};self.journal={};self.loaded_days={};self.day_matrices={}
                return reference_counts(ref,buildings)
            if kind=='matrix':
                matrix=travel_matrix(payload,self.loaded_reference)
                self.loaded_matrix=matrix
                # First PUT may precede reference. File demo data stop being implicit API inputs.
                if not self.dynamic:
                    self.loaded_reference=None;self.dynamic=True;self.loaded_days={}
                    self.plans={};self.states={};self.journal={};self.day_matrices={}
                return dict(status='loaded',counts={'points':len(matrix['points'])})
            ref=self.loaded_reference if self.dynamic else self.full_reference();matrix=self.active_matrix()
            data=day_input(day,payload,ref,matrix);key=str(day)
            if not self.dynamic:self.loaded_reference=ref;self.loaded_matrix=matrix;self.dynamic=True
            self.loaded_days[key]=data;self.states[key]=deepcopy(data);self.day_matrices[key]=deepcopy(matrix)
            self.plans.pop(key,None);self.journal={k:v for k,v in self.journal.items() if k[0]!=key}
            return dict(status='loaded',counts={'orders':len(data['orders'])})
        finally:self.plan_lock.release()

    def days(self):
        if self.dynamic:
            return [dict(date=key,model_now=self.states.get(key,day)['now'],orders_count=len(self.states.get(key,day)['orders'])) for key,day in sorted(self.loaded_days.items())]
        counts={}
        for o in self.read('orders_train.json'):
            day=o['slot']['start'][:10];counts[day]=counts.get(day,0)+1
        return [dict(date=d,model_now=d+'T08:30:00+05:00',orders_count=n) for d,n in sorted(counts.items())]

    def reference(self):
        if self.dynamic:
            ref=self.loaded_reference or dict(service_centers=[],staff=[],work_types=[])
            return dict(service_centers=ref['service_centers'],staff=[dict(staff_id=p['staff_id'],display_name=p.get('display_name'),service_center_id=p['service_center_id'],profiles=p['profiles'],technologies=p['technologies'],height_permit=p['height_permit'],shift_start=p['shift']['start'],shift_end=p['shift']['end']) for p in ref['staff']],work_types=ref['work_types'])
        return dict(service_centers=self.read('service_centers.json'),
            staff=[dict(staff_id=p['staff_id'],display_name=p.get('display_name'),
                service_center_id=p['service_center_id'],profiles=p['profiles'],technologies=p['technologies'],
                height_permit=p['height_permit'],shift_start=p['shift']['start'],shift_end=p['shift']['end'])
                for p in self.read('staff.json')],
            work_types=[dict(code=row['code'],name=row['name'],duration_min=int(row['duration_min']),profiles=row['profiles'])
                for row in self._works()])

    @staticmethod
    def _works():
        import csv
        with (ROOT/'data'/'work_types.csv').open(encoding='utf-8',newline='') as stream:
            rows=list(csv.DictReader(stream))
        for row in rows:
            row['profiles']=row['profiles'].split('|')
            for key in ['duration_min','max_start_delay_min','deadline_value','repeat_deadline_value']:
                row[key]=int(row[key]) if row[key] else None
            row['pgp_relevant']=row['pgp_relevant']=='true'
        return rows

    def day(self,day:date):
        if str(day) not in {d['date'] for d in self.days()}:return None
        orders=[]
        for row in self.states.get(str(day),{}).get('orders',self.loaded_days.get(str(day),{}).get('orders',self.read('orders_train.json'))):
            if row['slot']['start'][:10]!=str(day):continue
            orders.append({k:v for k,v in row.items() if k not in ('fact','slot','previous_order_id')}|
                dict(slot_start=row['slot']['start'],slot_end=row['slot']['end']))
        return dict(date=day,model_now=self.states.get(str(day),{}).get('now',str(day)+'T08:30:00+05:00'),orders=sorted(orders,key=lambda o:(o['slot_start'],o['order_id'])),plan=self.plans.get(str(day)))

    def calculate(self,day,limit):
        from planner.solver import build_plan
        if self.day(day) is None:return None
        if not self.plan_lock.acquire(blocking=False):raise PlanConflict('Расчёт уже выполняется.')
        try:
            if any(d==str(day) for d,eid in self.journal):raise PlanConflict('После события начальный план не пересчитывается.')
            reference=self.full_reference()
            initial=self.loaded_days.get(str(day)) or dict(date=str(day),now=str(day)+'T08:30:00+05:00',orders=[{k:v for k,v in o.items() if k!='fact'} for o in self.read('orders_train.json') if o['slot']['start'][:10]==str(day)])
            plan=build_plan(reference,initial,self.day_matrices.get(str(day),self.active_matrix()),limit)
            self.plans[str(day)]=plan;return plan
        finally:self.plan_lock.release()

    def event(self,day,event):
        from copy import deepcopy
        import time
        from planner.events import apply_event,EventError
        from .event_store import duplicate_result,result_for
        from .contracts import validate
        if not self.plan_lock.acquire(blocking=False):raise PlanConflict('Расчёт уже выполняется.')
        try:
            key=(str(day),event['event_id'])
            if key in self.journal:return duplicate_result(self.journal[key],event)
            if self.day(day) is None:raise EventError('DAY_NOT_LOADED','День не загружен.',404)
            if str(day) not in self.plans:raise EventError('PLAN_NOT_BUILT','Сначала рассчитайте план.',409)
            initial=dict(date=str(day),now=str(day)+'T08:30:00+05:00',orders=[{k:v for k,v in o.items() if k!='fact'} for o in self.read('orders_train.json') if o['slot']['start'][:10]==str(day)])
            ref=self.full_reference()
            began=time.monotonic();previous=self.plans[str(day)]
            state,plan=apply_event(ref,self.states.get(str(day),self.loaded_days.get(str(day),initial)),self.day_matrices.get(str(day),self.active_matrix()),previous,event)
            validate('Plan',plan);result=result_for(event,previous,plan,began)
            self.states[str(day)]=state;self.plans[str(day)]=plan;self.journal[key]=deepcopy(dict(payload=event,result=result))
            return result
        finally:self.plan_lock.release()
