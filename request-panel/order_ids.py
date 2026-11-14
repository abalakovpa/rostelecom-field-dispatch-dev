"""Keep the organizer's four-digit order suffix without random collisions."""
from hashlib import sha256

def choose_order_id(date, request_id, usage):
    if usage.get('order_id'):
        return usage['order_id']
    prefix='ORD-'+date.replace('-','')+'-'
    used=set(usage['used_order_ids'])
    start=int(sha256(request_id.encode()).hexdigest()[:8],16)%10000
    for offset in range(10000):
        candidate=prefix+f'{(start+offset)%10000:04d}'
        if candidate not in used:return candidate
    raise ValueError('На эту дату исчерпаны 10000 идентификаторов нарядов. Выберите другую дату.')
