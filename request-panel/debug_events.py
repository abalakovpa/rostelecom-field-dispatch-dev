"""Translate debug controls into official events; never edit a saved plan."""
from datetime import datetime, timedelta
from uuid import uuid4


def unavailable_event(event, staff_id, body, now):
    event.update(type='STAFF_UNAVAILABLE', staff_id=staff_id, reason='OTHER')
    if body.get('until'):
        until = datetime.fromisoformat(body['until'])
        if until.tzinfo is None or until <= now:
            raise ValueError('Конец недоступности должен быть позже модельного времени с часовым поясом')
        event['until'] = until.isoformat()
    return event


def make_event(body, day):
    now = datetime.fromisoformat(day['model_now'])
    action = body['action']
    event = dict(event_id='DEBUG-' + str(uuid4()), timestamp=now.isoformat())
    if action == 'TICK':
        target = datetime.fromisoformat(body['time'])
        if target.tzinfo is None:
            raise ValueError('Время должно содержать часовой пояс')
        if target < now:
            raise ValueError('Модельное время нельзя переводить назад')
        event.update(type='TIME_TICK', timestamp=target.isoformat())
        return event
    if action == 'UNAVAILABLE' and body.get('staff_id'):
        return unavailable_event(event, body['staff_id'], body, now)
    order_id = body['order_id']
    visits = [(r, s) for r in (day.get('plan') or {}).get('routes', [])
              for s in r['stops'] if s['type'] == 'VISIT' and s.get('order_id') == order_id]
    if action == 'CANCEL':
        event.update(type='ORDER_CANCELLED', order_id=order_id, reason='CUSTOMER_REQUEST')
        return event
    if len(visits) != 1:
        raise ValueError('Выберите назначенный визит на этой дате')
    route, stop = visits[0]
    start, end = map(datetime.fromisoformat, (stop['start'], stop['end']))
    if action in ('START', 'FINISH'):
        if now >= end:
            raise ValueError('Визит уже завершён по модельному времени')
        event.update(type='TIME_TICK', timestamp=max(now, start if action == 'START' else end).isoformat())
    elif action == 'DELAY':
        if not start <= now < end:
            raise ValueError('Сначала переведите время к началу визита')
        minutes = int(body.get('minutes', 60))
        if not 1 <= minutes <= 1440:
            raise ValueError('Задержка: от 1 до 1440 минут')
        event.update(type='VISIT_DELAYED', staff_id=route['staff_id'], order_id=order_id,
                     expected_end=(end + timedelta(minutes=minutes)).isoformat())
    elif action == 'UNAVAILABLE':
        return unavailable_event(event, route['staff_id'], body, now)
    else:
        raise ValueError('Неизвестное действие отладки')
    return event
