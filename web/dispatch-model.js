// UI projections use only the current Plan and model time, never training facts.
export function planOverview(plan){
  return {visits:(plan?.routes||[]).reduce((n,r)=>n+r.stops.filter(s=>s.type==='VISIT').length,0),
    unassigned:plan?.unassigned?.length||0,pgp:(plan?.pgp_groups||[]).reduce((n,g)=>n+g.order_ids.length,0)};
}
export function projectDay(day,staff=[]){
  const assignments=new Map(),unassigned=new Map((day?.plan?.unassigned||[]).map(x=>[x.order_id,x]));
  const cancelled=new Map((day?.plan?.cancelled||[]).map(x=>[x.order_id,x])),groups=new Map();
  for(const g of day?.plan?.pgp_groups||[])for(const id of g.order_ids)groups.set(id,g);
  for(const r of day?.plan?.routes||[]){let n=0;for(const stop of r.stops)if(stop.type==='VISIT')assignments.set(stop.order_id,{staff:r.staff_id,number:++n,stop});}
  const now=Date.parse(day?.model_now);const status=id=>{
    if(!day?.plan)return 'pending';if(cancelled.has(id))return 'cancelled';if(groups.has(id))return 'pgp';
    const visit=assignments.get(id);if(!visit)return unassigned.has(id)?'unassigned':'unknown';
    return Date.parse(visit.stop.end)<=now?'completed':Date.parse(visit.stop.start)<=now?'active':'assigned';
  };
  const orderIds=new Set((day?.orders||[]).map(o=>o.order_id));
  const riskAlerts=new Map();
  for(const a of day?.plan?.alerts||[])if(a.type==='LATE_RISK'&&a.status==='ACTIVE'&&orderIds.has(a.order_id)&&!cancelled.has(a.order_id)&&!groups.has(a.order_id)){
    if(!riskAlerts.has(a.order_id))riskAlerts.set(a.order_id,[]);riskAlerts.get(a.order_id).push(a);
  }
  const risks=new Set(riskAlerts.keys());
  const counts={all:day?.orders?.length||0,assigned:[...assignments.keys()].filter(id=>orderIds.has(id)&&!cancelled.has(id)&&!groups.has(id)).length,unassigned:[...unassigned.keys()].filter(id=>orderIds.has(id)&&!cancelled.has(id)&&!groups.has(id)).length,pgp:[...groups.keys()].filter(id=>orderIds.has(id)&&!cancelled.has(id)).length,cancelled:[...cancelled.keys()].filter(id=>orderIds.has(id)).length,risk:risks.size};
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
  return {assignments,unassigned,cancelled,groups,status,counts,rows,risks,riskAlerts};
}

export const statusLabels={pending:'План не построен',assigned:'Назначен',active:'В работе по плану',completed:'Завершён по плану',unassigned:'Не назначен',pgp:'Групповая проблема',cancelled:'Отменён',unknown:'Нет статуса в плане'};
export const actionLabels={RESCHEDULE:'Согласовать новый слот',REASSIGN:'Передать другому сотруднику',ESCALATE:'Решение диспетчера',TRANSFER_TO_STATION:'Передать в станционное подразделение',NONE:'Без действия'};

// Shared by list filters and map marker summaries.
export function matchesOrderStatus(view,id,filter='all'){
 if(filter==='all')return true;
 if(filter==='risk')return view.risks.has(id);
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
