"""Deterministic ETA replay and feasible recommendations; no invented traffic or future events."""
from copy import deepcopy
from datetime import timedelta
import math
import time
from .solver import Context,stamp,iso,qualified

def forecast_routes(reference,day,matrix,plan,excluded=()):
    """Replay the current sequence BEFORE repairing it after known changes.

    An unchanged leg may already be in progress: keep its planned ETA unless a
    changed predecessor or model time pushes it later. Do not restart the whole
    journey at now on every TIME_TICK.
    """
    ctx=Context(reference,day,matrix);orders={o['order_id']:o for o in day['orders']}
    people={p['staff_id']:p for p in reference['staff']};excluded=set(excluded);risks={}
    for route in plan['routes']:
        sid=route['staff_id'];person=people[sid];location=person['service_center_id'];end=None
        blocked=day.get('_unavailable',{}).get(sid);resume_used=False
        for s in route['stops']:
            if stamp(s['start'])<ctx.now:
                end=stamp(s['end']);location=s['location_id'];continue
            if s['type']=='DEPOT_START':end=max(stamp(s['end']),ctx.now);location=s['location_id'];continue
            arrival=max(stamp(s['arrival']),ctx.now,(end or ctx.now)+timedelta(seconds=ctx.travel(location,s['location_id'])))
            unavailable=bool(blocked and (not blocked.get('until') or stamp(blocked['until'])>=ctx.local(person['shift']['end'])))
            if blocked and not resume_used:
                resume_used=True
                until=stamp(blocked['until']) if blocked.get('until') else ctx.local(person['shift']['end'])
                arrival=max(arrival,until+timedelta(seconds=ctx.travel(person['service_center_id'],s['location_id'])))
                unavailable=not blocked.get('until') or until>=ctx.local(person['shift']['end'])
            start=max(arrival,stamp(s['start']))
            if s['type']=='VISIT':
                o=orders[s['order_id']];duration=timedelta(minutes=ctx.works[o['work_type_code']]['duration_min'])
                end=start+duration
                if o['order_id'] not in excluded and start>stamp(o['latest_start']):
                    causes=[]
                    if blocked:causes.append('Недоступность исполнителя')
                    if any(stop.get('order_id') in day.get('_duration_overrides',{}) for stop in route['stops'] if stamp(stop['start'])<ctx.now):causes.append('Задержка предыдущего визита')
                    if not causes:causes.append('Оставшаяся последовательность работ и время проезда')
                    risks[o['order_id']]=dict(order_id=o['order_id'],staff_id=sid,
                        forecast_start=None if unavailable else iso(start),lateness_min=None if unavailable else math.ceil((start-stamp(o['latest_start'])).total_seconds()/60),
                        reason='; '.join(causes),warning_deadline=iso(stamp(o['slot']['start'])-timedelta(minutes=30)),
                        forecast_available=not unavailable)
            else:
                end=start+(stamp(s['end'])-stamp(s['start']))
            location=s['location_id']
    return risks

def feasible_alternative(ctx,order,people,jobs,excluded_staff,deadline):
    for person in people.values():
        if time.monotonic()>=deadline:break
        sid=person['staff_id']
        if sid==excluded_staff or sid not in jobs or not qualified(person,order,ctx.works):continue
        sequence=[o for o in jobs[sid] if o['order_id']!=order['order_id']]
        for gap in range(len(sequence)+1):
            if time.monotonic()>=deadline:return None
            route=ctx.schedule(person,sequence[:gap]+[order]+sequence[gap:])
            if route:
                visit=next(s for s in route['stops'] if s.get('order_id')==order['order_id'])
                return {'staff_id':sid,'start':visit['start']}
    return None

def feasible_slot(ctx,order,people,jobs,deadline):
    # Suggest, never apply, a new two-hour slot today. Keep the hard deadline.
    minimum=max(ctx.now,stamp(order['slot']['end']))
    start=minimum.replace(second=0,microsecond=0)
    start+=timedelta(minutes=(-start.minute)%15)
    if start<minimum:start+=timedelta(minutes=15)
    work=ctx.works[order['work_type_code']]
    last=stamp(order['deadline'])-timedelta(minutes=work['duration_min'])
    while start<=last and start.date().isoformat()==ctx.day['date'] and time.monotonic()<deadline:
        modified=deepcopy(order);end=start+timedelta(hours=2)
        delay=work.get('max_start_delay_min')
        modified.update(slot={'start':iso(start),'end':iso(end)},latest_start=iso(min(end,start+timedelta(minutes=delay))) if delay is not None else iso(end))
        found=feasible_alternative(ctx,modified,people,jobs,None,deadline)
        if found:return modified['slot']
        start+=timedelta(minutes=30)
    return None

def update_risk_alerts(plan,previous,day,forecasts,ctx,people,jobs,excluded,deadline):
    orders={o['order_id']:o for o in day['orders']};now=stamp(day['now']);excluded=set(excluded)
    assigned={s['order_id']:(r['staff_id'],s) for r in plan['routes'] for s in r['stops'] if s.get('order_id')}
    # Existing history is retained. A resolved alert is not recycled for a new episode.
    active={a['order_id']:a for a in plan['alerts'] if a['type']=='LATE_RISK' and a['status']=='ACTIVE'}
    for oid,risk in forecasts.items():
        if oid in excluded:continue
        current=assigned.get(oid);valid=current and stamp(current[1]['start'])<=stamp(orders[oid]['latest_start'])
        alert=active.get(oid)
        if alert is None:
            alert=dict(alert_id=f"ALR-{day['date']}-{len(plan['alerts'])+1}",created_at=day['now'],type='LATE_RISK',order_id=oid)
            plan['alerts'].append(alert)
        alert.setdefault('first_forecast_at',alert.get('forecast_at',day['now']))
        alert.update(risk)
        alert['forecast_at']=day['now'];alert['timely']=stamp(alert['first_forecast_at'])<=stamp(risk['warning_deadline'])
        alert.update(status='RESOLVED' if valid else 'ACTIVE',resolved_at=day['now'] if valid else None,applied=False,
            suggested_action='RESCHEDULE',suggested_staff_id=None,proposed_slot=None)
        if valid and current[0]!=risk['staff_id']:
            alert.update(suggested_action='REASSIGN',suggested_staff_id=current[0],applied=True,resolution='REASSIGNED')
            action=f"Передан {current[0]}, новое начало {current[1]['start'][11:16]}."
        elif valid:
            alert['resolution']='ROUTE_ADJUSTED';action='Риск снят перестановкой оставшихся визитов; согласованный слот сохранён.'
        else:
            found=feasible_alternative(ctx,orders[oid],people,jobs,risk['staff_id'],deadline)
            if found:
                alert.update(suggested_action='REASSIGN',suggested_staff_id=found['staff_id'],suggested_start=found['start'])
                action=f"Проверена допустимая вставка у {found['staff_id']}; рекомендация ещё не применена."
            else:
                slot=feasible_slot(ctx,orders[oid],people,jobs,deadline)
                alert['proposed_slot']=slot
                action='Новый слот проверен по текущим маршрутам; требуется согласование с абонентом.' if slot else 'Согласуйте перенос: проверенный новый слот пока не найден в доступном бюджете поиска.'
        eta=f"Прогноз начала без вмешательства {risk['forecast_start'][11:16]}, опоздание {risk['lateness_min']} мин." if risk['forecast_start'] else 'Исполнитель не сможет продолжить визиты в этой смене; точный прогноз начала недоступен.'
        alert['message']=risk['reason']+'. '+eta+' '+action
    for oid,alert in active.items():
        if oid in forecasts and oid not in excluded:continue
        current=assigned.get(oid)
        if oid in excluded or (current and stamp(current[1]['start'])<=stamp(orders[oid]['latest_start'])):
            alert.update(status='RESOLVED',resolved_at=day['now'])
            alert['resolution']='NO_LONGER_APPLICABLE' if oid in excluded else 'ON_TIME'
