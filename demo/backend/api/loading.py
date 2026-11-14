"""Canonical validation shared by memory and PostgreSQL loading paths."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import math
from .contracts import validate,validator
from planner.events import EventError

ZONE=timezone(timedelta(hours=5))

def require(ok,message,code='INVALID_DATA',status=422):
    if not ok:raise EventError(code,message,status)

def canonical(name,payload):
    schemas=validator(name).schema['components']['schemas']
    def shape(schema,value):
        if '$ref' in schema:return shape(schemas[schema['$ref'].rsplit('/',1)[-1]],value)
        if value is None:return None
        if 'anyOf' in schema:
            branch=next((b for b in schema['anyOf'] if b.get('type')!='null'),{})
            return shape(branch,value)
        if 'allOf' in schema:
            result={}
            for branch in schema['allOf']:
                part=shape(branch,value)
                if isinstance(part,dict):result.update(part)
            return result if result else deepcopy(value)
        if isinstance(value,list):return [shape(schema.get('items',{}),v) for v in value]
        if isinstance(value,dict):
            properties=schema.get('properties')
            return {k:shape(properties[k],v) for k,v in value.items() if k in properties} if properties else deepcopy(value)
        if isinstance(value,float):require(math.isfinite(value),'Число должно быть конечным.')
        return value
    # The general API convention requires unknown input fields to be ignored.
    result=shape(schemas[name],payload)
    try:validate(name,result)
    except EventError as exc:raise EventError(exc.code,exc.message,400) from exc
    def local_times(schema,value):
        if '$ref' in schema:return local_times(schemas[schema['$ref'].rsplit('/',1)[-1]],value)
        if value is None:return None
        if 'anyOf' in schema:return local_times(next((b for b in schema['anyOf'] if b.get('type')!='null'),{}),value)
        if 'allOf' in schema:
            for branch in schema['allOf']:value=local_times(branch,value)
            return value
        if schema.get('format')=='date-time':return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(ZONE).isoformat()
        if isinstance(value,dict):return {k:local_times(schema.get('properties',{}).get(k,{}),v) for k,v in value.items()}
        if isinstance(value,list):return [local_times(schema.get('items',{}),v) for v in value]
        return value
    return local_times(schemas[name],result)

def unique(rows,key):
    require(len({r[key] for r in rows})==len(rows),'Повторяющиеся идентификаторы: '+key)

def coordinates(item):
    require(-90<=item['lat']<=90 and -180<=item['lon']<=180,'Координаты вне допустимого диапазона.')

def reference_data(payload):
    ref=canonical('ReferenceData',payload)
    for name,key in [('service_centers','service_center_id'),('staff','staff_id'),('access_nodes','access_node_id'),('work_types','code')]:unique(ref[name],key)
    centers={c['service_center_id'] for c in ref['service_centers']};buildings={}
    for center in ref['service_centers']:
        coordinates(center);require(center['opening_hours']['open']<center['opening_hours']['close'],'Некорректные часы работы СЦ.')
    for person in ref['staff']:
        require(person['service_center_id'] in centers,'Неизвестный СЦ сотрудника.')
        shift=person['shift'];require(shift['start']<shift['end'],'Некорректная дневная смена.')
        require(shift['start']<=shift['break_window']['from']<=shift['break_window']['to']<=shift['end'],'Окно начала обеда вне смены.')
        require(all(person['equipment_start'][k]<=person['equipment_capacity'][k] for k in ['ONT','ROUTER','STB']),'Стартовый запас больше ёмкости.')
    for node in ref['access_nodes']:
        coordinates(node)
        require(dict(OLT='PON',SWITCH='FTTB',DSLAM='XDSL',CMTS='DOCSIS')[node['node_type']]==node['technology'],'Тип узла не соответствует технологии.')
        unique(node['buildings'],'building_id')
        for b in node['buildings']:
            coordinates(b);require(not b.get('zone_service_center_id') or b['zone_service_center_id'] in centers,'Неизвестная зона СЦ.')
            require(b['building_id'] not in buildings or buildings[b['building_id']]==b,'Различающиеся атрибуты одного дома в разных узлах.')
            buildings[b['building_id']]=b
    return ref,buildings

def coverage(ref,buildings,matrix):
    required={c['service_center_id'] for c in ref['service_centers']}|set(buildings)
    require(required<=set(matrix['points']),'Матрица не покрывает все СЦ и дома.')

def travel_matrix(payload,ref=None):
    matrix=canonical('TravelMatrix',payload);n=len(matrix['points'])
    for key in ['durations_sec','distances_m']:
        require(len(matrix[key])==n and all(len(row)==n for row in matrix[key]),'Матрица должна иметь размер N×N.')
        require(all(matrix[key][i][i]==0 for i in range(n)),'Диагональ матрицы должна быть нулевой.')
    if ref:
        buildings={b['building_id']:b for node in ref['access_nodes'] for b in node['buildings']};coverage(ref,buildings,matrix)
    return matrix

def day_input(day,payload,ref,matrix):
    require(ref is not None,'Сначала загрузите справочники.','REFERENCE_NOT_LOADED',409)
    require(matrix is not None,'Сначала загрузите матрицу.','MATRIX_NOT_LOADED',409)
    payload=deepcopy(payload)
    if isinstance(payload.get('orders'),list):
        for order in payload['orders']:
            if isinstance(order,dict):order.pop('fact',None)
    data=canonical('DayInput',payload);require(data['date']==str(day),'Дата URL не совпадает с date.')
    now=datetime.fromisoformat(data['now'].replace('Z','+00:00'))
    require(now.astimezone(ZONE).date().isoformat()==data['date'],'now относится к другому модельному дню.')
    unique(data['orders'],'order_id');people={p['staff_id'] for p in ref['staff']};works={w['code']:w for w in ref['work_types']}
    require(set(data.get('absent_staff_ids',[]))<=people,'Неизвестный отсутствующий сотрудник.')
    nodes={n['access_node_id']:n for n in ref['access_nodes']}
    buildings={b['building_id']:b for n in nodes.values() for b in n['buildings']};coverage(ref,buildings,matrix)
    for order in data['orders']:
        order.pop('fact',None)
        require(order['work_type_code'] in works,'Неизвестный тип работы.')
        node=nodes.get(order['access_node_id']);building=buildings.get(order['building_id'])
        require(node is not None and building is not None,'Неизвестный узел или дом.')
        require(any(b['building_id']==order['building_id'] for b in node['buildings']) and node['technology']==order['technology'],'Наряд не соответствует дому/узлу/технологии.')
        require(all(order[k]==building[k] for k in ['address','lat','lon','building_type']),'Атрибуты адреса не совпадают со справочником.')
        require(not building['overhead_line'] or order['requires_height'],'Для ВЛС нужен допуск к высоте.')
        parse=lambda v:datetime.fromisoformat(v.replace('Z','+00:00'))
        start,end,latest,deadline=map(parse,[order['slot']['start'],order['slot']['end'],order['latest_start'],order['deadline']])
        require(start.astimezone(ZONE).date().isoformat()==data['date'],'Слот наряда относится к другому дню.')
        require(parse(order['registered_at'])<=now,'Наряд зарегистрирован после now; передайте его событием NEW_ORDER.')
        require(end-start==timedelta(hours=2),'Слот должен длиться два часа.')
        work=works[order['work_type_code']];delay=work['max_start_delay_min']
        expected=min(end,start+timedelta(minutes=delay)) if delay is not None else end
        require(latest==expected,'latest_start не соответствует слоту и типу работы.')
        require(latest+timedelta(minutes=work['duration_min'])<=deadline,'Контрольный срок раньше допустимого завершения.')
    data.setdefault('absent_staff_ids',[])
    return data

def reference_counts(ref,buildings):
    return dict(status='loaded',counts={**{k:len(v) for k,v in ref.items()},'buildings':len(buildings)})
