// UI projections use only the current Plan and model time, never training facts.
export function planOverview(plan){
  return {visits:(plan?.routes||[]).reduce((n,r)=>n+r.stops.filter(s=>s.type==='VISIT').length,0),
    unassigned:plan?.unassigned?.length||0,pgp:new Set([...(plan?.pgp_groups||[]),...(plan?.incident_groups||[])].flatMap(g=>g.order_ids)).size};
}
export function projectDay(day,staff=[]){
  const assignments=new Map(),unassigned=new Map((day?.plan?.unassigned||[]).map(x=>[x.order_id,x]));
  const cancelled=new Map((day?.plan?.cancelled||[]).map(x=>[x.order_id,x])),groups=new Map();
  const transferred=new Set(),incidents=new Map();
  for(const [kind,items] of [['incident',day?.plan?.incident_groups||[]],['transfer',day?.plan?.pgp_groups||[]]])for(const g of items)for(const id of g.order_ids){groups.set(id,{...g,kind});if(kind==='incident')incidents.set(id,g);if(kind==='transfer')transferred.add(id);}
  for(const r of day?.plan?.routes||[]){let n=0;for(const stop of r.stops)if(stop.type==='VISIT')assignments.set(stop.order_id,{staff:r.staff_id,number:++n,stop});}
  const now=Date.parse(day?.model_now);const status=id=>{
    if(!day?.plan)return 'pending';if(cancelled.has(id))return 'cancelled';if(transferred.has(id))return 'pgp';
    const visit=assignments.get(id);if(!visit)return unassigned.has(id)?'unassigned':'unknown';
    return Date.parse(visit.stop.end)<=now?'completed':Date.parse(visit.stop.start)<=now?'active':'assigned';
  };
  const orderIds=new Set((day?.orders||[]).map(o=>o.order_id));
  const riskAlerts=new Map();
  for(const a of day?.plan?.alerts||[])if(a.type==='LATE_RISK'&&a.status==='ACTIVE'&&orderIds.has(a.order_id)&&!cancelled.has(a.order_id)&&!transferred.has(a.order_id)){
    if(!riskAlerts.has(a.order_id))riskAlerts.set(a.order_id,[]);riskAlerts.get(a.order_id).push(a);
  }
  const risks=new Set(riskAlerts.keys());
  const counts={all:day?.orders?.length||0,assigned:[...assignments.keys()].filter(id=>orderIds.has(id)&&!cancelled.has(id)&&!transferred.has(id)).length,unassigned:[...unassigned.keys()].filter(id=>orderIds.has(id)&&!cancelled.has(id)&&!transferred.has(id)).length,pgp:[...groups.keys()].filter(id=>orderIds.has(id)&&!cancelled.has(id)).length,cancelled:[...cancelled.keys()].filter(id=>orderIds.has(id)).length,risk:risks.size};
  const rows=(day?.plan?.routes||[]).map(route=>{
    const person=staff.find(s=>s.staff_id===route.staff_id);const blocks=[];
    for(let i=0;i<route.stops.length;i++){
      const s=route.stops[i],arrival=Date.parse(s.arrival),start=Date.parse(s.start),end=Date.parse(s.end);
      const previous=i?Date.parse(route.stops[i-1].end):arrival;
      const travel=Math.max(0,s.travel_sec||0)*1000,departure=arrival-travel;
      if(departure>previous)blocks.push({type:'WAIT',start:previous,end:departure,stop:s});
      if(travel)blocks.push({type:'TRAVEL',start:departure,end:arrival,stop:s});
      if(start>arrival)blocks.push({type:'WAIT',start:arrival,end:start,stop:s});
      if(end>start)blocks.push({type:s.type,start,end,stop:s});
    }
    const minutes=type=>blocks.filter(b=>b.type===type).reduce((sum,b)=>sum+(b.end-b.start)/60000,0);
    const shiftStart=Date.parse(`${day.date}T${(person?.shift_start||'09:00').slice(0,5)}:00+05:00`);
    const shiftEnd=Date.parse(`${day.date}T${(person?.shift_end||'21:00').slice(0,5)}:00+05:00`);
    const available=(shiftEnd-shiftStart)/60000-minutes('BREAK');
    return {route,person,blocks,shiftStart,shiftEnd,visits:route.stops.filter(s=>s.type==='VISIT').length,
      workMin:minutes('VISIT'),travelMin:minutes('TRAVEL'),waitMin:minutes('WAIT'),
      utilization:available>0?(minutes('VISIT')+minutes('TRAVEL'))/available:0};
  });
  return {assignments,unassigned,cancelled,groups,status,counts,rows,risks,riskAlerts,transferred,incidents};
}

export const statusLabels={pending:'План не построен',assigned:'Назначен',active:'В работе по плану',completed:'Завершён по плану',unassigned:'Не назначен',pgp:'Групповая проблема',cancelled:'Отменён',unknown:'Нет статуса в плане'};
export const actionLabels={RESCHEDULE:'Согласовать новый слот',REASSIGN:'Передать другому сотруднику',ESCALATE:'Решение диспетчера',TRANSFER_TO_STATION:'Передать в станционное подразделение',NONE:'Без действия',INDIVIDUAL_VISITS:'Индивидуальные выезды по заявкам'};

// Shared by list filters and map marker summaries.
export function matchesOrderStatus(view,id,filter='all'){
 if(filter==='all')return true;
 if(filter==='risk')return view.risks.has(id);
 if(filter==='pgp')return view.groups.has(id)&&!view.cancelled.has(id);
 if(filter==='assigned')return view.assignments.has(id)&&!['cancelled','pgp'].includes(view.status(id));
 return view.status(id)===filter;
}
export function markerSummary(orders,view){
 const counts={risk:0,pgp:0,cancelled:0};
 for(const o of orders)for(const key of Object.keys(counts))if(matchesOrderStatus(view,o.order_id,key))counts[key]++;
 const labels={risk:'Риск опоздания',pgp:'ПГП',cancelled:'Отменены'};
 return {counts,kind:counts.risk?'risk':counts.pgp?'pgp':counts.cancelled===orders.length&&orders.length?'cancelled':'normal',
   text:Object.entries(counts).filter(([,n])=>n).map(([k,n])=>`${labels[k]}: ${n}`).join(' · ')};
}

// One list drives the warnings panel and its indicator. Incident warnings are UI
// projections, not additional official Plan buckets or double-counted visits.
export function projectWarnings(day){
 const plan=day?.plan;if(!plan)return [];
 const alerts=(plan.alerts||[]).map(a=>({...a}));const view=projectDay(day);
 const byId=new Map((day.orders||[]).map(o=>[o.order_id,o]));
 const seen=new Set(alerts.filter(a=>a.group_id).map(a=>a.group_id));
 for(const [kind,items] of [['incident',plan.incident_groups||[]],['transfer',plan.pgp_groups||[]]])for(const g of items){
  if(seen.has(g.group_id))continue;
  const ids=g.order_ids.filter(id=>byId.has(id)&&!view.cancelled.has(id));if(!ids.length)continue;
  seen.add(g.group_id);
  const active=ids.some(id=>view.status(id)!=='completed');
  alerts.push({alert_id:`UI-GROUP-${g.group_id}`,type:kind==='incident'?'INCIDENT_GROUP':'PGP_DETECTED',
   group_id:g.group_id,status:active?'ACTIVE':'RESOLVED',created_at:g.detected_at,
   suggested_action:g.action,message:kind==='incident'?`Общая авария на ${g.access_node_id}: ${ids.length} нарядов. Выполнение — отдельными выездами.`:`ПГП на ${g.access_node_id}: ${ids.length} нарядов переданы в станционное подразделение.`});
 }
 return alerts;
}
