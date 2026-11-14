"""Automatic scheduling policy for the team's manual-demo workflow.

Official pgp_groups remain exclusive buckets. Incidents with individual visits
are metadata in incident_groups, so order accounting and equipment are not doubled.
"""
from copy import deepcopy
from datetime import datetime,timedelta
from time import monotonic
from planner_openapi import plan_openapi

def stamp(value): return datetime.fromisoformat(value)
def groups_for(reference,day,previous,cancelled):
    groups=deepcopy((previous or {}).get('incident_groups',[]))
    eligible={w['code'] for w in reference['work_types'] if w.get('pgp_relevant')}
    excluded={c['order_id'] for c in cancelled}
    orders=[o for o in day['orders'] if o['work_type_code'] in eligible and o['order_id'] not in excluded]
    by_id={o['order_id']:o for o in orders};used=set()
    for group in groups:
        group['order_ids']=[oid for oid in group['order_ids'] if oid in by_id]
        used.update(group['order_ids'])
    for order in sorted(orders,key=lambda o:(stamp(o['registered_at']),o['order_id'])):
        if order['order_id'] in used:continue
        target=next((g for g in groups if g['access_node_id']==order['access_node_id'] and any(abs((stamp(order['registered_at'])-stamp(by_id[oid]['registered_at'])).total_seconds())<=3600 for oid in g['order_ids'])),None)
        if target:
            target['order_ids'].append(order['order_id']);used.add(order['order_id']);continue
        cluster=[o for o in orders if o['order_id'] not in used and o['access_node_id']==order['access_node_id'] and 0<=(stamp(o['registered_at'])-stamp(order['registered_at'])).total_seconds()<=3600]
        if len(cluster)>=3:
            ids=[o['order_id'] for o in cluster];used.update(ids)
            groups.append({'group_id':f"INC-{day['date']}-{len(groups)+1}",'access_node_id':order['access_node_id'],'order_ids':ids,'detected_at':day['now'],'action':'INDIVIDUAL_VISITS'})
    return [g for g in groups if g['order_ids']]

def calculate(request):
    reference=request['reference'];matrix=request['matrix'];day=deepcopy(request['day'])
    previous=request.get('previous_plan');event=request.get('event')
    budget=max(.05,float(request.get('time_limit_sec',7 if event else 25)))
    deadline=monotonic()+budget
    cancelled=deepcopy((previous or {}).get('cancelled',[]))
    if event and event['type']=='ORDER_CANCELLED':
        begun=any(s.get('order_id')==event['order_id'] and stamp(s['start'])<stamp(event['timestamp']) for r in previous['routes'] for s in r['stops'])
        if not begun and not any(c['order_id']==event['order_id'] for c in cancelled):cancelled.append({'order_id':event['order_id'],'cancelled_at':event['timestamp'],'event_id':event['event_id']})
    def solve(candidate,remaining):
        return plan_openapi(reference,matrix,candidate,previous=previous,event=event,cancelled=cancelled,pgp_groups=(),time_limit_sec=max(.01,remaining))
    result=solve(day,budget*.5 if event else budget)
    changes=[]
    # On events only: try later 2-hour slots on this day, preserving deadline.
    for missing in list(result['unassigned']) if event else []:
        if monotonic()>=deadline:break
        order=next(o for o in day['orders'] if o['order_id']==missing['order_id'])
        duration=order.get('_remaining_duration_sec',next(w['duration_min']*60 for w in reference['work_types'] if w['code']==order['work_type_code']))
        grace=next(w.get('max_start_delay_min') for w in reference['work_types'] if w['code']==order['work_type_code'])
        start=max(stamp(day['now']),stamp(order['slot']['start'])+timedelta(minutes=30))
        while start.date().isoformat()==day['date'] and start+timedelta(seconds=duration)<=stamp(order['deadline']) and monotonic()<deadline:
            candidate=deepcopy(day);updated=next(o for o in candidate['orders'] if o['order_id']==order['order_id'])
            slot={'start':start.isoformat(),'end':(start+timedelta(hours=2)).isoformat()}
            latest=min(start+timedelta(minutes=grace if grace is not None else 120),stamp(order['deadline'])-timedelta(seconds=duration))
            updated.update(slot=slot,latest_start=latest.isoformat())
            trial=solve(candidate,min(.25,deadline-monotonic()))
            formerly_assigned={s['order_id'] for r in result['routes'] for s in r['stops'] if s['type']=='VISIT'}
            assigned={s['order_id'] for r in trial['routes'] for s in r['stops'] if s['type']=='VISIT'}
            if order['order_id'] in assigned and formerly_assigned<=assigned:
                changes.append({'order_id':order['order_id'],'old_slot':deepcopy(order['slot']),'slot':slot,'latest_start':updated['latest_start']})
                day=candidate;result=trial;break
            start+=timedelta(minutes=30)
    result['incident_groups']=groups_for(reference,day,previous,cancelled)
    result['_order_updates']=changes
    result['automatic_reschedules']=deepcopy((previous or {}).get('automatic_reschedules',[]))+[{**c,'changed_at':day['now'],'event_id':event['event_id']} for c in changes]
    for change in changes:
        result['alerts'].append({'alert_id':f"AUTO-{event['event_id']}-{change['order_id']}",'created_at':day['now'],'type':'LATE_RISK','status':'RESOLVED','order_id':change['order_id'],'suggested_action':'RESCHEDULE','proposed_slot':change['slot'],'applied':True,'resolved_at':day['now'],'message':'Система автоматически назначила новое время визита'})
    return result
