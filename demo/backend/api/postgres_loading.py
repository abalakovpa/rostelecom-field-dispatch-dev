"""Dataset loads are atomic and exclude concurrent planning/event writes."""
from contextlib import contextmanager
from copy import deepcopy
import uuid
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .loading import reference_data,travel_matrix,day_input,reference_counts,coverage
from planner.events import EventError

DATASET_LOCK=682043119

@contextmanager
def transaction(settings,timeout=55000):
    s=settings
    with psycopg.connect(host=s.host,port=s.port,dbname=s.database,user=s.user,password=s.password,connect_timeout=3,row_factory=dict_row,
            options=f'-c timezone=Asia/Yekaterinburg -c statement_timeout={timeout}') as conn:
        if not conn.execute('SELECT pg_try_advisory_xact_lock(%s) AS ok',(DATASET_LOCK,)).fetchone()['ok']:
            raise EventError('DATASET_BUSY','Расчёт или другая загрузка уже выполняется. Повторите запрос.',422)
        yield conn

def insert(conn,table,row):
    # Table and column names are constructed only from fixed internal mappings.
    from psycopg import sql
    query=sql.SQL('INSERT INTO dispatch.{} ({}) VALUES ({})').format(sql.Identifier(table),
        sql.SQL(',').join(map(sql.Identifier,row)),sql.SQL(',').join(sql.Placeholder() for _ in row))
    conn.execute(query,[Jsonb(v) if isinstance(v,dict) else v for v in row.values()])

def insert_orders(conn,day,orders):
    for order in orders:
        fields=['order_id','work_type_code','technology','building_id','address','lat','lon','building_type','requires_height','access_node_id','registered_at','latest_start','deadline','required_equipment','is_repeat','previous_order_id']
        insert(conn,'orders',dict(date=day,**{k:order.get(k) for k in fields},slot_start=order['slot']['start'],slot_end=order['slot']['end']))

def delete_day(conn,day):
    for table in ['plans','events','absent_staff','orders','planning_days']:
        conn.execute('DELETE FROM dispatch.'+table+' WHERE date=%s',(day,))

def load_reference(settings,payload):
    ref,buildings=reference_data(payload)
    with transaction(settings) as conn:
        state=conn.execute('SELECT * FROM dispatch.dataset_state WHERE singleton').fetchone()
        matrix=conn.execute('SELECT payload FROM dispatch.travel_matrices WHERE matrix_id=%s',(state['matrix_id'],)).fetchone() if state['matrix_id'] else None
        compatible=bool(matrix and ({c['service_center_id'] for c in ref['service_centers']}|set(buildings))<=set(matrix['payload']['points']))
        for table in ['plans','events','absent_staff','orders','planning_days','training_orders','access_node_buildings','staff','buildings','access_nodes','work_types','service_centers']:
            conn.execute('DELETE FROM dispatch.'+table)
        for center in ref['service_centers']:
            insert(conn,'service_centers',{k:v for k,v in center.items() if k!='opening_hours'}|dict(opening_open=center['opening_hours']['open'],opening_close=center['opening_hours']['close']))
        for person in ref['staff']:
            shift=person['shift']
            insert(conn,'staff',{k:v for k,v in person.items() if k!='shift'}|dict(shift_start=shift['start'],shift_end=shift['end'],break_duration_min=shift['break_duration_min'],break_window_from=shift['break_window']['from'],break_window_to=shift['break_window']['to']))
        for building in buildings.values():insert(conn,'buildings',building)
        for node in ref['access_nodes']:
            insert(conn,'access_nodes',{k:v for k,v in node.items() if k!='buildings'})
            for building in node['buildings']:insert(conn,'access_node_buildings',dict(access_node_id=node['access_node_id'],building_id=building['building_id']))
        for work in ref['work_types']:insert(conn,'work_types',work)
        conn.execute('UPDATE dispatch.dataset_state SET reference=%s,matrix_id=%s WHERE singleton',(Jsonb(ref),state['matrix_id'] if compatible else None))
    return reference_counts(ref,buildings)

def load_matrix(settings,payload):
    with transaction(settings) as conn:
        state=conn.execute('SELECT * FROM dispatch.dataset_state WHERE singleton').fetchone()
        matrix=travel_matrix(payload,state['reference']);key=matrix['matrix_id']
        prior=conn.execute('SELECT payload FROM dispatch.travel_matrices WHERE matrix_id=%s',(key,)).fetchone()
        if prior and prior['payload']!=matrix and conn.execute('SELECT 1 FROM dispatch.planning_days WHERE matrix_id=%s LIMIT 1',(key,)).fetchone():
            archive=key+'@snapshot-'+uuid.uuid4().hex;archived=deepcopy(prior['payload']);archived['matrix_id']=archive
            insert(conn,'travel_matrices',dict(matrix_id=archive,payload=archived))
            conn.execute('UPDATE dispatch.planning_days SET matrix_id=%s WHERE matrix_id=%s',(archive,key))
        conn.execute('INSERT INTO dispatch.travel_matrices(matrix_id,payload) VALUES(%s,%s) ON CONFLICT(matrix_id) DO UPDATE SET payload=EXCLUDED.payload',(key,Jsonb(matrix)))
        conn.execute('UPDATE dispatch.dataset_state SET matrix_id=%s WHERE singleton',(key,))
    return dict(status='loaded',counts={'points':len(matrix['points'])})

def load_day(settings,date,payload):
    with transaction(settings,25000) as conn:
        state=conn.execute('SELECT * FROM dispatch.dataset_state WHERE singleton').fetchone()
        row=conn.execute('SELECT payload FROM dispatch.travel_matrices WHERE matrix_id=%s',(state['matrix_id'],)).fetchone() if state['matrix_id'] else None
        data=day_input(date,payload,state['reference'],row['payload'] if row else None)
        delete_day(conn,date)
        insert(conn,'planning_days',dict(date=date,model_now=data['now'],matrix_id=state['matrix_id'],reference_snapshot=state['reference'],input_snapshot=data))
        for sid in data['absent_staff_ids']:insert(conn,'absent_staff',dict(date=date,staff_id=sid))
        insert_orders(conn,date,data['orders'])
    return dict(status='loaded',counts={'orders':len(data['orders'])})
