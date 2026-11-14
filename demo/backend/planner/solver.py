"""Bounded route-construction heuristic, with each assignment batch solved by CP-SAT.

Candidates are complete feasible routes, including lunch, reloads and depot return.
This is not a claim of globally optimal VRPTW or proof that dropped jobs are impossible.
"""
import time
from copy import deepcopy
from collections import defaultdict
from datetime import datetime, timedelta
from ortools.sat.python import cp_model

def stamp(value):return datetime.fromisoformat(value)
def iso(value):return value.isoformat(timespec='seconds')

def qualified(person,order,works):
    return bool(set(person['profiles'])&set(works[order['work_type_code']]['profiles'])) and order['technology'] in person['technologies'] and (not order['requires_height'] or person['height_permit'])

class Context:
    def __init__(self,reference,day,matrix):
        self.day=day;self.now=stamp(day['now']);self.reference=reference
        self.works={w['code']:w for w in reference['work_types']}
        self.centers={c['service_center_id']:c for c in reference['service_centers']}
        self.positions={p:i for i,p in enumerate(matrix['points'])};self.matrix=matrix
        self.prefixes={};self.unavailable={}

    def local(self,value):
        return stamp(self.day['date']+'T'+value+':00+05:00')

    def travel(self,a,b):return self.matrix['durations_sec'][self.positions[a]][self.positions[b]]
    def distance(self,a,b):return self.matrix['distances_m'][self.positions[a]][self.positions[b]]

    def schedule(self,person,jobs):
        prefix=self.prefixes.get(person['staff_id'],[])
        blocked=self.unavailable.get(person['staff_id'])
        if blocked and (not blocked.get('until') or stamp(blocked['until'])>=self.local(person['shift']['end'])):
            if jobs:return None
            return dict(staff_id=person['staff_id'],service_center_id=person['service_center_id'],status='UNAVAILABLE',
                unavailable_from=blocked['from'],unavailable_until=blocked.get('until'),stops=deepcopy(prefix))
        if prefix and prefix[-1]['type']=='DEPOT_END':
            return None if jobs else dict(staff_id=person['staff_id'],service_center_id=person['service_center_id'],status='ACTIVE',stops=deepcopy(prefix))
        if not jobs and not prefix:return dict(staff_id=person['staff_id'],service_center_id=person['service_center_id'],status='ACTIVE',stops=[])
        candidates=[]
        lunch_done=any(s['type']=='BREAK' for s in prefix)
        for lunch_gap in ([-1] if lunch_done else range(len(jobs)+1)):
            result=self._schedule(person,jobs,lunch_gap)
            if result:candidates.append(result)
        return min(candidates,key=lambda r:(r['totals']['travel_sec'],r['stops'][-1]['end'])) if candidates else None

    def _schedule(self,person,jobs,lunch_gap):
        shift=person['shift'];finish=self.local(shift['end']);current=max(self.local(shift['start']),self.now)
        location=person['service_center_id'];stock=person['equipment_start'].copy();stops=deepcopy(self.prefixes.get(person['staff_id'],[]))
        if stops:
            location=stops[-1]['location_id'];current=max(current,stamp(stops[-1]['end']));stock=stops[-1]['equipment_after'].copy()
        if current>finish:return None
        def add(kind,place,arrival,start,end,order=None):
            nonlocal current,location
            stop=dict(seq=len(stops)+1,type=kind,location_id=place,arrival=iso(arrival),start=iso(start),end=iso(end),
                travel_sec=self.travel(location,place) if stops else 0,distance_m=self.distance(location,place) if stops else 0,
                status='PLANNED',equipment_after=stock.copy())
            if order:stop['order_id']=order['order_id']
            stops.append(stop);current=end;location=place
        blocked=self.unavailable.get(person['staff_id'])
        # A not-yet-started shift must begin after an active outage. Starting
        # its depot stop at shift.start inside the outage is forbidden.
        if not stops and blocked and blocked.get('until'):
            current=max(current,stamp(blocked['until']))
        if not stops:add('DEPOT_START',location,current,current,current)
        if blocked and blocked.get('until'):
            center=self.centers[person['service_center_id']]
            arrival=current+timedelta(seconds=self.travel(location,center['service_center_id']))
            start=max(arrival,stamp(blocked['until']),self.local(center['opening_hours']['open']))
            end=start+timedelta(minutes=center['restock_duration_min'])
            if end>self.local(center['opening_hours']['close']) or end>finish:return None
            stock=person['equipment_capacity'].copy();add('RESTOCK',center['service_center_id'],arrival,start,end)
        for index in range(len(jobs)+1):
            if index==lunch_gap:
                start=max(current,self.local(shift['break_window']['from']))
                if start>self.local(shift['break_window']['to']):return None
                add('BREAK',location,current,start,start+timedelta(minutes=shift['break_duration_min']))
            if index==len(jobs):break
            order=jobs[index]
            if not qualified(person,order,self.works):return None
            if any(stock[k]<q for k,q in order['required_equipment'].items()):
                options=[]
                for center in self.centers.values():
                    arrival=current+timedelta(seconds=self.travel(location,center['service_center_id']))
                    start=max(arrival,self.local(center['opening_hours']['open']))
                    end=start+timedelta(minutes=center['restock_duration_min'])
                    if end>self.local(center['opening_hours']['close']):continue
                    if any(person['equipment_capacity'][k]<q for k,q in order['required_equipment'].items()):continue
                    next_arrival=end+timedelta(seconds=self.travel(center['service_center_id'],order['building_id']))
                    options.append((next_arrival,center['service_center_id'],arrival,start,end))
                if not options:return None
                _,place,arrival,start,end=min(options)
                stock=person['equipment_capacity'].copy();add('RESTOCK',place,arrival,start,end)
            arrival=current+timedelta(seconds=self.travel(location,order['building_id']))
            start=max(arrival,stamp(order['slot']['start']),stamp(order['registered_at']),self.now)
            end=start+timedelta(minutes=self.works[order['work_type_code']]['duration_min'])
            if start>stamp(order['latest_start']) or end>stamp(order['deadline']) or end>finish:return None
            for k,q in order['required_equipment'].items():stock[k]-=q
            add('VISIT',order['building_id'],arrival,start,end,order)
        arrival=current+timedelta(seconds=self.travel(location,person['service_center_id']))
        if arrival>finish:return None
        add('DEPOT_END',person['service_center_id'],arrival,arrival,arrival)
        totals=dict(visits=len(jobs),travel_sec=sum(s['travel_sec'] for s in stops),distance_m=sum(s['distance_m'] for s in stops),
            work_min=sum(self.works[o['work_type_code']]['duration_min'] for o in jobs))
        available=(finish-self.local(shift['start'])).total_seconds()-shift['break_duration_min']*60
        totals['utilization']=(totals['work_min']*60+totals['travel_sec'])/available if available else 0
        return dict(staff_id=person['staff_id'],service_center_id=person['service_center_id'],status='ACTIVE',stops=stops,totals=totals)

def pgp_groups(orders,works,day):
    nodes=defaultdict(list)
    for order in orders:
        if works[order['work_type_code']]['pgp_relevant']:nodes[order['access_node_id']].append(order)
    groups=[]
    for node,rows in sorted(nodes.items()):
        rows=sorted(rows,key=lambda o:o['registered_at']);used=set()
        for row in rows:
            if row['order_id'] in used:continue
            batch=[o for o in rows if o['order_id'] not in used and stamp(row['registered_at'])<=stamp(o['registered_at'])<=stamp(row['registered_at'])+timedelta(minutes=60)]
            if len(batch)<3:continue
            ids=[o['order_id'] for o in batch];used.update(ids)
            groups.append(dict(group_id=f"PGP-{day['date'].replace('-','')}-{len(groups)+1:03}",access_node_id=node,order_ids=ids,detected_at=day['now'],action='TRANSFER_TO_STATION'))
    return groups

def build_plan(reference,day,matrix,time_limit_sec=30):
    started=time.monotonic();deadline=started+max(0.1,time_limit_sec-0.25);ctx=Context(reference,day,matrix)
    staff=[p for p in reference['staff'] if p['staff_id'] not in day.get('absent_staff_ids',[])]
    groups=pgp_groups(day['orders'],ctx.works,day);grouped={oid for g in groups for oid in g['order_ids']}
    pending={o['order_id']:o for o in day['orders'] if o['order_id'] not in grouped}
    jobs={p['staff_id']:[] for p in staff};routes={p['staff_id']:ctx.schedule(p,[]) for p in staff}
    while pending and time.monotonic()<deadline:
        choices=[]
        for person in staff:
            sid=person['staff_id']
            for order in pending.values():
                if time.monotonic()>=deadline:break
                if not qualified(person,order,ctx.works):continue
                best=None
                # Insert into every gap, rather than forcing a late repeat to block the morning.
                for gap in range(len(jobs[sid])+1):
                    if time.monotonic()>=deadline:break
                    route=ctx.schedule(person,jobs[sid][:gap]+[order]+jobs[sid][gap:])
                    if route and (best is None or (route['totals']['travel_sec'],route['stops'][-1]['end'])<(best['totals']['travel_sec'],best['stops'][-1]['end'])):best=route
                if best:choices.append((sid,order,best))
            if time.monotonic()>=deadline:break
        if not choices:break
        model=cp_model.CpModel();vars=[model.new_bool_var(f'c{i}') for i in range(len(choices))]
        by_staff=defaultdict(list);by_order=defaultdict(list);score=[]
        for var,(sid,order,route) in zip(vars,choices):
            by_staff[sid].append(var);by_order[order['order_id']].append(var)
            extra=route['totals']['travel_sec']-routes[sid].get('totals',{}).get('travel_sec',0)
            # Weighted service count dominates all travel/tie-break costs in one batch.
            score.append(var*((2 if order['is_repeat'] else 1)*100_000_000-extra*10-len(jobs[sid])*1000))
        for group in list(by_staff.values())+list(by_order.values()):model.add_at_most_one(group)
        model.maximize(sum(score));solver=cp_model.CpSolver();solver.parameters.num_search_workers=1
        solver.parameters.max_time_in_seconds=max(.01,min(.75,deadline-time.monotonic()))
        status=solver.solve(model)
        if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):break
        selected=[choice for var,choice in zip(vars,choices) if solver.value(var)]
        if not selected:break
        all_orders={o['order_id']:o for o in day['orders']}
        for sid,order,route in selected:
            jobs[sid]=[all_orders[s['order_id']] for s in route['stops'] if s['type']=='VISIT']
            routes[sid]=route;pending.pop(order['order_id'])
    unassigned=[]
    for order in pending.values():
        eligible=any(qualified(p,order,ctx.works) for p in staff)
        unassigned.append(dict(order_id=order['order_id'],reason_code='OTHER' if eligible else 'NO_QUALIFIED_STAFF',
            reason_text='За отведённое время эвристика не нашла допустимую вставку; невозможность назначения не доказана.' if eligible else 'Нет сотрудника с нужным профилем, технологией и допуском.',suggested_action='RESCHEDULE' if eligible else 'ESCALATE',since=day['now']))
    plan=dict(date=day['date'],plan_version=1,as_of=day['now'],based_on_event_id=None,routes=list(routes.values()),
        unassigned=unassigned,pgp_groups=groups,cancelled=[],alerts=[],computation_ms=round((time.monotonic()-started)*1000))
    visits=sum(r.get('totals',{}).get('visits',0) for r in routes.values())
    plan['summary']=dict(orders_total=len(day['orders']),visits_planned=visits,unassigned=len(unassigned),pgp_orders=len(grouped),cancelled=0,
        travel_sec_total=sum(r.get('totals',{}).get('travel_sec',0) for r in routes.values()))
    from .validate import validate_plan
    validate_plan(reference,day,matrix,plan)
    return plan
