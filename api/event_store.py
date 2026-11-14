"""Atomic event + state + immutable version persistence."""
import time
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from planner.events import apply_event,EventError

def duplicate_result(stored,event):
    if stored['payload']!=event:raise EventError('EVENT_ID_CONFLICT','Этот event_id уже принят с другим содержимым.',409)
    return dict(stored['result'],duplicate=True)

def result_for(event,previous,plan,began):
    old={r['staff_id']:r for r in previous['routes']}
    return dict(event_id=event['event_id'],accepted=True,duplicate=False,plan_version=plan['plan_version'],as_of=plan['as_of'],
        processing_ms=round((time.monotonic()-began)*1000),changed_staff_ids=[r['staff_id'] for r in plan['routes'] if r!=old.get(r['staff_id'])],
        new_alerts=[a for a in plan['alerts'] if a['alert_id'] not in {x['alert_id'] for x in previous['alerts']}])

def postgres_event(settings,day,event):
    from .contracts import validate
    began=time.monotonic();s=settings
    with psycopg.connect(host=s.host,port=s.port,dbname=s.database,user=s.user,password=s.password,connect_timeout=2,row_factory=dict_row,
            options='-c timezone=Asia/Yekaterinburg -c statement_timeout=9000 -c lock_timeout=500') as conn:
        from .postgres_loading import DATASET_LOCK
        if not conn.execute('SELECT pg_try_advisory_xact_lock_shared(%s) AS ok',(DATASET_LOCK,)).fetchone()['ok']:raise EventError('DATASET_BUSY','Выполняется загрузка данных.',409)
        row=conn.execute('SELECT * FROM dispatch.planning_days WHERE date=%s FOR UPDATE NOWAIT',(day,)).fetchone()
        if not row:raise EventError('DAY_NOT_LOADED','День не загружен.',404)
        prior=conn.execute('SELECT payload,result FROM dispatch.events WHERE date=%s AND event_id=%s',(day,event['event_id'])).fetchone()
        if prior:return duplicate_result(prior,event)
        previous=conn.execute('SELECT payload FROM dispatch.current_plans WHERE date=%s',(day,)).fetchone()
        if not previous:raise EventError('PLAN_NOT_BUILT','Сначала рассчитайте первоначальный план.',409)
        matrix=conn.execute('SELECT payload FROM dispatch.travel_matrices WHERE matrix_id=%s',(row['matrix_id'],)).fetchone()['payload']
        state,plan=apply_event(row['reference_snapshot'],row['input_snapshot'],matrix,previous['payload'],event)
        validate('Plan',plan)
        result=result_for(event,previous['payload'],plan,began)
        if event['type']=='NEW_ORDER':
            o=next(o for o in state['orders'] if o['order_id']==event['order']['order_id'])
            fields=['order_id','work_type_code','technology','building_id','address','lat','lon','building_type','requires_height','access_node_id','registered_at','latest_start','deadline','required_equipment','is_repeat','previous_order_id']
            values=[Jsonb(o[k]) if k=='required_equipment' else o.get(k) for k in fields]
            conn.execute('INSERT INTO dispatch.orders(date,'+','.join(fields)+',slot_start,slot_end) VALUES('+','.join(['%s']*(len(fields)+3))+')',
                [day,*values,o['slot']['start'],o['slot']['end']])
        conn.execute('INSERT INTO dispatch.events(date,event_id,type,timestamp,payload,result) VALUES(%s,%s,%s,%s,%s,%s)',
            (day,event['event_id'],event['type'],event['timestamp'],Jsonb(event),Jsonb(result)))
        conn.execute('INSERT INTO dispatch.plans(date,plan_version,as_of,based_on_event_id,computation_ms,payload) VALUES(%s,%s,%s,%s,%s,%s)',
            (day,plan['plan_version'],plan['as_of'],event['event_id'],plan['computation_ms'],Jsonb(plan)))
        conn.execute('UPDATE dispatch.planning_days SET model_now=%s,input_snapshot=%s WHERE date=%s',(event['timestamp'],Jsonb(state),day))
        return result
