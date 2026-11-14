"""Repair the unstarted suffix; execution history is immutable."""
from copy import deepcopy
import time
from datetime import timezone,timedelta
from .solver import Context,stamp,iso,qualified,pgp_groups
from .validate import validate_plan
from .risks import forecast_routes,update_risk_alerts

class EventError(Exception):
    def __init__(self,code,message,status=400):self.code=code;self.message=message;self.status=status

def apply_event(reference,day,matrix,previous,event,budget=6):
    began=time.monotonic();deadline=began+budget;day=deepcopy(day);plan=deepcopy(previous)
    now=stamp(event['timestamp'])
    if now<stamp(day['now']):raise EventError('EVENT_OUT_OF_ORDER','Событие раньше текущего модельного времени.',409)
    local_zone=timezone(timedelta(hours=5))
    if str(now.astimezone(local_zone).date())!=day['date']:raise EventError('BAD_REQUEST','Событие относится к другому дню.')
    orders={o['order_id']:o for o in day['orders']};kind=event['type'];ctx=Context(reference,dict(day,now=event['timestamp']),matrix)
    people={p['staff_id']:p for p in reference['staff']}
    if event.get('staff_id') and event['staff_id'] not in people:raise EventError('UNKNOWN_STAFF','Сотрудник не найден.',422)
    if event.get('order_id') and event['order_id'] not in orders:raise EventError('UNKNOWN_ORDER','Наряд не найден.',422)
    if kind=='NEW_ORDER':
        o=deepcopy(event['order']);o.pop('fact',None)
        if o['order_id'] in orders:raise EventError('ORDER_EXISTS','Наряд уже существует.',409)
        nodes={n['access_node_id']:n for n in reference['access_nodes']};node=nodes.get(o['access_node_id'])
        building=next((b for b in (node or {}).get('buildings',[]) if b['building_id']==o['building_id']),None)
        if not building or o['technology']!=node['technology'] or o['work_type_code'] not in ctx.works or o['building_id'] not in ctx.positions:
            raise EventError('BAD_REFERENCE','Дом, тип работ или технология отсутствуют в справочниках.',422)
        if any(o[k]!=building[k] for k in ['lat','lon','address','building_type']):raise EventError('BAD_REFERENCE','Адрес не совпадает со справочником дома.',422)
        if stamp(o['registered_at'])>now or stamp(o['slot']['start']).astimezone(local_zone).date().isoformat()!=day['date'] or not stamp(o['slot']['start'])<=stamp(o['latest_start'])<=stamp(o['slot']['end']):
            raise EventError('BAD_REQUEST','Некорректное время нового наряда.')
        orders[o['order_id']]=o;day['orders'].append(o)
    day['now']=event['timestamp']
    if kind in ('VISIT_DELAYED','ORDER_TRANSFERRED'):
        target=next((s for r in plan['routes'] if r['staff_id']==event['staff_id'] for s in r['stops'] if s.get('order_id')==event['order_id']),None)
        if not target or not stamp(target['start'])<=now<stamp(target['end']):raise EventError('VISIT_NOT_ACTIVE','Визит сейчас не выполняется.',422)
        end=event['expected_end'] if kind=='VISIT_DELAYED' else event['actual_end']
        if (kind=='VISIT_DELAYED' and stamp(end)<=stamp(target['end'])) or (kind=='ORDER_TRANSFERRED' and not stamp(target['start'])<=stamp(end)<=now):
            raise EventError('BAD_REQUEST','Некорректное новое время окончания визита.')
        target['end']=end;day.setdefault('_duration_overrides',{})[event['order_id']]=end
    if kind=='STAFF_UNAVAILABLE':
        if event.get('until') and stamp(event['until'])<=now:raise EventError('BAD_REQUEST','Конец недоступности должен быть после события.')
        day.setdefault('_unavailable',{})[event['staff_id']]={'from':event['timestamp'],'until':event.get('until')}
    cancelled=plan['cancelled'];cancelled_ids={c['order_id'] for c in cancelled}
    prefixes={r['staff_id']:[deepcopy(s) for s in r['stops'] if stamp(s['start'])<now or kind in ('VISIT_DELAYED','ORDER_TRANSFERRED') and s.get('order_id')==event.get('order_id') and r['staff_id']==event.get('staff_id')] for r in plan['routes']}
    locked={s['order_id'] for stops in prefixes.values() for s in stops if s.get('order_id')}
    if kind=='ORDER_CANCELLED' and event['order_id'] not in locked and event['order_id'] not in cancelled_ids:
        cancelled.append(dict(order_id=event['order_id'],cancelled_at=event['timestamp'],event_id=event['event_id']));cancelled_ids.add(event['order_id'])
    groups=[]
    for g in plan['pgp_groups']:
        g['order_ids']=[oid for oid in g['order_ids'] if oid not in cancelled_ids and oid not in locked]
        if len(g['order_ids'])>=2:groups.append(g)
    grouped={oid for g in groups for oid in g['order_ids']}
    extra=pgp_groups([o for o in orders.values() if o['order_id'] not in locked|cancelled_ids|grouped],ctx.works,day)
    for g in extra:g['group_id']=f"PGP-{day['date'].replace('-','')}-{previous['plan_version']+1}-{len(groups)+1}";groups.append(g)
    grouped={oid for g in groups for oid in g['order_ids']};pending={k:o for k,o in orders.items() if k not in locked|cancelled_ids|grouped}
    forecasts=forecast_routes(reference,day,matrix,plan,locked|cancelled_ids|grouped)
    ctx.prefixes=prefixes;ctx.unavailable=day.get('_unavailable',{})
    jobs={};routes={}
    for old in plan['routes']:
        sid=old['staff_id'];person=people[sid]
        sequence=[orders[s['order_id']] for s in old['stops'] if s['type']=='VISIT' and s['order_id'] in pending]
        route=ctx.schedule(person,sequence)
        while route is None and sequence:
            sequence.pop();route=ctx.schedule(person,sequence)
        if route is None:
            # An outage can leave an employee unable to complete lunch/return today.
            if sid not in ctx.unavailable:raise EventError('NO_FEASIBLE_REPAIR','Не удалось завершить замороженный маршрут в пределах смены.',409)
            route=dict(staff_id=sid,service_center_id=person['service_center_id'],status='UNAVAILABLE',stops=prefixes[sid],
                unavailable_from=ctx.unavailable[sid]['from'],unavailable_until=ctx.unavailable[sid].get('until'))
        jobs[sid]=sequence;routes[sid]=route
        for o in sequence:pending.pop(o['order_id'],None)
    # Preserve incumbents; fill gaps using a bounded insertion search.
    for oid in sorted(list(pending),key=lambda k:(not pending[k]['is_repeat'],pending[k]['latest_start'])):
        if time.monotonic()>=deadline-.6:break
        order=pending[oid];best=None
        for sid,sequence in jobs.items():
            if time.monotonic()>=deadline-.6:break
            person=people[sid]
            if not qualified(person,order,ctx.works):continue
            for gap in range(len(sequence)+1):
                if time.monotonic()>=deadline-.6:break
                candidate=sequence[:gap]+[order]+sequence[gap:];route=ctx.schedule(person,candidate)
                if route:
                    cost=route['totals']['travel_sec']-sum(s.get('travel_sec',0) for s in routes[sid]['stops'])
                    if best is None or cost<best[0]:best=(cost,sid,candidate,route)
        if best:
            _,sid,sequence,route=best;jobs[sid]=sequence;routes[sid]=route;pending.pop(oid)
    unassigned=[dict(order_id=oid,reason_code='OTHER',reason_text='За время перепланирования допустимая вставка не найдена.',suggested_action='RESCHEDULE',since=day['now']) for oid in pending]
    for route in routes.values():
        for s in route['stops']:s['status']='DONE' if stamp(s['end'])<=now else 'IN_PROGRESS' if stamp(s['start'])<=now else 'PLANNED'
        route['totals']=dict(visits=sum(s['type']=='VISIT' for s in route['stops']),travel_sec=sum(s.get('travel_sec',0) for s in route['stops']),distance_m=sum(s.get('distance_m',0) for s in route['stops']))
    plan.update(plan_version=previous['plan_version']+1,as_of=day['now'],based_on_event_id=event['event_id'],routes=list(routes.values()),unassigned=unassigned,pgp_groups=groups,cancelled=cancelled)
    alerts=plan['alerts'];known={(a['type'],a.get('order_id'),a.get('group_id')) for a in alerts}
    for group in groups:
        key=('PGP_DETECTED',None,group['group_id'])
        if key not in known:
            alerts.append(dict(alert_id=f"ALR-{day['date']}-{len(alerts)+1}",created_at=day['now'],type='PGP_DETECTED',status='ACTIVE',group_id=group['group_id'],suggested_action='TRANSFER_TO_STATION',applied=True,message='Выявлена групповая проблема на '+group['access_node_id']))
    update_risk_alerts(plan,previous,day,forecasts,ctx,people,jobs,locked|cancelled_ids|grouped,deadline)
    plan['summary']=dict(orders_total=len(orders),visits_planned=sum(r['totals']['visits'] for r in routes.values()),unassigned=len(unassigned),pgp_orders=len(grouped),cancelled=len(cancelled),travel_sec_total=sum(r['totals']['travel_sec'] for r in routes.values()))
    try:validate_plan(reference,day,matrix,plan,previous,event)
    except ValueError as exc:
        if 'one lunch for used route' in str(exc):
            raise EventError('UNAVAILABILITY_BREAK_CONFLICT','Правила обеда и недоступности противоречат друг другу: сотрудник уже начал работу, но до конца смены не может сделать обязательный перерыв. Состояние сохранено без изменений.',409) from exc
        raise EventError('NO_FEASIBLE_REPAIR','Не удалось получить допустимое продолжение замороженного плана. Состояние не изменено.',409) from exc
    plan['computation_ms']=round((time.monotonic()-began)*1000)
    return day,plan
