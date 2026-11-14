import {createEventId} from './uuid.js';
import {projectDay,planOverview,statusLabels,actionLabels} from './dispatch-model.js';
import {createDispatcher} from './dispatcher-view.js';
const $=id=>document.getElementById(id);
const state={ref:null,day:null,tab:'orders',selected:null,request:0,markers:new Map(),geometryRequest:0,status:'all',view:null};
const techColors={PON:'#df8b4e',FTTB:'#6d58ae',XDSL:'#548f8b',DOCSIS:'#bd7897'};
const time=value=>new Intl.DateTimeFormat('ru-RU',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Yekaterinburg'}).format(new Date(value));
const dateLabel=value=>new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long',year:'numeric',timeZone:'Asia/Yekaterinburg'}).format(new Date(value+'T12:00:00+05:00'));
function node(tag,className,text){const e=document.createElement(tag);if(className)e.className=className;if(text!==undefined)e.textContent=text;return e;}
function error(message){$('error').textContent=message;$('error').hidden=!message;}
async function get(url){
  const response=await fetch(url,{headers:{Accept:'application/json'},cache:'no-store'});
  const body=await response.json();
  if(!response.ok)throw new Error(body.error?.message||'Не удалось загрузить данные.');
  return body;
}
let map,ordersLayer,centersLayer;
function setupMap(){
  if(!window.L){error('Не удалось загрузить библиотеку карты. Обновите страницу.');return;}
  map=L.map('map',{zoomControl:false}).setView([56.849,60.605],12);
  L.control.zoom({position:'bottomright'}).addTo(map);
  const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{
    maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(map);
  let failed=0;tiles.on('tileerror',()=>{if(++failed>=3)$('tiles-warning').hidden=false;});
  tiles.on('tileload',()=>{$('tiles-warning').hidden=true;failed=0;});
  ordersLayer=L.layerGroup().addTo(map);centersLayer=L.layerGroup().addTo(map);
}
function popup(title,subtitle,buttonLabel,action){
  const box=node('div');box.append(node('strong','',title),node('div','',subtitle));
  if(buttonLabel){const b=node('button','popup-action',buttonLabel);b.addEventListener('click',action);box.append(b);}
  return box;
}
function renderCenters(){
  if(!map)return;centersLayer.clearLayers();
  for(const c of state.ref.service_centers){
    L.marker([c.lat,c.lon],{icon:L.divIcon({className:'depot-icon',html:'⌂',iconSize:[27,27],iconAnchor:[13,13]}),zIndexOffset:500})
      .addTo(centersLayer).bindPopup(popup(c.name,c.address));
  }
}
function filteredOrders(){
  const query=$('search').value.trim().toLocaleLowerCase('ru');const tech=$('technology').value;const profile=$('profile').value;
  return (state.day?.orders||[]).filter(o=>(state.status==='all'||(state.status==='risk'?state.view.risks.has(o.order_id):state.status==='assigned'?state.view.assignments.has(o.order_id):state.view.status(o.order_id)===state.status))&&(!tech||o.technology===tech)&&(!profile||work(o).profiles.includes(profile))&&
    (!query||[o.order_id,o.building_id,o.address,o.access_node_id].some(v=>v.toLocaleLowerCase('ru').includes(query))));
}
function filteredStaff(){
  const query=$('search').value.trim().toLocaleLowerCase('ru');const tech=$('technology').value;const profile=$('profile').value;
  return (state.ref?.staff||[]).filter(p=>(!tech||p.technologies.includes(tech))&&(!profile||p.profiles.includes(profile))&&
    (!query||[p.staff_id,p.display_name||'',p.service_center_id].some(v=>v.toLocaleLowerCase('ru').includes(query))));
}
function work(order){return state.ref.work_types.find(w=>w.code===order.work_type_code)||{name:order.work_type_code,duration_min:0,profiles:[]};}
function fit(){
  if(!map)return;const points=state.ref?.service_centers.map(c=>[c.lat,c.lon])||[];
  for(const o of filteredOrders())points.push([o.lat,o.lon]);
  if(points.length)map.fitBounds(L.latLngBounds(points),{padding:[45,65],maxZoom:14});
}
function renderMarkers(orders){
  if(!map)return;ordersLayer.clearLayers();state.markers.clear();
  const groups=new Map();for(const o of orders){if(!groups.has(o.building_id))groups.set(o.building_id,[]);groups.get(o.building_id).push(o);}
  $('map-count').textContent=`${groups.size} адресов`;
  for(const [id,group] of groups){
    const o=group[0];const repeated=group.some(o=>o.is_repeat);const focused=group.some(o=>o.order_id===state.selected);
    const marker=L.marker([o.lat,o.lon],{title:`${o.address}: ${group.length} нарядов`,
      icon:L.divIcon({className:`order-icon${repeated?' repeat':''}${focused?' focused':''}`,html:String(group.length),iconSize:[23,23],iconAnchor:[11,11]})}).addTo(ordersLayer);
    marker.bindPopup(popup(o.address,`${id} · ${group.length} нарядов`,group.length===1?'Открыть наряд':'Показать наряды дома',()=>{
      if(group.length===1)selectOrder(o);
      else {$('search').value=id;setTab('orders');render();map.closePopup();}
    }));state.markers.set(id,marker);
  }
}
function orderCard(order){
  const w=work(order);const card=node('button',`order-card${state.selected===order.order_id?' chosen':''}`);card.type='button';
  const top=node('div','card-top');top.append(node('span','order-id',order.order_id),node('span','tech-chip',order.technology));
  const bottom=node('div','card-bottom');bottom.append(node('span','time-tag',`${time(order.slot_start)} — ${time(order.slot_end)}`),node('span','',`${w.duration_min} мин`));
  if(order.is_repeat)bottom.append(node('span','repeat-tag','↺ Повтор'));
  if(order.requires_height)bottom.append(node('span','height-tag','△ Высота'));
  card.append(top,node('h3','',order.address),node('div','card-work',w.name),bottom);
  const assignment=assigned(order.order_id);
  if(assignment)card.append(node('div','assignment',`${assignment.staff} · визит ${assignment.number} · ${time(assignment.stop.start)}`));
  const status=state.view.status(order.order_id);card.append(node('span',`status-tag status-${status}`,statusLabels[status]));
  const reason=state.view.unassigned.get(order.order_id);if(reason)card.append(node('div','reason-preview',reason.reason_text));
  if(state.view.risks.has(order.order_id))card.append(node('span','risk-badge','Риск опоздания'));
  card.addEventListener('click',()=>selectOrder(order));return card;
}
function staffCard(person){
  const card=node('button','order-card staff-card');const top=node('div','card-top');
  top.append(node('span','order-id',person.staff_id),node('span','tech-chip',person.profiles.map(p=>p==='LTP3'?'3ЛТП':'Инсталляция').join(' / ')));
  card.append(top,node('h3','',person.display_name||person.staff_id),node('div','card-work',`${person.technologies.join(' · ')}${person.height_permit?' · Допуск к высоте':''}`));
  const bottom=node('div','card-bottom');bottom.append(node('span','time-tag',`${person.shift_start.slice(0,5)} — ${person.shift_end.slice(0,5)}`),node('span','',person.service_center_id));card.append(bottom);
  const workload=state.view?.rows.find(r=>r.route.staff_id===person.staff_id);
  if(workload)card.append(node('div','staff-workload',`${workload.visits} визитов · работы ${Math.round(workload.workMin)} мин · дорога ${Math.round(workload.travelMin)} мин`));
  card.addEventListener('click',()=>{
    const center=state.ref.service_centers.find(c=>c.service_center_id===person.service_center_id);
    const box=$('details');box.replaceChildren();box.hidden=false;
    const close=node('button','close','×');close.setAttribute('aria-label','Закрыть карточку');close.onclick=()=>{box.hidden=true;};
    box.append(close,node('div','detail-id',person.staff_id),node('h2','',person.display_name||person.staff_id),node('p','',person.technologies.join(' · ')),
      detailRow('Сервисный центр',person.service_center_id),detailRow('Смена',`${person.shift_start.slice(0,5)}–${person.shift_end.slice(0,5)}`),
      node('p','', 'Положение показано по закреплённому СЦ. Текущая GPS-позиция не поступала.'));
    if(center&&map)map.flyTo([center.lat,center.lon],14,{duration:.6});
  });return card;
}
function detailRow(label,value){const row=node('div','detail-row');row.append(node('span','',label),node('span','',value));return row;}
function selectOrder(order){
  state.selected=order.order_id;render();
  const box=$('details');box.replaceChildren();box.hidden=false;
  const assignment=assigned(order.order_id);
  const fullTime=value=>new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Yekaterinburg'}).format(new Date(value));
  const close=node('button','close','×');close.setAttribute('aria-label','Закрыть карточку');close.addEventListener('click',()=>{box.hidden=true;state.selected=null;render();});
  box.append(close,node('div','detail-id',order.order_id),node('h2','',order.address),node('p','',work(order).name),
    detailRow('Статус',statusLabels[state.view.status(order.order_id)]),
    detailRow('Технология',order.technology),detailRow('Слот',`${time(order.slot_start)}–${time(order.slot_end)}`),
    detailRow('Начать не позднее',time(order.latest_start)),detailRow('Назначено выполнить до',assignment?fullTime(assignment.stop.end):'Назначение ещё не получено'),
    detailRow('Узел доступа',order.access_node_id),detailRow('Допуск к высоте',order.requires_height?'Требуется':'Не требуется'));
  const normative=node('details');normative.append(node('summary','','Нормативный срок по ТЗ'),node('p','',fullTime(order.deadline)+' · используется для оценки просрочки, не является назначенным временем визита'));box.append(normative);
  if(order.is_repeat)box.append(node('p','repeat-tag','↺ Повторное обращение · повышенный приоритет'));
  const equipment=node('div','equipment');for(const [kind,count]of Object.entries(order.required_equipment)){if(count)equipment.append(node('span','',`${kind} × ${count}`));}
  if(!equipment.childNodes.length)equipment.append(node('span','','АО не требуется'));box.append(equipment);
  if(assignment)box.append(detailRow('Исполнитель',assignment.staff),detailRow('Назначенный визит',`${fullTime(assignment.stop.start)}–${time(assignment.stop.end)}`));
  const reason=state.view.unassigned.get(order.order_id);
  if(reason)box.append(node('div','unassigned-detail',`${reason.reason_text} ${actionLabels[reason.suggested_action]||''}`));
  const group=state.view.groups.get(order.order_id);if(group)box.append(node('div','unassigned-detail',`${group.group_id}: ${actionLabels[group.action]||group.action}`));
  const cancelled=state.view.cancelled.get(order.order_id);if(cancelled)box.append(detailRow('Отменён в',time(cancelled.cancelled_at)));
  dispatcher.highlight();
  if(map)map.flyTo([order.lat,order.lon],15,{duration:.6});
}
function render(){
  let daily=document.getElementById('daily-order-counts');
  if(!daily){daily=node('div','statusbar');daily.id='daily-order-counts';document.querySelector('.statusbar').after(daily);}
  const dailyCounts=state.view?.counts;
  daily.textContent=state.day?`Наряды за ${state.day.date}: всего ${dailyCounts?.all ?? state.day.orders.length} · назначено ${dailyCounts?.assigned ?? 0} · не назначено ${dailyCounts?.unassigned ?? 0}`+(state.day.plan?'':` · ожидают расчёта ${state.day.orders.length}`):'Выберите день';

  let summary=document.getElementById('automatic-policy-summary');
  if(!summary){summary=node('div','statusbar');summary.id='automatic-policy-summary';document.querySelector('.statusbar').after(summary);}
  const plan=state.day?.plan;
  const changes=plan?.automatic_reschedules||[],incidents=plan?.incident_groups||[],transfers=plan?.transferred_orders||[];
  summary.textContent=`Автоматические переносы: ${changes.length}. На другие дни: ${transfers.length}. Группы аварий с выездами: ${incidents.length}. `+
    transfers.map(c=>` → `).join('; ')+ ' '+changes.slice(-3).map(c=>`${c.order_id}: ${time(c.old_slot.start)} → ${time(c.slot.start)}`).join('; ')+
    (incidents.length?' · '+incidents.map(g=>`${g.group_id}: ${g.order_ids.length} заявок`).join('; '):'');
  if(!state.ref||!state.day)return;
  state.view=projectDay(state.day,state.ref.staff);
  const orders=filteredOrders();const staff=filteredStaff();const rows=state.tab==='orders'?orders:staff;
  $('list-count').textContent=state.day.orders.length;
  $('results-text').textContent=state.tab==='orders'?`Найдено нарядов: ${rows.length}`:`Сотрудников: ${rows.length}`;
  $('list').replaceChildren(...rows.map(state.tab==='orders'?orderCard:staffCard));
  if(!rows.length)$('list').append(node('div','empty','Ничего не найдено. Измените поиск или сбросьте фильтры.'));
  renderMarkers(orders);
  dispatcher.highlight();
}
function setTab(tab){
  state.tab=tab;for(const key of ['orders','staff']){$(key+'-tab').classList.toggle('selected',key===tab);$(key+'-tab').setAttribute('aria-pressed',String(key===tab));}
  $('search').placeholder=tab==='orders'?'Адрес, номер наряда или дома':'Имя, номер сотрудника или СЦ';
  $('search').setAttribute('aria-label',tab==='orders'?'Поиск по адресу, наряду или дому':'Поиск сотрудника');render();
}
async function loadDay(){
  const seq=++state.request;error('');$('refresh').disabled=true;
  $('list').replaceChildren(node('div','empty','Загружаем данные дня…'));state.day=null;state.selected=null;$('details').hidden=true;
  state.view=null;state.geometryRequest++;routeLayer?.clearLayers();dispatcher.loading();
  if(ordersLayer)ordersLayer.clearLayers();$('total').textContent='—';$('repeat-count').textContent='—';
  try {
    const day=await get('/api/ui/days/'+encodeURIComponent($('day').value));if(seq!==state.request)return;
    state.day=day;$('total').textContent=day.orders.length;$('repeat-count').textContent=day.orders.filter(o=>o.is_repeat).length;
    if(!day.plan)state.status='all';
    $('model-time').textContent=`Модельное время ${time(day.model_now)} · UTC+5`;
    $('plan-status').textContent=day.plan?`План · версия ${day.plan.plan_version}`:'План ещё не построен';
    const overview=planOverview(day.plan);
    $('plan-note').textContent=day.plan?`Назначено ${overview.visits} · Не назначено ${overview.unassigned} · ПГП ${overview.pgp}`:'Готов к первому расчёту';
    updateRouteOptions();
    updateEventExample();
    render();dispatcher.render();fit();
  }catch(e){if(seq===state.request){error(e.message);$('list').replaceChildren(node('div','empty','Данные не загружены. Нажмите «Обновить данные» после восстановления подключения.'));}}
  finally{if(seq===state.request)$('refresh').disabled=false;}
}
async function bootstrap(){
  error('');$('refresh').disabled=true;
  try{
    const ref=await get('/api/ui/bootstrap');state.ref=ref;
    $('source').textContent=ref.data_source==='demo'?'Демо · данные из файлов':'PostgreSQL · подключено';$('source').className='source '+ref.data_source;
    $('staff-count').textContent=ref.staff.length;$('center-count').textContent=ref.service_centers.length;
    $('day').replaceChildren(...ref.days.map(d=>{const o=node('option','',dateLabel(d.date));o.value=d.date;return o;}));
    $('day').disabled=!ref.days.length;renderCenters();
    if(ref.days.length)await loadDay();
    else {$('list').replaceChildren(node('div','empty','Дни ещё не загружены. Импортируйте подготовленные данные.'));fit();}
  }catch(e){error(e.message);$('source').textContent='Нет подключения';$('list').replaceChildren(node('div','empty','Проверьте настройки подключения к базе. Данные из файлов не подставляются автоматически.'));}
  finally{$('refresh').disabled=false;}
}
$('refresh').onclick=()=>state.ref?loadDay():bootstrap();$('day').onchange=loadDay;
for(const id of ['search','technology','profile'])$(id).addEventListener(id==='search'?'input':'change',()=>{state.selected=null;$('details').hidden=true;render();});
$('reset').onclick=()=>{for(const id of ['search','technology','profile'])$(id).value='';state.status='all';state.selected=null;$('details').hidden=true;render();dispatcher.syncStatus();fit();};
$('orders-tab').onclick=()=>setTab('orders');$('staff-tab').onclick=()=>setTab('staff');$('fit').onclick=fit;
setupMap();bootstrap();

function assigned(id){
  return state.view?.assignments.get(id)||null;
}
const planControls=node('div','plan-controls');
const buildButton=node('button','build-button','Сформировать план');buildButton.id='build-plan';
const routeChoice=node('select');routeChoice.id='route-choice';routeChoice.setAttribute('aria-label','Маршрут сотрудника');
planControls.append(buildButton,routeChoice);document.querySelector('.workspace').before(planControls);
let routeLayer=map?L.layerGroup().addTo(map):null;
function updateRouteOptions(){
  state.geometryRequest++;if(routeLayer)routeLayer.clearLayers();
  routeChoice.replaceChildren(node('option','','Выберите маршрут сотрудника'));routeChoice.firstChild.value='';
  const routes=(state.day?.plan?.routes||[]).filter(r=>r.stops.some(s=>s.type==='VISIT'));
  for(const route of routes){const visits=route.stops.filter(s=>s.type==='VISIT');const option=node('option','',`${route.staff_id} · ${visits.length} визитов`);option.value=route.staff_id;routeChoice.append(option);}
  routeChoice.disabled=!routes.length;
  buildButton.disabled=(state.day?.plan?.plan_version||0)>1;
  buildButton.title=buildButton.disabled?'После событий план обновляется автоматически.':'Построить расписание выездов. Лимит вычисления — 30 секунд; длительность работ определяется типом заявки.';
}
buildButton.onclick=async()=>{
  if(!state.day)return;const day=$('day').value;buildButton.disabled=true;$('day').disabled=true;buildButton.textContent='Идёт расчёт…';error('');
  try{
    const response=await fetch(`/api/v1/days/${day}/plan`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({time_limit_sec:30})});
    const result=await response.json();if(!response.ok)throw new Error(result.error?.message||'Не удалось рассчитать план.');
    await loadDay();
  }catch(e){error(e.message);}finally{buildButton.disabled=false;$('day').disabled=false;buildButton.textContent='Обновить план';}
};
const dispatcher=createDispatcher({state,node,time,
  onStatus(status){state.status=status;state.selected=null;$('details').hidden=true;setTab('orders');dispatcher.syncStatus();},
  focusOrder(id){const order=state.day?.orders.find(o=>o.order_id===id);if(!order)return;state.status='all';for(const key of ['technology','profile'])$(key).value='';$('search').value=id;setTab('orders');dispatcher.syncStatus();selectOrder(order);document.querySelector('.workspace').scrollIntoView({behavior:'smooth',block:'start'});},
  chooseRoute(id){routeChoice.value=id;dispatcher.highlight();if(routeChoice.value)routeChoice.onchange();document.querySelector('.workspace').scrollIntoView({behavior:'smooth',block:'start'});}
});
routeChoice.addEventListener('change',()=>dispatcher.highlight());
dispatcher.render();
routeChoice.onchange=async()=>{
  const seq=++state.geometryRequest;routeLayer?.clearLayers();if(!routeChoice.value||!state.day)return;
  const route=state.day.plan.routes.find(r=>r.staff_id===routeChoice.value);error('');
  try{
    const result=await get(`/api/ui/days/${$('day').value}/routes/${route.staff_id}/geometry`);
    if(seq!==state.geometryRequest)return;
    if(result.staff_id!==route.staff_id||result.plan_version!==state.day.plan.plan_version){
      throw new Error('План изменился. Обновите данные и выберите маршрут повторно.');
    }
    const palette=['#159fe8','#20bc8b','#ef638a','#69b844','#35bbc6','#e2ac21','#6294ef','#e777b0'];
    const line=L.featureGroup().addTo(routeLayer);
    for(const [i,segment] of result.segments.entries()){
      L.geoJSON(segment.geometry,{interactive:false,style:{color:'#ffffff',weight:5,opacity:.95,dashArray:'6 7',lineCap:'round',lineJoin:'round'}}).addTo(line);
      L.geoJSON(segment.geometry,{style:{color:palette[i%palette.length],weight:2.5,opacity:.95,dashArray:'6 7',lineCap:'round',lineJoin:'round'}})
        .bindTooltip(`${segment.from_stop} → ${segment.to_stop}`,{sticky:true}).addTo(line);
    }
    let number=0;
    for(const stop of route.stops){if(stop.type!=='VISIT')continue;number++;
      const order=state.day.orders.find(o=>o.order_id===stop.order_id);
      L.marker([order.lat,order.lon],{zIndexOffset:1100,icon:L.divIcon({className:'route-number',html:String(number),iconSize:[26,26]})})
        .addTo(routeLayer).bindPopup(popup(order.address,`${time(stop.start)}–${time(stop.end)} · ${stop.order_id}`,'Открыть наряд',()=>selectOrder(order)));
    }
    if(line.getBounds().isValid())map.fitBounds(line.getBounds(),{padding:[35,35]});
  }catch(e){if(seq===state.geometryRequest)error(e.message);}
};
updateRouteOptions();

const eventsPanel=node('details','events-panel');eventsPanel.append(node('summary','','События и перепланирование'));
eventsPanel.append(node('p','','Событие изменяет модельное время и создаёт новую версию плана. Уже начатые визиты сохраняются; первоначальный расчёт после события закрывается.'));
const eventType=node('select');eventType.setAttribute('aria-label','Тип события');
for(const [code,label] of [['TIME_TICK','Ход времени'],['ORDER_CANCELLED','Отмена визита'],['STAFF_UNAVAILABLE','Недоступность сотрудника'],['VISIT_DELAYED','Задержка работ'],['ORDER_TRANSFERRED','Передача в подразделение'],['NEW_ORDER','Новый наряд']]){const option=node('option','',label);option.value=code;eventType.append(option);}
const eventBody=node('textarea');eventBody.setAttribute('aria-label','Параметры события JSON');eventBody.rows=11;eventBody.spellcheck=false;
const eventSend=node('button','build-button','Применить событие');const eventStatus=node('span','event-status');
eventsPanel.append(eventType,eventBody,eventSend,eventStatus);document.querySelector('.statusbar').after(eventsPanel);
document.querySelector('.dispatch-results').after(eventsPanel);
function eventIso(value){return new Date(new Date(value).getTime()+5*3600000).toISOString().slice(0,19)+'+05:00';}
function updateEventExample(){
  if(!state.day){eventSend.disabled=true;return;}
  eventSend.disabled=!state.day.plan;
  const now=new Date(state.day.model_now);const future=new Date(now.getTime()+15*60000);
  const body={event_id:'EV-'+createEventId(),type:eventType.value,timestamp:eventIso(future)};
  const assignedVisits=(state.day.plan?.routes||[]).flatMap(r=>r.stops.filter(s=>s.type==='VISIT').map(s=>({staff:r.staff_id,stop:s})));
  const next=assignedVisits.find(v=>new Date(v.stop.end)>now);const order=state.day.orders.find(o=>new Date(o.slot_start)>future)||state.day.orders[0];
  if(body.type==='ORDER_CANCELLED'){body.order_id=order?.order_id;body.reason='CUSTOMER_REQUEST';}
  if(body.type==='STAFF_UNAVAILABLE'){body.staff_id=next?.staff||state.ref?.staff[0]?.staff_id;body.reason='VEHICLE_BREAKDOWN';body.until=eventIso(new Date(future.getTime()+2*3600000));}
  if(['VISIT_DELAYED','ORDER_TRANSFERRED'].includes(body.type)&&next){
    body.staff_id=next.staff;body.order_id=next.stop.order_id;
    const moment=new Date(Math.max(now.getTime(),new Date(next.stop.start).getTime())+60000);body.timestamp=eventIso(moment);
    if(body.type==='VISIT_DELAYED')body.expected_end=eventIso(new Date(new Date(next.stop.end).getTime()+30*60000));
    else {body.actual_end=body.timestamp;body.transferred_to='STATION_EQUIPMENT';}
  }
  if(body.type==='NEW_ORDER'&&order){
    const o={...order};delete o.slot_start;delete o.slot_end;
    o.slot={start:order.slot_start,end:order.slot_end};o.order_id=`ORD-${$('day').value.replaceAll('-','')}-${9000+Math.floor(Math.random()*999)}`;
    o.registered_at=body.timestamp;o.is_repeat=false;o.previous_order_id=null;body.order=o;
  }
  eventBody.value=JSON.stringify(body,null,2);
}
eventType.onchange=updateEventExample;
eventSend.onclick=async()=>{
  let payload;try{payload=JSON.parse(eventBody.value);}catch{eventStatus.textContent='Проверьте синтаксис JSON.';return;}
  eventSend.disabled=true;$('day').disabled=true;eventStatus.textContent='Перепланирование…';
  try{
    const response=await fetch(`/api/v1/days/${$('day').value}/events`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const result=await response.json();if(!response.ok)throw new Error(result.error?.message||'Ошибка события.');
    await bootstrap();eventStatus.textContent=`${result.duplicate?'Повтор уже принятого события':'Событие принято'} · версия ${result.plan_version} · ${result.processing_ms} мс`;
  }catch(e){eventStatus.textContent=e.message;}finally{eventSend.disabled=!state.day?.plan;$('day').disabled=false;}
};





