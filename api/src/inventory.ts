import type { FastifyInstance } from 'fastify';
import type { Store } from './store.js';
import { ApiError } from './errors.js';
const kinds=['ONT','ROUTER','STB'];
export function equipmentStart(input:any,worker:any){
  return {...(input._equipment_start_by_staff?.[worker.staff_id] ?? worker.equipment_start)};
}
export function validateInventoryOverrides(input:any,reference:any){
  if(input._equipment_start_by_staff===undefined)return;
  const overrides=input._equipment_start_by_staff;
  if(!overrides || typeof overrides!=='object' || Array.isArray(overrides))throw new ApiError(422,'INVALID_EQUIPMENT','Неверный комплект смены');
  for(const [id,counts] of Object.entries(overrides) as [string,any][]){
    const worker=reference.staff.find((w:any)=>w.staff_id===id);
    if(!worker)throw new ApiError(422,'UNKNOWN_STAFF',id);
    if(!counts || typeof counts!=='object' || Object.keys(counts).length!==3 || kinds.some(k=>!Number.isInteger(counts[k]) || counts[k]<0 || counts[k]>worker.equipment_capacity[k]))throw new ApiError(422,'INVALID_EQUIPMENT','Стартовый комплект должен помещаться в рюкзак');
  }
}
export function inventoryFor(input:any,plan:any,worker:any){
  const initial=equipmentStart(input,worker),current={...initial};
  for(const record of input._interrupted_visits ?? [])if(record.staff_id===worker.staff_id)
    for(const kind of kinds)current[kind]-=record.equipment_consumed[kind]??0;
  const route=plan?.routes.find((r:any)=>r.staff_id===worker.staff_id);
  const now=Date.parse(input.now);
  for(const stop of route?.stops ?? []){
    // A visit consumes its kit at start; a depot visit replenishes it at end.
    const effective=stop.type==='VISIT'?stop.start:stop.type==='RESTOCK'?stop.end:null;
    if(effective && Date.parse(effective)<=now)Object.assign(current,stop.equipment_after);
  }
  return {staff_id:worker.staff_id,display_name:worker.display_name,service_center_id:worker.service_center_id,
    initial,current,capacity:worker.equipment_capacity,
    restocks:(route?.stops ?? []).filter((s:any)=>s.type==='RESTOCK').map((s:any)=>({location_id:s.location_id,start:s.start,end:s.end,equipment_after:s.equipment_after}))};
}
export function registerInventory(app:FastifyInstance,store:Store){
  app.get<{Params:{date:string}}>('/api/ui/days/:date/inventory',async(request,reply)=>{
    reply.header('Cache-Control','no-store');
    return store.transact(async state=>{
      if(!state.reference)throw new ApiError(409,'REFERENCE_NOT_LOADED','Загрузите справочники');
      const date=request.params.date,day=state.days[date];
      const input=day?.input ?? {date,now:date+'T00:00:00+05:00'};
      return {date,model_now:input.now,editable:!day || (!day.events.length && !day.input.orders.length),staff:state.reference.staff.map((w:any)=>inventoryFor(input,day?.plan,w))};
    });
  });
  app.post<{Params:{date:string};Body:{staff_id:string;equipment_start:Record<string,number>}}>('/api/ui/days/:date/inventory',{
    schema:{params:{type:'object',required:['date'],properties:{date:{type:'string',format:'date'}}},body:{type:'object',additionalProperties:false,required:['staff_id','equipment_start'],properties:{staff_id:{type:'string'},equipment_start:{type:'object',additionalProperties:false,required:kinds,properties:Object.fromEntries(kinds.map(k=>[k,{type:'integer',minimum:0,maximum:10000}]))}}}},
  },async(request,reply)=>{
    reply.header('Cache-Control','no-store');
    return store.transact(async state=>{
      const worker=state.reference?.staff.find((w:any)=>w.staff_id===request.body.staff_id);
      if(!worker)throw new ApiError(422,'UNKNOWN_STAFF','Неизвестный сотрудник');
      for(const k of kinds)if(Number(request.body.equipment_start[k])>worker.equipment_capacity[k])throw new ApiError(422,'INVALID_EQUIPMENT','Начальный комплект превышает вместимость: '+k);
      const date=request.params.date,existing=state.days[date];
      if(existing && (existing.events.length || existing.input.orders.length))throw new ApiError(409,'SHIFT_ALREADY_USED','Стартовый комплект задаётся до заявок и событий. Выберите новую дату.');
      const day=existing ?? {input:{date,now:date+'T00:00:00+05:00',orders:[],absent_staff_ids:[]},events:[],event_results:{},plan:null};
      (day.input._equipment_start_by_staff ??= {})[worker.staff_id]={...request.body.equipment_start};
      day.plan=null;state.days[date]=day;
      return {date,staff_id:worker.staff_id,equipment_start:equipmentStart(day.input,worker)};
    });
  });
}
