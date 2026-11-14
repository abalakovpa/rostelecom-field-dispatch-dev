"""Automatic scheduling policy for the team's manual-demo workflow.

Official pgp_groups remain exclusive buckets. Incidents with individual visits
are metadata in incident_groups, so order accounting and equipment are not doubled.
"""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from time import monotonic
from planner_openapi import plan_openapi

def stamp(value): return datetime.fromisoformat(value)

def enrich_risk_alerts(result, orders):
    """UI metadata uses the original promised slot, even after an auto move.

    Preserve timestamps of previously issued warnings. Missing forecast data is
    unknown, not proof that an employee is unavailable.
    """
    by_id={o['order_id']:o for o in orders}
    for alert in result.get('alerts',[]):
        if alert['type']!='LATE_RISK':continue
        order=by_id.get(alert.get('order_id'))
        if not order:continue
        change=next((c for c in result.get('automatic_reschedules',[])
            if c['order_id']==alert['order_id'] and c.get('changed_at')==alert['created_at']),None)
        slot=change['old_slot'] if change else order['slot']
        alert.setdefault('warning_deadline',(stamp(slot['start'])-timedelta(minutes=30)).isoformat())
        alert.setdefault('timely',stamp(alert['created_at'])<=stamp(alert['warning_deadline']))
        alert.setdefault('forecast_at',alert['created_at'])
        if alert.get('forecast_start') is not None:alert.setdefault('forecast_available',True)
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
    original_orders=deepcopy(day['orders'])
    previous=request.get('previous_plan');event=request.get('event')
    budget=max(.05,float(request.get('time_limit_sec',7 if event else 25)))
    deadline=monotonic()+budget
    cancelled=deepcopy((previous or {}).get('cancelled',[]))
    if event and event['type']=='ORDER_CANCELLED':
        begun=any(s.get('order_id')==event['order_id'] and stamp(s['start'])<stamp(event['timestamp']) for r in previous['routes'] for s in r['stops'])
        if not begun and not any(c['order_id']==event['order_id'] for c in cancelled):cancelled.append({'order_id':event['order_id'],'cancelled_at':event['timestamp'],'event_id':(event or {}).get('event_id','INITIAL')})
    def solve(candidate,remaining):
        return plan_openapi(reference,matrix,candidate,previous=previous,event=event,cancelled=cancelled,pgp_groups=(),time_limit_sec=max(.01,remaining))
    result=solve(day,budget*.4)
    risk_context={a['order_id']:deepcopy(a) for a in result['alerts'] if a['type']=='LATE_RISK' and a.get('order_id')}
    changes=[]
    future_transfers=[]
    calendar=deepcopy(request.get('calendar',{}))
    same_day_deadline=monotonic()+max(0,deadline-monotonic())*.6
    # On events only: try later 2-hour slots on this day, preserving deadline.
    for missing in list(result['unassigned']):
        if monotonic()>=deadline:break
        order=next(o for o in day['orders'] if o['order_id']==missing['order_id'])
        duration=order.get('_remaining_duration_sec',next(w['duration_min']*60 for w in reference['work_types'] if w['code']==order['work_type_code']))
        grace=next(w.get('max_start_delay_min') for w in reference['work_types'] if w['code']==order['work_type_code'])
        start=max(stamp(day['now']),stamp(order['slot']['start'])+timedelta(minutes=30))
        while start.date().isoformat()==day['date'] and monotonic()<same_day_deadline:
            candidate=deepcopy(day);updated=next(o for o in candidate['orders'] if o['order_id']==order['order_id'])
            slot={'start':start.isoformat(),'end':(start+timedelta(hours=2)).isoformat()}
            latest=start+timedelta(minutes=grace if grace is not None else 120)
            updated.update(slot=slot,latest_start=latest.isoformat())
            trial=solve(candidate,min(.25,deadline-monotonic()))
            formerly_assigned={s['order_id'] for r in result['routes'] for s in r['stops'] if s['type']=='VISIT'}
            assigned={s['order_id'] for r in trial['routes'] for s in r['stops'] if s['type']=='VISIT'}
            if order['order_id'] in assigned and formerly_assigned<=assigned:
                changes.append({'order_id':order['order_id'],'old_slot':deepcopy(order['slot']),'slot':slot,'latest_start':updated['latest_start']})
                day=candidate;result=trial;break
            start+=timedelta(minutes=30)
    # Reserve a real route in a later day's calendar, not merely a suggested date.
    for missing in list(result['unassigned']):
        if monotonic()>=deadline:break
        order=next(o for o in day['orders'] if o['order_id']==missing['order_id'])
        duration=order.get('_remaining_duration_sec',next(w['duration_min']*60 for w in reference['work_types'] if w['code']==order['work_type_code']))
        grace=next(w.get('max_start_delay_min') for w in reference['work_types'] if w['code']==order['work_type_code'])
        local=timezone(timedelta(hours=5))
        target_date=datetime.fromisoformat(day['date']).date()+timedelta(days=1)
        last_date=target_date+timedelta(days=365)
        accepted=False
        while target_date<=last_date and monotonic()<deadline:
            key=target_date.isoformat()
            saved=calendar.get(key)
            if saved:
                target=deepcopy(saved['input']);old_plan=saved.get('plan')
            else:
                target={'date':key,'now':key+'T00:00:00+05:00','orders':[],'absent_staff_ids':[]};old_plan=None
            # Never rewrite a day already advanced by events.
            if saved and saved.get('events'):target_date+=timedelta(days=1);continue
            if any(o['order_id']==order['order_id'] for o in target['orders']):break
            earliest=min((p['shift']['start'] for p in reference['staff'] if p['staff_id'] not in target.get('absent_staff_ids',[])),default='23:59')
            start=max(stamp(key+'T'+earliest+':00+05:00'),stamp(target['now']))
            while start.date()==target_date and monotonic()<deadline:
                candidate=deepcopy(target);moved=deepcopy(order)
                slot={'start':start.isoformat(),'end':(start+timedelta(hours=2)).isoformat()}
                latest=start+timedelta(minutes=grace if grace is not None else 120)
                moved.update(slot=slot,latest_start=latest.isoformat());candidate['orders'].append(moved)
                trial=plan_openapi(reference,matrix,candidate,previous=old_plan,time_limit_sec=min(.3,max(.01,deadline-monotonic())),cancelled=(old_plan or {}).get('cancelled',[]))
                assigned={s['order_id'] for r in trial['routes'] for s in r['stops'] if s['type']=='VISIT'}
                old_visits={(r['staff_id'],s['order_id'],s['arrival'],s['start'],s['end']) for r in (old_plan or {}).get('routes',[]) for s in r['stops'] if s['type']=='VISIT'}
                new_visits={(r['staff_id'],s['order_id'],s['arrival'],s['start'],s['end']) for r in trial['routes'] for s in r['stops'] if s['type']=='VISIT'}
                if moved['order_id'] in assigned and old_visits<=new_visits:
                    future_transfers.append({'order_id':moved['order_id'],'from_date':day['date'],'to_date':key,'old_slot':deepcopy(order['slot']),'slot':slot,'target_input':candidate,'target_plan':trial})
                    calendar[key]={'input':candidate,'plan':trial,'events':[]}
                    result['unassigned']=[u for u in result['unassigned'] if u['order_id']!=order['order_id']]
                    day['orders']=[o for o in day['orders'] if o['order_id']!=order['order_id']]
                    accepted=True;break
                start+=timedelta(minutes=30)
            if accepted:break
            target_date+=timedelta(days=1)
    result['_future_transfers']=future_transfers
    result['transferred_orders']=deepcopy((previous or {}).get('transferred_orders',[]))+[{k:v for k,v in transfer.items() if k not in ('target_input','target_plan')} for transfer in future_transfers]
    result['incident_groups']=groups_for(reference,day,previous,cancelled)
    result['_order_updates']=changes
    result['automatic_reschedules']=deepcopy((previous or {}).get('automatic_reschedules',[]))+[{**c,'changed_at':day['now'],'event_id':(event or {}).get('event_id','INITIAL')} for c in changes]
    # plan_openapi may reuse historical alert objects from previous_plan.
    # Enrichment and closing a risk must not rewrite a preceding version.
    result['alerts']=deepcopy(result['alerts'])
    moved={c['order_id']:c for c in [*changes,*future_transfers]}
    cancelled_ids={c['order_id'] for c in cancelled}
    for alert in result['alerts']:
        if alert['type']=='LATE_RISK' and alert['status']=='ACTIVE' and alert.get('order_id') in moved:
            alert.update(status='RESOLVED',resolved_at=day['now'],applied=True,
                resolution='AUTO_RESCHEDULE',suggested_action='RESCHEDULE',proposed_slot=moved[alert['order_id']]['slot'])
        elif alert['type']=='LATE_RISK' and alert['status']=='ACTIVE' and alert.get('order_id') in cancelled_ids:
            alert.update(status='RESOLVED',resolved_at=day['now'],applied=False,
                resolution='ORDER_CANCELLED',suggested_action='NONE')
    for change in changes:
        forecast={k:v for k,v in risk_context.get(change['order_id'],{}).items()
            if k in ('forecast_start','forecast_available','lateness_min','forecast_at','staff_id')}
        result['alerts'].append({**forecast,'alert_id':f"AUTO-{(event or {}).get('event_id','INITIAL')}-{change['order_id']}",'created_at':day['now'],'type':'LATE_RISK','status':'RESOLVED','order_id':change['order_id'],'suggested_action':'RESCHEDULE','proposed_slot':change['slot'],'applied':True,'resolved_at':day['now'],'message':'Система автоматически назначила новое время визита'})
    enrich_risk_alerts(result,original_orders)
    return result
