"""Independent replay of initial plans. Fails closed before anything is saved."""
from collections import Counter
from datetime import datetime,timedelta

def validate_plan(reference,day,matrix,plan,previous=None,event=None):
    def require(ok,message):
        if not ok:raise ValueError('Invalid plan: '+message)
    parse=datetime.fromisoformat
    local=lambda t:parse(day['date']+'T'+t+':00+05:00')
    staff={p['staff_id']:p for p in reference['staff'] if p['staff_id'] not in day.get('absent_staff_ids',[])}
    orders={o['order_id']:o for o in day['orders']};works={w['code']:w for w in reference['work_types']}
    centers={c['service_center_id']:c for c in reference['service_centers']};idx={p:i for i,p in enumerate(matrix['points'])}
    seen=Counter();route_staff=[]
    frozen={}
    if previous:
        for r in previous['routes']:
            for s in r['stops']:
                if parse(s['start'])<parse(day['now']):frozen[(r['staff_id'],s['seq'])]=s
    preserved=set()
    for route in plan['routes']:
        person=staff[route['staff_id']];route_staff.append(person['staff_id']);shift=person['shift'];stops=route['stops']
        require(route['service_center_id']==person['service_center_id'],'route depot')
        if not stops:continue
        require(stops[0]['type']=='DEPOT_START' and (stops[-1]['type']=='DEPOT_END' or route['status']=='UNAVAILABLE'),'depot endpoints')
        require(stops[0]['location_id']==person['service_center_id'],'own depot')
        if stops[-1]['type']=='DEPOT_END':require(stops[-1]['location_id']==person['service_center_id'],'return depot')
        stock=person['equipment_start'].copy();breaks=[];visits=0
        for n,stop in enumerate(stops):
            arrival,start,end=map(parse,[stop['arrival'],stop['start'],stop['end']]);location=stop['location_id']
            key=(route['staff_id'],stop['seq']);old=frozen.get(key)
            if old:
                preserved.add(key)
                require(all(stop.get(k)==old.get(k) for k in ['type','order_id','location_id','arrival','start']),'frozen stop changed')
                allowed=event and event['type'] in ('VISIT_DELAYED','ORDER_TRANSFERRED') and stop.get('order_id')==event.get('order_id') and route['staff_id']==event.get('staff_id')
                require(stop['end']==old['end'] or allowed,'frozen end changed without event')
            require(stop['seq']==n+1,'consecutive stop sequence')
            require(local(shift['start'])<=arrival<=start<=end<=local(shift['end']),'shift/time order')
            require(old or start>=parse(day['now']),'new stop cannot start in the past')
            if n:
                predecessor=stops[n-1];travel=matrix['durations_sec'][idx[predecessor['location_id']]][idx[location]]
                require(arrival>=parse(predecessor['end'])+timedelta(seconds=travel),'road time')
                if previous and not old:
                    require(arrival>=max(parse(predecessor['end']),parse(day['now']))+timedelta(seconds=travel),'new suffix cannot travel before notification')
            if stop['type']=='VISIT':
                o=orders[stop['order_id']];w=works[o['work_type_code']];seen[o['order_id']]+=1;visits+=1
                require(location==o['building_id'],'visit building')
                require(bool(set(person['profiles'])&set(w['profiles'])) and o['technology'] in person['technologies'],'qualification')
                require(not o['requires_height'] or person['height_permit'],'height')
                require(parse(o['slot']['start'])<=start<=parse(o['latest_start']),'slot')
                require(start>=parse(o['registered_at']) and (end<=parse(o['deadline']) or old),'registration/deadline')
                override=day.get('_duration_overrides',{}).get(o['order_id'])
                require(end==parse(override) if override else end-start==timedelta(minutes=w['duration_min']),'normative duration')
                for key,q in o['required_equipment'].items():stock[key]-=q
                require(all(q>=0 for q in stock.values()),'nonnegative equipment')
            elif stop['type']=='BREAK':
                breaks.append(stop)
                require(n>0 and location==stops[n-1]['location_id'],'break location')
                require(local(shift['break_window']['from'])<=start<=local(shift['break_window']['to']),'break start window')
                require(end-start>=timedelta(minutes=shift['break_duration_min']),'lunch duration')
            elif stop['type']=='RESTOCK':
                c=centers[location]
                require(local(c['opening_hours']['open'])<=start<=end<=local(c['opening_hours']['close']),'depot opening hours')
                require(end-start>=timedelta(minutes=c['restock_duration_min']),'reload duration')
                stock=person['equipment_capacity'].copy()
            else:
                require(stop['type'] in ('DEPOT_START','DEPOT_END'),'stop kind')
                require(arrival==start==end,'instant depot stop')
                require(n==0 if stop['type']=='DEPOT_START' else n==len(stops)-1,'depot placement')
            require(stop.get('equipment_after',stock)==stock,'equipment trace')
        require(not visits or len(breaks)==1,'one lunch for used route')
        blocked=day.get('_unavailable',{}).get(route['staff_id'])
        if blocked:
            until=parse(blocked['until']) if blocked.get('until') else local(shift['end'])
            require(all(not(parse(blocked['from'])<=parse(s['start'])<until) for s in stops),'stop during unavailability')
    require(preserved==set(frozen),'frozen stop removed')
    require(Counter(route_staff)==Counter(staff.keys()),'one route per present employee')
    for row in plan['unassigned']:seen[row['order_id']]+=1
    for group in plan['pgp_groups']:
        group_orders=[orders[oid] for oid in group['order_ids']]
        prior_group=previous and any(g['group_id']==group['group_id'] for g in previous['pgp_groups'])
        require(len(group_orders)>=(2 if prior_group else 3),'PGP minimum')
        require(all(o['access_node_id']==group['access_node_id'] and works[o['work_type_code']]['pgp_relevant'] for o in group_orders),'PGP node/types')
        times=[parse(o['registered_at']) for o in group_orders]
        require(max(times)-min(times)<=timedelta(minutes=60),'PGP interval')
        seen.update(group['order_ids'])
    for row in plan['cancelled']:seen[row['order_id']]+=1
    require(seen==Counter(orders.keys()),'every order accounted exactly once')
    return True
