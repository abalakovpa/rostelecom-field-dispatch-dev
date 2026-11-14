import {warningIndicator} from './ui-format.js';
import {projectDay,projectWarnings,statusLabels,actionLabels} from './dispatch-model.js';
export function createDispatcher({state,node,time,focusOrder,chooseRoute,onStatus}){
 const statuses=node('div','dispatch-statuses');statuses.setAttribute('aria-label','Статусы нарядов');document.querySelector('.workspace').before(statuses);
 const statusSelect=node('select');statusSelect.id='order-status';statusSelect.setAttribute('aria-label','Статус наряда');statusSelect.style.cssText='width:100%;margin-top:9px';
 for(const [key,label] of [['all','Все статусы'],['risk','Риск опоздания'],['assigned','Все назначенные'],['active','В работе по плану'],['completed','Завершены по плану'],['unassigned','Не назначены'],['pgp','ПГП'],['cancelled','Отменены']]){const o=node('option','',label);o.value=key;statusSelect.append(o);}
 document.querySelector('.list-heading').before(statusSelect);statusSelect.onchange=()=>onStatus(statusSelect.value);
 const root=node('div','dispatch-results');document.querySelector('#map-view').after(root);
 const gantt=node('section','dispatch-section');gantt.setAttribute('aria-label','Диаграмма Ганта');gantt.id='timeline-view';gantt.dataset.panel='timeline';gantt.hidden=true;
 const heading=node('div','dispatch-heading');const title=node('div');title.append(node('h2','','План смены по времени'),node('p','','Работы, переезды и перерывы · Екатеринбург, UTC+5'));
 const controls=node('div','gantt-controls');const find=node('input');find.type='search';find.placeholder='Найти сотрудника';find.setAttribute('aria-label','Поиск сотрудника в Ганте');find.style.cssText='border:1px solid #e1e7ef;border-radius:7px;padding:8px 10px;font-size:11px';
 const used=node('label','attention-history');const usedCheck=node('input');usedCheck.type='checkbox';used.append(usedCheck,node('span','','Только с визитами'));controls.append(find,used);heading.append(title,controls);gantt.append(heading);
 const legend=node('div','gantt-legend');const types={VISIT:'Работы',TRAVEL:'Дорога',WAIT:'Ожидание',BREAK:'Обед',RESTOCK:'Пополнение АО'};
 for(const [type,label]of Object.entries(types)){const item=node('span');item.append(node('i',`gantt-${type}`),node('span','',label));legend.append(item);}
 gantt.append(legend);const timeline=node('div','gantt-scroll');timeline.id='gantt';gantt.append(timeline);
 const attention=node('div','attention-grid');attention.id='warnings-view';attention.dataset.panel='warnings';attention.hidden=true;const warningPanel=node('section','dispatch-section attention-column');const warningHead=node('div','dispatch-heading');const warningTitle=node('div');warningTitle.append(node('h2','','Предупреждения'),node('p','','Сохранённые сигналы текущей версии плана'));
 const history=node('label','attention-history');const historyCheck=node('input');historyCheck.type='checkbox';history.append(historyCheck,node('span','','Показать закрытые'));warningHead.append(warningTitle,history);warningPanel.append(warningHead);const warnings=node('div','attention-list');warnings.id='warnings';warningPanel.append(warnings);
 attention.append(warningPanel);root.append(gantt,attention);
 let view=null;
 function empty(target,text){target.replaceChildren(node('div','dispatch-empty',text));}
 function syncStatus(){statusSelect.value=state.status||'all';for(const b of statuses.querySelectorAll('button'))b.setAttribute('aria-pressed',String(b.dataset.status===(state.status||'all')));}
 function renderCounts(){
  statuses.replaceChildren();
  for(const [key,label]of [['all','Все наряды'],['assigned','Назначены'],['risk','Риски'],['unassigned','Не назначены'],['pgp','ПГП'],['cancelled','Отменены']]){
   const b=node('button','status-filter');b.dataset.status=key;b.title=({risk:'Только активные риски опоздания',pgp:'Наряды, переданные в станционное подразделение как групповая проблема',cancelled:'Отменённые наряды за выбранную дату'})[key]||label;b.append(node('span','',label),node('strong','',state.day?.plan||key==='all'?String(view.counts[key]):'—'));b.disabled=!state.day?.plan&&key!=='all';b.onclick=()=>onStatus(key);statuses.append(b);
  }syncStatus();
 }
 function renderTimeline(){
  if(!state.day?.plan){empty(timeline,'Сначала рассчитайте план выбранного дня. Здесь появятся маршруты сотрудников по времени.');return;}
  let rows=view.rows;const query=find.value.trim().toLowerCase();rows=rows.filter(r=>(!usedCheck.checked||r.visits)&&(!query||[r.route.staff_id,r.person?.display_name||'',r.route.service_center_id].some(s=>s.toLowerCase().includes(query))));
  if(!rows.length){empty(timeline,'Сотрудники по выбранным фильтрам не найдены.');return;}
  const all=view.rows;const lo=Math.floor(Math.min(...all.map(r=>r.shiftStart))/3600000)*3600000,hi=Math.ceil(Math.max(...all.map(r=>r.shiftEnd))/3600000)*3600000;const span=hi-lo;const pct=t=>Math.max(0,Math.min(100,(t-lo)/span*100));
  const grid=node('div','gantt-grid');grid.style.setProperty('--hour-width',`${3600000/span*100}%`);
  const head=node('div','gantt-head');head.append(node('div','gantt-label','Сотрудник / загрузка'));const hours=node('div','gantt-hours');
  for(let t=lo;t<=hi;t+=3600000){const tick=node('span','',time(t));tick.style.left=`${pct(t)}%`;if(t===lo)tick.style.transform='none';if(t===hi)tick.style.transform='translateX(-100%)';hours.append(tick);}head.append(hours);grid.append(head);
  const now=Date.parse(state.day.model_now);
  for(const row of rows){
   const line=node('div','gantt-row');line.dataset.staff=row.route.staff_id;const employee=node('button','gantt-label');employee.append(node('strong','',row.route.staff_id+' · '+(row.person?.display_name||'Сотрудник')),node('small','',`${row.visits} визитов · ${Math.round(row.utilization*100)}% · ${row.route.status==='UNAVAILABLE'?'Недоступен':row.route.service_center_id}`));employee.title=`Работы ${Math.round(row.workMin)} мин · дорога ${Math.round(row.travelMin)} мин · ожидание ${Math.round(row.waitMin)} мин`;employee.onclick=()=>chooseRoute(row.route.staff_id);
   const track=node('div','gantt-track');const shift=node('div','gantt-shift');shift.style.left=pct(row.shiftStart)+'%';shift.style.width=(pct(row.shiftEnd)-pct(row.shiftStart))+'%';track.append(shift);
   let visit=0;
   for(const b of row.blocks){
    if(b.type==='VISIT')visit++;const label=types[b.type]||b.type;const duration=Math.round((b.end-b.start)/60000);const block=node(b.type==='VISIT'?'button':'div',`gantt-block gantt-${b.type}`,b.type==='VISIT'?String(visit):duration>=30?label:'');
    block.style.left=pct(b.start)+'%';block.style.width=Math.max(0,pct(b.end)-pct(b.start))+'%';block.title=`${label} · ${time(b.start)}–${time(b.end)} · ${duration} мин${b.stop.order_id?' · '+b.stop.order_id:''}`;
    if(b.type==='VISIT'){block.dataset.order=b.stop.order_id;block.setAttribute('aria-label',block.title);block.onclick=()=>focusOrder(b.stop.order_id);}
    else block.setAttribute('aria-label',block.title);track.append(block);
   }
   if(now>=lo&&now<=hi){const marker=node('div','gantt-now');marker.style.left=pct(now)+'%';marker.title='Модельное время '+time(now);track.append(marker);}
   line.append(employee,track);grid.append(line);
  }
  timeline.replaceChildren(grid);highlight();
 }
 function renderAttention(){
  const plan=state.day?.plan;const alerts=projectWarnings(state.day);const signal=warningIndicator(plan,alerts);const indicator=document.getElementById('warning-indicator');
  indicator.className='warning-indicator '+signal.state;indicator.setAttribute('aria-label',signal.label);indicator.title=signal.label;
  if(!plan){empty(warnings,'Предупреждения появятся после расчёта и обработки событий.');return;}
  const list=alerts.filter(a=>historyCheck.checked||a.status==='ACTIVE');warnings.replaceChildren();
  if(!list.length)empty(warnings,alerts.length?'Активных предупреждений нет. Включите «Показать закрытые» для истории.':'По известным событиям и текущей матрице предупреждений нет. Неизвестные будущие задержки и пробки прогнозом не учитываются.');
  for(const a of list){const card=node('article','attention-card');const head=node('header');head.append(node('strong','',({LATE_RISK:'Риск опоздания',PGP_DETECTED:'Выявлена ПГП',INCIDENT_GROUP:'Общая авария (ПГП)',UNASSIGNED:'Неназначенный наряд'})[a.type]||a.type),node('span','',a.status==='ACTIVE'?'Активно':'Закрыто'));card.append(head,node('p','',a.message),node('div','attention-action',a.type==='LATE_RISK'&&a.status==='RESOLVED'?'Риск снят — дополнительных действий не требуется':actionLabels[a.suggested_action]||a.suggested_action),node('p','',`Создано ${time(a.created_at)}${a.staff_id?' · '+a.staff_id:''}${a.applied?' · действие применено':''}`));
   if(a.type==='LATE_RISK'){
    const facts=node('div','forecast-facts');
    const fact=(label,value)=>{const row=node('div');row.append(node('span','',label),node('strong','',value));facts.append(row);};
    if(a.forecast_start)fact('Без вмешательства',time(a.forecast_start));else if(a.forecast_available===false)fact('Прогноз начала','Исполнитель недоступен');
    if(a.lateness_min!=null)fact('Опоздание',`${a.lateness_min} мин`);
    if(a.warning_deadline)fact('Предупредить до',time(a.warning_deadline));
    if(a.timely!=null){const timing=node('div',a.timely?'timing-good':'timing-late',a.timely?'Предупреждение своевременное':'Риск выявлен менее чем за 30 минут до слота');facts.append(timing);}
    if(a.forecast_at)fact('Прогноз обновлён',time(a.forecast_at));
    if(a.suggested_staff_id)fact(a.applied?'Новый исполнитель':'Проверенная замена',a.suggested_staff_id);
    if(a.proposed_slot)fact('Предлагаемый слот',`${time(a.proposed_slot.start)}–${time(a.proposed_slot.end)}`);
    if(a.status==='RESOLVED')fact('Результат',a.resolution==='ROUTE_ADJUSTED'?'Исправлено перестановкой':a.applied?'Рекомендация выполнена':'Риск снят');
    else if(a.proposed_slot)facts.append(node('p','','Слот ещё не согласован с абонентом.'));
    card.append(facts);
   }
   if(a.order_id){const b=node('button','','Открыть наряд');b.onclick=()=>focusOrder(a.order_id);card.append(b);}else if(a.group_id){const b=node('button','','Показать наряды ПГП');b.onclick=()=>onStatus('pgp');card.append(b);}warnings.append(card);
  }

 }
 function highlight(){for(const e of timeline.querySelectorAll('[data-order]'))e.classList.toggle('selected-visit',e.dataset.order===state.selected);for(const e of timeline.querySelectorAll('[data-staff]'))e.classList.toggle('route-selected',e.dataset.staff===document.getElementById('route-choice').value);}
 find.oninput=renderTimeline;usedCheck.onchange=renderTimeline;historyCheck.onchange=renderAttention;
 return {render(){view=projectDay(state.day,state.ref?.staff);renderCounts();renderTimeline();renderAttention();},syncStatus,highlight,
  loading(){const indicator=document.getElementById('warning-indicator');indicator.className='warning-indicator unknown';indicator.setAttribute('aria-label','Предупреждения: данные загружаются');empty(timeline,'Загружаем план выбранного дня…');empty(warnings,'Загружаем предупреждения…');statuses.replaceChildren();}};
}
