import type { FastifyInstance } from 'fastify';
import { readFile } from 'node:fs/promises';
import { resolve, sep, extname } from 'node:path';
import type { Store } from './store.js';
import { ApiError } from './errors.js';
import { registerInventory,inventoryFor } from './inventory.js';
export function registerUi(app:FastifyInstance,store:Store) {
  registerInventory(app,store);
  const root=resolve(process.env.WEB_ROOT ?? '../web');
  async function asset(file:string,reply:any) {
    const path=resolve(root,file);
    if(path!==root && !path.startsWith(root+sep)) throw new ApiError(404,'NOT_FOUND','Asset not found');
    const mime:Record<string,string>={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png','.svg':'image/svg+xml'};
    try {return reply.header('Cache-Control','no-cache').type(mime[extname(path)] ?? 'application/octet-stream').send(await readFile(path));}
    catch {throw new ApiError(404,'NOT_FOUND','Asset not found');}
  }
  app.get('/',async (_request,reply)=>asset('index.html',reply));
  app.get<{Params:{'*':string}}>('/static/*',async (request,reply)=>asset(request.params['*'],reply));
  app.get('/api/ui/catalog',async (_request,reply)=>{
    reply.header('Cache-Control','no-store');
    return store.transact(async state=>({
      buildings:(state.reference?.access_nodes ?? []).flatMap((n:any)=>n.buildings.map((b:any)=>({...b,access_node_id:n.access_node_id,technology:n.technology}))),
      works:state.reference?.work_types ?? [],staff:state.reference?.staff ?? [],
    }));
  });
  app.get('/api/ui/bootstrap',async (_request,reply)=>{
    reply.header('Cache-Control','no-store');
    return store.transact(async state=>({data_source:'postgres',days:Object.values(state.days).map((d:any)=>({date:d.input.date,model_now:d.input.now,orders_count:d.input.orders.length})),service_centers:state.reference?.service_centers ?? [],staff:(state.reference?.staff ?? []).map((s:any)=>({...s,shift_start:s.shift.start,shift_end:s.shift.end})),work_types:state.reference?.work_types ?? []}));
  });
  app.get<{Params:{date:string;request:string}}>('/api/ui/days/:date/debug-orders/:request',async (request,reply)=>{
    reply.header('Cache-Control','no-store');
    return store.transact(async state=>{
      const day=state.days[request.params.date];if(!day)throw new ApiError(404,'DAY_NOT_LOADED','Day not loaded');
      const prior=day.events.find((e:any)=>e.type==='NEW_ORDER' && e.event_id==='LOCAL-'+request.params.request);
      const prefix='ORD-'+request.params.date.replaceAll('-','')+'-';
      const used=new Set<string>();
      for(const d of Object.values(state.days) as any[]) {
        for(const o of d.input.orders)if(o.order_id.startsWith(prefix))used.add(o.order_id);
        for(const e of d.events)if(e.type==='NEW_ORDER' && e.order.order_id.startsWith(prefix))used.add(e.order.order_id);
        for(const t of d.plan?.transferred_orders ?? [])if(t.order_id.startsWith(prefix))used.add(t.order_id);
      }
      return {order_id:prior?.order.order_id ?? null,used_order_ids:[...used]};
    });
  });
  app.get<{Params:{date:string}}>('/api/ui/days/:date',async (request,reply)=>{
    reply.header('Cache-Control','no-store');
    return store.transact(async state=>{
      const d=state.days[request.params.date];if(!d)throw new ApiError(404,'DAY_NOT_LOADED','Day not loaded');
      return {data_source:'postgres',date:d.input.date,model_now:d.input.now,orders:d.input.orders.map((o:any)=>({...o,slot_start:o.slot.start,slot_end:o.slot.end})),plan:d.plan,inventory:state.reference.staff.map((w:any)=>inventoryFor(d.input,d.plan,w))};
    });
  });
  app.get<{Params:{date:string;staff:string}}>('/api/ui/days/:date/routes/:staff/geometry',async request=>{
    const {route,points,version}=await store.transact(async state=>{
      const d=state.days[request.params.date];if(!d?.plan)throw new ApiError(404,'PLAN_NOT_FOUND','Plan not built');
      const route=d.plan.routes.find((r:any)=>r.staff_id===request.params.staff);if(!route)throw new ApiError(404,'UNKNOWN_STAFF','Route not found');
      const points=new Map<string,number[]>();for(const c of state.reference.service_centers)points.set(c.service_center_id,[c.lon,c.lat]);
      for(const n of state.reference.access_nodes)for(const b of n.buildings)points.set(b.building_id,[b.lon,b.lat]);
      return {route,points,version:d.plan.plan_version};
    });
    const coordinates:number[][]=[],labels:string[]=[];let visit=0;
    for(const stop of route.stops){if(stop.type==='BREAK')continue;const point=points.get(stop.location_id);if(!point)throw new ApiError(502,'ROUTING_UNAVAILABLE','Unknown location');const label=stop.type==='VISIT'?String(++visit):'СЦ';if(JSON.stringify(coordinates.at(-1))===JSON.stringify(point)){labels[labels.length-1]=label;}else{coordinates.push(point);labels.push(label);}}
    if(coordinates.length<2)return {staff_id:request.params.staff,plan_version:version,geometry:{type:'LineString',coordinates:[]},segments:[]};
    try {
      const base=process.env.OSRM_URL ?? 'https://router.project-osrm.org';
      const response=await fetch(`${base}/route/v1/driving/${coordinates.map(p=>p.join(',')).join(';')}?overview=full&geometries=geojson&steps=true`,{signal:AbortSignal.timeout(5000)});
      if(!response.ok)throw new Error('Routing failed');const data:any=await response.json();if(data.code!=='Ok')throw new Error('No route');
      const r=data.routes[0];return {staff_id:request.params.staff,plan_version:version,geometry:r.geometry,segments:r.legs.map((leg:any,i:number)=>({from_stop:labels[i],to_stop:labels[i+1],geometry:{type:'LineString',coordinates:leg.steps.flatMap((s:any)=>s.geometry.coordinates)}}))};
    }catch{throw new ApiError(502,'ROUTING_UNAVAILABLE','Road geometry unavailable; plan is unchanged');}
  });
}
