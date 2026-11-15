import { Ajv } from 'ajv';
import addFormats from 'ajv-formats';
import type { FastifyInstance } from 'fastify';
import { ApiError } from './errors.js';
import { definitions, schemaRef } from './openapi.js';
import type { Store, Document } from './store.js';
import type { Planner } from './planning.js';
import {equipmentStart,validateInventoryOverrides} from './inventory.js';
const fail = (code: string, message: string, status = 422): never => { throw new ApiError(status, code, message); };
const unique = (items: any[], key: string) => {
  const ids = items.map(x => x[key]);
  if (new Set(ids).size !== ids.length) fail('DUPLICATE_ID', `Duplicate ${key}`);
};
function validateReference(r: any) {
  for (const [list, key] of [['staff','staff_id'],['service_centers','service_center_id'],['access_nodes','access_node_id'],['work_types','code']]) unique(r[list!], key!);
  const centers = new Set(r.service_centers.map((c: any) => c.service_center_id));
  for (const worker of r.staff) {
    if (!centers.has(worker.service_center_id)) fail('UNKNOWN_SERVICE_CENTER', worker.service_center_id);
    for (const [kind, count] of Object.entries(worker.equipment_start)) {
      if (Number(count) > (worker.equipment_capacity[kind] ?? 0)) fail('INVALID_EQUIPMENT', 'Start exceeds capacity');
    }
  }
  const buildings = r.access_nodes.flatMap((n: any) => n.buildings);
  unique(buildings, 'building_id');
  for (const building of buildings) if (building.zone_service_center_id !== undefined && !centers.has(building.zone_service_center_id)) fail('UNKNOWN_SERVICE_CENTER', building.zone_service_center_id);
}
function validateMatrix(m: any, reference?: any) {
  const size = m.points.length;
  for (const key of ['durations_sec','distances_m']) {
    if (m[key].length !== size || m[key].some((row: any[], i: number) => row.length !== size || row[i] !== 0)) fail('INVALID_MATRIX', `${key} must be NxN with zero diagonal`);
  }
  if (reference) {
    const points = new Set(m.points);
    for (const id of [...reference.service_centers.map((c: any) => c.service_center_id), ...reference.access_nodes.flatMap((n: any) => n.buildings.map((b: any) => b.building_id))]) {
      if (!points.has(id)) fail('INVALID_MATRIX', `Missing point ${id}`);
    }
  }
}
function validateOrder(o: any, reference: any, date: string, now: string) {
  if (!reference.work_types.some((w: any) => w.code === o.work_type_code)) fail('UNKNOWN_WORK_TYPE', o.work_type_code);
  if(o._test_staff_id !== undefined) {
    const person=reference.staff.find((p:any)=>p.staff_id===o._test_staff_id);
    const work=reference.work_types.find((w:any)=>w.code===o.work_type_code);
    if(!person)fail('UNKNOWN_STAFF','Selected test employee does not exist');
    if(!person.profiles.some((profile:string)=>work.profiles.includes(profile)))fail('STAFF_NOT_QUALIFIED','У сотрудника нет нужного профиля: '+work.profiles.map((p:string)=>p==='INSTALL'?'инсталляция':'3ЛТП').join(' или '));
    if(!person.technologies.includes(o.technology))fail('STAFF_NOT_QUALIFIED','Сотрудник не обучен технологии '+o.technology);
    if(o.requires_height && !person.height_permit)fail('STAFF_NOT_QUALIFIED','У сотрудника нет допуска к работам на высоте');
    if(Object.entries(o.required_equipment).some(([kind,count])=>Number(count)>(person.equipment_capacity[kind] ?? 0)))fail('NO_EQUIPMENT','Equipment demand exceeds selected employee capacity');
  }
  const node = reference.access_nodes.find((n: any) => n.access_node_id === o.access_node_id);
  if (!node?.buildings.some((b: any) => b.building_id === o.building_id)) fail('UNKNOWN_BUILDING', o.building_id);
  if (new Date(Date.parse(o.slot.start) + 5 * 60 * 60 * 1000).toISOString().slice(0,10) !== date || Date.parse(o.registered_at) > Date.parse(now)) fail('INVALID_ORDER_TIME', o.order_id);
  if (Date.parse(o.slot.start) > Date.parse(o.latest_start) || Date.parse(o.latest_start) > Date.parse(o.slot.end) || Date.parse(o.slot.start) >= Date.parse(o.slot.end)) fail('INVALID_SLOT', o.order_id);
}
function requireDay(state: Document, date: string) {
  const day = state.days[date];
  if (!day) fail('DAY_NOT_FOUND', date, 404);
  return day;
}
function applyEvent(day: any, e: any, reference: any) {
  const order = day.input.orders.find((o: any) => o.order_id === e.order_id);
  const staff = reference.staff.find((s: any) => s.staff_id === e.staff_id);
  if (e.order_id && !order) fail('UNKNOWN_ORDER', e.order_id);
  if (e.staff_id && !staff) fail('UNKNOWN_STAFF', e.staff_id);
  const stop = day.plan.routes.find((r: any) => r.staff_id === e.staff_id)?.stops.find((s: any) => s.order_id === e.order_id && s.type === 'VISIT');
  if (['VISIT_DELAYED','ORDER_TRANSFERRED'].includes(e.type)) {
    if (!stop || Date.parse(stop.start) > Date.parse(e.timestamp) || Date.parse(stop.end) <= Date.parse(e.timestamp)) fail('INVALID_VISIT_STATE', 'Visit is not in progress');
    if (e.type === 'VISIT_DELAYED' && Date.parse(e.expected_end) <= Date.parse(stop.end)) fail('INVALID_EXPECTED_END', 'Expected end must be later');
    if (e.type === 'ORDER_TRANSFERRED' && (Date.parse(e.actual_end) < Date.parse(stop.start) || Date.parse(e.actual_end) > Date.parse(e.timestamp))) fail('INVALID_ACTUAL_END', 'Actual end is outside visit interval');
  }
  if (e.type === 'NEW_ORDER') {
    if (day.input.orders.some((o: any) => o.order_id === e.order.order_id)) fail('DUPLICATE_ORDER', e.order.order_id);
    validateOrder(e.order, reference, day.input.date, e.timestamp);
    day.input.orders.push(e.order);
  }
  if (e.type === 'STAFF_UNAVAILABLE') {
    const route=day.plan.routes.find((r:any)=>r.staff_id===e.staff_id);
    for (const visit of route?.stops ?? []) {
      if(visit.type!=='VISIT' || Date.parse(visit.start)>Date.parse(e.timestamp) || Date.parse(visit.end)<=Date.parse(e.timestamp))continue;
      const interrupted=day.input.orders.find((o:any)=>o.order_id===visit.order_id);
      const consumed={...(interrupted._remaining_equipment ?? interrupted.required_equipment)};
      (day.input._interrupted_visits ??= []).push({staff_id:e.staff_id,order_id:visit.order_id,start:visit.start,interrupted_at:e.timestamp,planned_end:visit.end,equipment_consumed:consumed});
      interrupted._remaining_duration_sec=Math.max(1,Math.round((Date.parse(visit.end)-Date.parse(e.timestamp))/1000));
      interrupted._remaining_equipment={ONT:0,ROUTER:0,STB:0};
    }
  }
  if (e.type === 'STAFF_UNAVAILABLE' && e.until && Date.parse(e.until) <= Date.parse(e.timestamp)) fail('INVALID_UNAVAILABLE_INTERVAL', 'until must be after timestamp');
  day.input.now = e.timestamp;
  day.events.push(e);
}
export function registerOfficialApi(app: FastifyInstance, store: Store, planner: Planner) {
  for (const schema of Object.values(definitions)) app.addSchema(schema);
  const validator = new Ajv({strict:false});
  (addFormats as any)(validator);
  for (const schema of Object.values(definitions)) validator.addSchema(schema);
  app.addHook('preValidation', async request => {
    if (request.method === 'POST' && request.url.endsWith('/plan') && request.body === undefined) request.body = {};
  });
  const params = { type:'object', required:['date'], properties:{date:{type:'string',format:'date'}} };
  const response = (name: string) => ({200:schemaRef(name)});
  app.get('/api/v1/health', {schema:{response:response('Health')}}, async () => store.transact(async () => ({status:'ok', version:'0.2.0'})));
  app.put('/api/v1/reference', {schema:{body:schemaRef('ReferenceData'),response:response('LoadResult')}}, async request => store.transact(async state => {
    const r: any = request.body; validateReference(r);
    if (state.matrix) validateMatrix(state.matrix, r);
    state.reference = r; state.days = {};
    return {status:'loaded',counts:{staff:r.staff.length,service_centers:r.service_centers.length,access_nodes:r.access_nodes.length,buildings:r.access_nodes.reduce((n:number,x:any)=>n+x.buildings.length,0),work_types:r.work_types.length}};
  }));
  app.put('/api/v1/reference/travel-matrix', {schema:{body:schemaRef('TravelMatrix'),response:response('LoadResult')}}, async request => store.transact(async state => {
    const m:any=request.body; validateMatrix(m,state.reference); state.matrix=m;
    return {status:'loaded',counts:{points:m.points.length}};
  }));
  app.put<{Params:{date:string}}>('/api/v1/days/:date', {schema:{params,body:schemaRef('DayInput'),response:response('LoadResult')}}, async request => store.transact(async state => {
    if (!state.reference) fail('REFERENCE_NOT_LOADED','Load reference first',409);
    const d:any=request.body;
    validateInventoryOverrides(d,state.reference);
    if (d.date !== request.params.date) fail('DATE_MISMATCH','Body and path dates differ');
    unique(d.orders,'order_id');
    for (const o of d.orders) validateOrder(o,state.reference,d.date,d.now);
    for (const id of d.absent_staff_ids ?? []) if (!state.reference.staff.some((w:any)=>w.staff_id===id)) fail('UNKNOWN_STAFF',id);
    state.days[d.date]={input:d,events:[],event_results:{},plan:null};
    return {status:'loaded',counts:{orders:d.orders.length}};
  }));
  async function calculate(state:Document,day:any,event:any,timeout:number) {
    const started=performance.now();
    validateInventoryOverrides(day.input,state.reference);
    const plan=await planner({reference:state.reference,matrix:state.matrix,day:structuredClone(day.input),previous_plan:structuredClone(day.plan),event,calendar:structuredClone(state.days)},timeout);
    for(const update of plan._order_updates ?? []) {
      const order=day.input.orders.find((o:any)=>o.order_id===update.order_id);
      if(!order)fail('INVALID_PLANNER_RESPONSE','Reschedule refers to an unknown order',502);
      const candidate={...order,slot:update.slot,latest_start:update.latest_start};
      const validateOrderSchema=validator.getSchema('urn:dispatch:Order');
      if(!validateOrderSchema?.(candidate))fail('INVALID_PLANNER_RESPONSE','Invalid rescheduled order',502);
      validateOrder(candidate,state.reference,day.input.date,day.input.now);
      if(Date.parse(candidate.slot.start)<Date.parse(day.input.now))fail('INVALID_PLANNER_RESPONSE','Reschedule is outside allowed time',502);
      order.slot=update.slot;order.latest_start=update.latest_start;
    }
    for(const transfer of plan._future_transfers ?? []) {
      const source=day.input.orders.find((o:any)=>o.order_id===transfer.order_id);
      const date=transfer.to_date;
      if(!source || !/^\d{4}-\d{2}-\d{2}$/.test(date) || date<=day.input.date)fail('INVALID_PLANNER_RESPONSE','Invalid future transfer',502);
      const target=state.days[date];
      if(target?.events.length)fail('INVALID_PLANNER_RESPONSE','Cannot change a day already processing events',502);
      const input=transfer.target_input,result=transfer.target_plan;
      if(input.date!==date || !validator.getSchema('urn:dispatch:DayInput')?.(input) || !validator.getSchema('urn:dispatch:Plan')?.(result))fail('INVALID_PLANNER_RESPONSE','Invalid destination day',502);
      for(const order of input.orders)validateOrder(order,state.reference,date,input.now);
      const destination=input.orders.find((o:any)=>o.order_id===source.order_id);
      if(!destination || Date.parse(destination.deadline)!==Date.parse(source.deadline))fail('INVALID_PLANNER_RESPONSE','Transfer changed deadline',502);
      const expected=input.orders.map((o:any)=>o.order_id);
      const accounted=[...result.routes.flatMap((r:any)=>r.stops.filter((s:any)=>s.type==='VISIT').map((s:any)=>s.order_id)),...result.unassigned.map((o:any)=>o.order_id),...result.cancelled.map((o:any)=>o.order_id),...result.pgp_groups.flatMap((g:any)=>g.order_ids)];
      if(new Set(accounted).size!==accounted.length || accounted.length!==expected.length || expected.some((id:string)=>!accounted.includes(id)))fail('INVALID_PLANNER_RESPONSE','Destination accounting mismatch',502);
      for(const route of result.routes) {
        let stock=equipmentStart(input,state.reference.staff.find((w:any)=>w.staff_id===route.staff_id));
        for(let i=0;i<route.stops.length;i++) {
          const stop=route.stops[i],prior=route.stops[i-1],from=prior?state.matrix.points.indexOf(prior.location_id):-1,to=state.matrix.points.indexOf(stop.location_id);
          stop.travel_sec=from<0?0:state.matrix.durations_sec[from][to];stop.distance_m=from<0?0:state.matrix.distances_m[from][to];
          if(stop.type==='RESTOCK')stock={...state.reference.staff.find((w:any)=>w.staff_id===route.staff_id).equipment_capacity};
          if(stop.type==='VISIT'){const o=input.orders.find((o:any)=>o.order_id===stop.order_id);for(const [kind,count] of Object.entries(o._remaining_equipment ?? o.required_equipment))stock[kind]=(stock[kind] ?? 0)-Number(count);}
          stop.equipment_after={...stock};
        if(stop.type==='VISIT'){const order=(input?.orders ?? day.input.orders).find((o:any)=>o.order_id===stop.order_id);if(order)stop.deadline_missed=Date.parse(stop.end)>Date.parse(order.deadline);}
        }
      }
      result.based_on_event_id=event?.event_id ?? null;
      state.days[date]={input,plan:result,events:target?.events ?? [],event_results:target?.event_results ?? {}};
      day.input.orders=day.input.orders.filter((o:any)=>o.order_id!==source.order_id);
    }
    delete plan._future_transfers;
    delete plan._order_updates;
    plan.date=day.input.date; plan.as_of=day.input.now; plan.plan_version=event ? day.plan.plan_version+1 : 1;
    plan.based_on_event_id=event?.event_id ?? null; plan.computation_ms=Math.round(performance.now()-started);
    for (const route of plan.routes ?? []) {
      const worker=state.reference.staff.find((w:any)=>w.staff_id===route.staff_id);
      const stock=equipmentStart(day.input,worker);
      for(const record of day.input._interrupted_visits ?? [])if(record.staff_id===route.staff_id)for(const [kind,count] of Object.entries(record.equipment_consumed))stock[kind]=(stock[kind] ?? 0)-Number(count);
      for (let i=0;i<route.stops.length;i++) {
        const stop=route.stops[i],prior=route.stops[i-1];
        const from=prior ? state.matrix.points.indexOf(prior.location_id) : -1,to=state.matrix.points.indexOf(stop.location_id);
        stop.travel_sec=from<0?0:state.matrix.durations_sec[from][to];
        stop.distance_m=from<0?0:state.matrix.distances_m[from][to];
        if(stop.type==='RESTOCK') Object.assign(stock,worker.equipment_capacity);
        if(stop.type==='VISIT') {const order=day.input.orders.find((o:any)=>o.order_id===stop.order_id);for(const [kind,count] of Object.entries(order?._remaining_equipment ?? order?.required_equipment ?? {}))stock[kind]=(stock[kind] ?? 0)-Number(count);}
        stop.equipment_after={...stock};
        if(stop.type==='VISIT'){const order=day.input.orders.find((o:any)=>o.order_id===stop.order_id);if(order)stop.deadline_missed=Date.parse(stop.end)>Date.parse(order.deadline);}
      }
    }
    const validate=validator.getSchema('urn:dispatch:Plan');
    if (!validate?.(plan)) fail('INVALID_PLANNER_RESPONSE','Planner result does not match Plan schema',502);
    const visits=plan.routes.flatMap((r:any)=>r.stops.filter((s:any)=>s.type==='VISIT').map((s:any)=>s.order_id));
    const accounted=[...visits,...plan.unassigned.map((o:any)=>o.order_id),...plan.cancelled.map((o:any)=>o.order_id),...plan.pgp_groups.flatMap((g:any)=>g.order_ids)];
    const expected=day.input.orders.map((o:any)=>o.order_id);
    if (new Set(accounted).size!==accounted.length || accounted.length!==expected.length || expected.some((id:string)=>!accounted.includes(id))) fail('INVALID_PLANNER_RESPONSE','Plan must account for each order exactly once',502);
    if (event && day.plan) {
      for (const oldRoute of day.plan.routes) {
        const next=plan.routes.find((r:any)=>r.staff_id===oldRoute.staff_id);
        for (const old of oldRoute.stops.filter((s:any)=>Date.parse(s.start)<Date.parse(event.timestamp))) {
          if(event.type==='STAFF_UNAVAILABLE' && oldRoute.staff_id===event.staff_id && old.type==='VISIT' && Date.parse(old.end)>Date.parse(event.timestamp))continue;
          const retained=next?.stops.find((s:any)=>s.type===old.type && s.order_id===old.order_id && s.start===old.start);
          const changedEnd=old.type==='VISIT' && old.order_id===event.order_id && oldRoute.staff_id===event.staff_id && ['VISIT_DELAYED','ORDER_TRANSFERRED'].includes(event.type);
          if (!retained || retained.location_id!==old.location_id || retained.arrival!==old.arrival || (!changedEnd && retained.end!==old.end)) fail('INVALID_PLANNER_RESPONSE','Started stop was changed',502);
          if (changedEnd && retained.end!==(event.expected_end ?? event.actual_end)) fail('INVALID_PLANNER_RESPONSE','Event end was not applied',502);
        }
      }
    }
    plan.interrupted_visits=day.input._interrupted_visits ?? [];
    day.plan=plan; return plan;
  }
  app.post<{Params:{date:string};Body:{time_limit_sec?:number}}>('/api/v1/days/:date/plan', {schema:{params,body:schemaRef('PlanRequest'),response:response('Plan')}}, async request => store.transact(async state => {
    const day=requireDay(state,request.params.date);
    if (!state.matrix) fail('MATRIX_NOT_LOADED','Load travel matrix first',409);
    if (day.events.length) fail('PLAN_ALREADY_UPDATED','Initial plan cannot be rebuilt after events',409);
    return calculate(state,day,null,(request.body?.time_limit_sec ?? 300)*1000);
  }));
  app.get<{Params:{date:string}}>('/api/v1/days/:date/plan', {schema:{params,response:response('Plan')}}, async request => store.transact(async state => {
    const day=requireDay(state,request.params.date);
    if (!day.plan) fail('PLAN_NOT_FOUND','Build initial plan first',404);
    return day.plan;
  }));
  app.post<{Params:{date:string}}>('/api/v1/days/:date/events', {schema:{params,body:schemaRef('Event'),response:response('EventResult')}}, async request => store.transact(async state => {
    const started=performance.now(), day=requireDay(state,request.params.date), e:any=request.body;
    if (!day.plan) fail('PLAN_NOT_FOUND','Build initial plan first',404);
    if (Object.hasOwn(day.event_results, e.event_id)) return {...day.event_results[e.event_id],duplicate:true};
    if(e.type==='NEW_ORDER' && (Object.values(state.days) as any[]).some(d=>d.input.orders.some((o:any)=>o.order_id===e.order.order_id) || d.events.some((prior:any)=>prior.type==='NEW_ORDER' && prior.order.order_id===e.order.order_id) || d.plan?.transferred_orders?.some((t:any)=>t.order_id===e.order.order_id)))fail('DUPLICATE_ORDER',e.order.order_id);
    if (Date.parse(e.timestamp)<Date.parse(day.input.now)) fail('EVENT_OUT_OF_ORDER','Event timestamp precedes model time',409);
    applyEvent(day,e,state.reference);
    const prior=day.plan;
    const plan=await calculate(state,day,e,9000);
    const result={event_id:e.event_id,accepted:true,duplicate:false,plan_version:plan.plan_version,as_of:plan.as_of,processing_ms:Math.round(performance.now()-started),changed_staff_ids:plan.routes.filter((r:any)=>JSON.stringify(r)!==JSON.stringify(prior.routes.find((p:any)=>p.staff_id===r.staff_id))).map((r:any)=>r.staff_id),new_alerts:plan.alerts.filter((a:any)=>!prior.alerts.some((p:any)=>p.alert_id===a.alert_id))};
    Object.defineProperty(day.event_results,e.event_id,{value:result,enumerable:true,writable:true,configurable:true});
    return result;
  }));
}










