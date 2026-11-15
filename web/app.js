import {icon,applyIcons} from './icons.js';
import {time,fullTime,shiftTime} from './ui-format.js';
import {createNavigation} from './navigation.js';
import {createEventId} from './uuid.js';
import {planAction} from './plan-action.js';
import {projectDay,statusLabels,actionLabels,matchesOrderStatus,markerSummary} from './dispatch-model.js';
import {createDispatcher} from './dispatcher-view.js';
import {MapView} from './map-view.js';
const $=id=>document.getElementById(id);
applyIcons();
const state={ref:null,day:null,tab:'orders',selected:null,request:0,markers:new Map(),geometryRequest:0,status:'all',view:null,planning:false};
const techColors={PON:'#df8b4e',FTTB:'#6d58ae',XDSL:'#548f8b',DOCSIS:'#bd7897'};
const dateLabel=value=>new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long',year:'numeric',timeZone:'Asia/Yekaterinburg'}).format(new Date(value+'T12:00:00+05:00'));
function node(tag,className,text){const e=document.createElement(tag);if(className)e.className=className;if(text!==undefined)e.textContent=text;return e;}
function error(message){$('error').textContent=message;$('error').hidden=!message;}
async function get(url){
  const response=await fetch(url,{headers:{Accept:'application/json'},cache:'no-store'});
  const body=await response.json();
  if(!response.ok)throw new Error(body.error?.message||'Не удалось загрузить данные.');
  return body;
}
let map;
const navigation=createNavigation(()=>map);
function setupMap(){
  let failed=0;
  try{
    map=new MapView('map',{
      onTileError(){if(++failed>=3)$('tiles-warning').hidden=false;},
      onTileLoad(){$('tiles-warning').hidden=true;failed=0;},
      onError(){error('Не удалось загрузить карту. Обновите страницу; список нарядов остаётся доступен.');}
    });
  }catch(e){error('Карта не запустилась. Проверьте поддержку WebGL в браузере; список нарядов остаётся доступен.');}
}
function popup(title,subtitle,buttonLabel,action){
  const box=node('div');box.append(node('strong','',title),node('div','',subtitle));
  if(buttonLabel){const b=node('button','popup-action',buttonLabel);b.addEventListener('click',action);box.append(b);}
  return box;
}
function renderCenters(){
  if(!map)return;map.clearMarkers('centers');
  for(const c of state.ref.service_centers){
    map.marker('centers',{lat:c.lat,lon:c.lon,className:'depot-icon',text:'⌂',title:c.name,zIndex:500,popup:popup(c.name,c.address)});
  }
}
function filteredOrders(){
  const query=$('search').value.trim().toLocaleLowerCase('ru');const tech=$('technology').value;const profile=$('profile').value;
  return (state.day?.orders||[]).filter(o=>matchesOrderStatus(state.view,o.order_id,state.status)&&(!tech||o.technology===tech)&&(!profile||work(o).profiles.includes(profile))&&
    (!query||[o.order_id,o.building_id,o.address,o.access_node_id].some(v=>v.toLocaleLowerCase('ru').includes(query))));
}
function filteredStaff(){
  const query=$('search').value.trim().toLocaleLowerCase('ru');const tech=$('technology').value;const profile=$('profile').value;
  return (state.ref?.staff||[]).filter(p=>(!tech||p.technologies.includes(tech))&&(!profile||p.profiles.includes(profile))&&
    (!query||[p.staff_id,p.display_name||'',p.service_center_id].some(v=>v.toLocaleLowerCase('ru').includes(query))));
}
function work(order){return state.ref.work_types.find(w=>w.code===order.work_type_code)||{name:order.work_type_code,duration_min:0,profiles:[]};}
function fit(){
  if(!map)return;const points=state.ref?.service_centers.map(c=>[c.lon,c.lat])||[];
  for(const o of filteredOrders())points.push([o.lon,o.lat]);
  map.fitPoints(points);
}
function renderMarkers(orders){
  if(!map)return;map.clearMarkers('orders');state.markers.clear();
  const groups=new Map();for(const o of orders){if(!groups.has(o.building_id))groups.set(o.building_id,[]);groups.get(o.building_id).push(o);}
  $('map-count').textContent=`${groups.size} адресов`;
  for(const [id,group] of groups){
    const o=group[0];const repeated=group.some(o=>o.is_repeat);const focused=group.some(o=>o.order_id===state.selected);
    const summary=markerSummary(group,state.view);
    const marker=map.marker('orders',{lat:o.lat,lon:o.lon,title:`${o.address}: ${group.length} нарядов${summary.text?' · '+summary.text:''}`,
      className:`order-icon marker-${summary.kind}${repeated?' repeat':''}${focused?' focused':''}`,text:String(group.length),
      popup:popup(o.address,`${id} · ${group.length} нарядов${summary.text?' · '+summary.text:''}`,group.length===1?'Открыть наряд':'Показать наряды дома',()=>{
      if(group.length===1)selectOrder(o);
      else {$('search').value=id;setTab('orders');render();map.closePopup();}
    })});state.markers.set(id,marker);
  }
}
function orderCard(order){
  const w=work(order);const card=node('button',`order-card${state.selected===order.order_id?' chosen':''}`);card.type='button';
  const top=node('div','card-top');top.append(node('span','order-id',order.order_id),node('span','tech-chip',order.technology));
  const bottom=node('div','card-bottom');bottom.append(node('span','time-tag',`${time(order.slot_start)} — ${time(order.slot_end)}`),node('span','',`${w.duration_min} мин`));
  if(order.is_repeat)bottom.append(node('span','repeat-tag','Повтор'));
  if(order.requires_height)bottom.append(node('span','height-tag','Допуск к высоте'));
  card.append(top,node('h3','',order.address),node('div','card-work',w.name),bottom);
  const assignment=assigned(order.order_id);
  if(assignment)card.append(node('div','assignment',`${assignment.staff} · визит ${assignment.number} · ${time(assignment.stop.start)}`));
  const status=state.view.status(order.order_id);card.append(node('span',`status-tag status-${status}`,statusLabels[status]));
  const group=state.view.groups.get(order.order_id);if(group&&group.kind==='incident'&&status!=='cancelled')card.append(node('span','status-tag status-pgp','ПГП · отдельный выезд'));
  const reason=state.view.unassigned.get(order.order_id);if(reason)card.append(node('div','reason-preview',reason.reason_text));
  if(state.view.risks.has(order.order_id))card.append(node('span','risk-badge','Риск опоздания'));
  card.addEventListener('click',()=>selectOrder(order));return card;
}
function staffCard(person){
  const card=node('button','order-card staff-card');const top=node('div','card-top');
  top.append(node('span','order-id',person.staff_id),node('span','tech-chip',person.profiles.map(p=>p==='LTP3'?'3ЛТП':'Инсталляция').join(' / ')));
  card.append(top,node('h3','',person.display_name||person.staff_id),node('div','card-work',`${person.technologies.join(' · ')}${person.height_permit?' · Допуск к высоте':''}`));
  const bottom=node('div','card-bottom');bottom.append(node('span','time-tag',`${shiftTime(state.day.date,person.shift_start)} — ${shiftTime(state.day.date,person.shift_end)}`),node('span','',person.service_center_id));card.append(bottom);
  const workload=state.view?.rows.find(r=>r.route.staff_id===person.staff_id);
  const inventory=state.day?.inventory?.find(p=>p.staff_id===person.staff_id);
  if(inventory)card.append(node('div','staff-workload',`Остаток: ONT ${inventory.current.ONT} · роутеры ${inventory.current.ROUTER} · STB ${inventory.current.STB}`));
  if(workload)card.append(node('div','staff-workload',`${workload.visits} визитов · работы ${Math.round(workload.workMin)} мин · дорога ${Math.round(workload.travelMin)} мин`));
  card.addEventListener('click',()=>{
    const center=state.ref.service_centers.find(c=>c.service_center_id===person.service_center_id);
    const box=$('details');box.replaceChildren();box.hidden=false;
    const close=node('button','close');close.append(icon('x'));close.setAttribute('aria-label','Закрыть карточку');close.onclick=()=>{box.hidden=true;};
    box.append(close,node('div','detail-id',person.staff_id),node('h2','',person.display_name||person.staff_id),node('p','',person.technologies.join(' · ')),
      detailRow('Сервисный центр',person.service_center_id),detailRow('Смена',`${shiftTime(state.day.date,person.shift_start)}–${shiftTime(state.day.date,person.shift_end)}`),
      node('p','', 'Положение показано по закреплённому СЦ. Текущая GPS-позиция не поступала.'));
    if(center&&map)map.focus([center.lon,center.lat],14);
  });return card;
}
function detailRow(label,value){const row=node('div','detail-row');row.append(node('span','',label),node('span','',value));return row;}
function selectOrder(order){
  map?.closePopup();
  state.selected=order.order_id;render();
  const box=$('details');box.replaceChildren();box.hidden=false;
  const assignment=assigned(order.order_id);
  const close=node('button','close');close.append(icon('x'));close.setAttribute('aria-label','Закрыть карточку');close.addEventListener('click',()=>{box.hidden=true;state.selected=null;render();});
  box.append(close,node('div','detail-id',order.order_id),node('h2','',order.address),node('p','',work(order).name),
    detailRow('Статус',statusLabels[state.view.status(order.order_id)]),
    detailRow('Технология',order.technology),detailRow('Слот',`${time(order.slot_start)}–${time(order.slot_end)}`),
    detailRow('Начать не позднее',time(order.latest_start)),detailRow('Назначено выполнить до',assignment?fullTime(assignment.stop.end):'Назначение ещё не получено'),
    detailRow('Узел доступа',order.access_node_id),detailRow('Допуск к высоте',order.requires_height?'Требуется':'Не требуется'));
  const normative=node('details');normative.append(node('summary','','Нормативный срок по ТЗ'),node('p','',fullTime(order.deadline)+' · используется для оценки просрочки, не является назначенным временем визита'));box.append(normative);
  if(order.is_repeat)box.append(node('p','repeat-tag','Повторное обращение · повышенный приоритет'));
  const equipment=node('div','equipment');for(const [kind,count]of Object.entries(order.required_equipment)){if(count)equipment.append(node('span','',`${kind} × ${count}`));}
  if(!equipment.childNodes.length)equipment.append(node('span','','АО не требуется'));box.append(equipment);
  if(assignment)box.append(detailRow('Исполнитель',assignment.staff),detailRow('Назначенный визит',`${fullTime(assignment.stop.start)}–${time(assignment.stop.end)}`));
  const reason=state.view.unassigned.get(order.order_id);
  if(reason)box.append(node('div','unassigned-detail',`${reason.reason_text} ${actionLabels[reason.suggested_action]||''}`));
  const group=state.view.groups.get(order.order_id);if(group&&!state.view.cancelled.has(order.order_id))box.append(node('div','unassigned-detail',`ПГП · ${group.group_id} · узел ${group.access_node_id} · ${group.order_ids.length} нарядов. ${actionLabels[group.action]||group.action}`));
  const cancelled=state.view.cancelled.get(order.order_id);if(cancelled)box.append(detailRow('Отменён в',fullTime(cancelled.cancelled_at)),node('p','status-tag status-cancelled','Отменённый наряд не требует выезда'));
  for(const alert of state.view.riskAlerts.get(order.order_id)||[]){
    const facts=node('div','unassigned-detail risk-detail');facts.append(node('strong','','Риск опоздания'),node('p','',alert.message));
    if(alert.forecast_start)facts.append(detailRow('Прогноз начала',fullTime(alert.forecast_start)));
    if(alert.lateness_min!=null)facts.append(detailRow('Опоздание',`${alert.lateness_min} мин`));
    if(alert.warning_deadline)facts.append(detailRow('Предупредить до',fullTime(alert.warning_deadline)));
    facts.append(node('p','',actionLabels[alert.suggested_action]||alert.suggested_action||''));box.append(facts);
  }
  dispatcher.highlight();
  if(map)map.focus([order.lon,order.lat],15);
}
function render(){
  if(state.ref&&state.day)state.view=projectDay(state.day,state.ref.staff);
  if(!state.ref||!state.day)return;
  state.view=projectDay(state.day,state.ref.staff);
  const orders=filteredOrders();const staff=filteredStaff();const rows=state.tab==='orders'?orders:staff;
  $('list-count').textContent=state.day.orders.length;
  $('results-text').textContent=state.tab==='orders'?`Найдено нарядов: ${rows.length}`:`Сотрудников: ${rows.length}`;
  $('list').replaceChildren(...rows.map(state.tab==='orders'?orderCard:staffCard));
  if(!rows.length){
    const labels={risk:'Нарядов с активным риском опоздания',pgp:'Нарядов в ПГП',cancelled:'Отменённых нарядов'};
    const message=state.tab==='orders'&&labels[state.status]?`${labels[state.status]} по выбранной дате и фильтрам нет.`:'Ничего не найдено. Измените поиск или сбросьте фильтры.';
    $('list').append(node('div','empty',message));
  }
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
  updatePlanButton();
  state.view=null;state.geometryRequest++;map?.clearRoute();dispatcher.loading();
  map?.clearMarkers('orders');$('total').textContent='—';
  try {
    const day=await get('/api/ui/days/'+encodeURIComponent($('day').value));if(seq!==state.request)return;
    state.day=day;$('total').textContent=day.orders.length;
    if(!day.plan)state.status='all';
    $('model-time').textContent=`Модельное время ${time(day.model_now)} · Екатеринбург`;
    updateRouteOptions();
    render();dispatcher.render();map?.showCity();
  }catch(e){if(seq===state.request){error(e.message);$('list').replaceChildren(node('div','empty','Данные не загружены. Нажмите «Обновить данные» после восстановления подключения.'));}}
  finally{if(seq===state.request){$('refresh').disabled=false;updatePlanButton();}}
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
$('orders-tab').onclick=()=>setTab('orders');$('staff-tab').onclick=()=>setTab('staff');$('fit').onclick=fit;$('show-city').onclick=()=>map?.showCity();
setupMap();bootstrap();

function assigned(id){
  return state.view?.assignments.get(id)||null;
}
const planControls=node('div','plan-controls');
const buildButton=node('button','build-button','Сформировать план');buildButton.id='build-plan';buildButton.disabled=true;
const routeChoice=node('select');routeChoice.id='route-choice';routeChoice.setAttribute('aria-label','Маршрут сотрудника');
planControls.append(buildButton,routeChoice);document.querySelector('.workspace').before(planControls);
function updateRouteOptions(){
  state.geometryRequest++;map?.clearRoute();
  routeChoice.replaceChildren(node('option','','Выберите маршрут сотрудника'));routeChoice.firstChild.value='';
  const routes=(state.day?.plan?.routes||[]).filter(r=>r.stops.some(s=>s.type==='VISIT'));
  for(const route of routes){const visits=route.stops.filter(s=>s.type==='VISIT');const option=node('option','',`${route.staff_id} · ${visits.length} визитов`);option.value=route.staff_id;routeChoice.append(option);}
  routeChoice.disabled=!routes.length;
  updatePlanButton();
}
function updatePlanButton(){
  buildButton.disabled=state.planning||!state.day;
  buildButton.textContent=state.planning?'Идёт расчёт…':state.day?.plan?'Обновить план':'Сформировать план';
  buildButton.title=state.day?.plan?'Пересчитать текущую смену, сохраняя модельное время и начатые визиты.':'Построить расписание выездов. Лимит вычисления — 30 секунд.';
}
buildButton.onclick=async()=>{
  if(!state.day||state.planning)return;const day=$('day').value;state.planning=true;updatePlanButton();$('day').disabled=true;$('refresh').disabled=true;error('');
  try{
    // Another browser or the entry panel may have advanced the shift already.
    const latest=await get(`/api/ui/days/${encodeURIComponent(day)}`);
    const action=planAction(latest,'UI-REPLAN-'+createEventId());
    const response=await fetch(action.url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(action.body)});
    const result=await response.json();if(!response.ok)throw new Error(result.error?.message||'Не удалось рассчитать план.');
    await loadDay();
  }catch(e){error(e.message);}finally{state.planning=false;$('day').disabled=!state.ref?.days.length;$('refresh').disabled=false;updatePlanButton();}
};
const dispatcher=createDispatcher({state,node,time,
  onStatus(status){navigation.show('map');state.status=status;state.geometryRequest++;map?.clearRoute();$('route-choice').value='';state.selected=null;$('details').hidden=true;setTab('orders');dispatcher.syncStatus();fit();},
  focusOrder(id){const order=state.day?.orders.find(o=>o.order_id===id);if(!order)return;navigation.show('map');state.status='all';for(const key of ['technology','profile'])$(key).value='';$('search').value=id;setTab('orders');dispatcher.syncStatus();selectOrder(order);document.querySelector('.workspace').scrollIntoView({behavior:'smooth',block:'start'});},
  chooseRoute(id){navigation.show('map');routeChoice.value=id;dispatcher.highlight();if(routeChoice.value)routeChoice.onchange();document.querySelector('.workspace').scrollIntoView({behavior:'smooth',block:'start'});}
});
routeChoice.addEventListener('change',()=>dispatcher.highlight());
dispatcher.render();
routeChoice.onchange=async()=>{
  const seq=++state.geometryRequest;map?.clearRoute();if(!routeChoice.value||!state.day||!map)return;
  const route=state.day.plan.routes.find(r=>r.staff_id===routeChoice.value);error('');
  let number=0;
  for(const stop of route.stops){if(stop.type!=='VISIT')continue;number++;
    const order=state.day.orders.find(o=>o.order_id===stop.order_id);
    if(!order)continue;
    map.marker('route',{lat:order.lat,lon:order.lon,className:'route-number',text:String(number),zIndex:1100,
      title:`Визит ${number}: ${order.address}`,popup:popup(order.address,`${time(stop.start)}–${time(stop.end)} · ${stop.order_id}`,'Открыть наряд',()=>selectOrder(order))});
  }
  try{
    const result=await get(`/api/ui/days/${$('day').value}/routes/${route.staff_id}/geometry`);
    if(seq!==state.geometryRequest)return;
    if(result.staff_id!==route.staff_id||result.plan_version!==state.day.plan.plan_version){
      throw new Error('План изменился. Обновите данные и выберите маршрут повторно.');
    }
    map.showRoute(result.segments);
  }catch(e){if(seq===state.geometryRequest)error(e.message);}
};
updateRouteOptions();
