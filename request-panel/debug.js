const $=id=>document.getElementById(id);
const section=document.createElement('section');
section.innerHTML=`<hr><h2>События и модельное время</h2>
<p>Отладка меняет настоящие данные выбранной даты. Время — Екатеринбург (UTC+5). Часы компьютера не двигают модель автоматически.</p>
<p>«К началу» и «К окончанию» двигают время всей смены. Это состояния по плану, а не подтверждение мастера.</p>
<button id="debug-refresh" type="button">Обновить снимок</button>
<p id="debug-clock" role="status">Загрузите день с рассчитанным планом.</p>
<label>Наряд<select id="debug-order"></select></label>
<div id="debug-actions"><button data-action="START">К началу визита</button> <button data-action="FINISH">К окончанию визита</button>
<label>Задержка, минут <input id="debug-minutes" type="number" min="1" max="1440" value="60"></label>
<button data-action="DELAY">Работы затянулись</button> <button data-action="CANCEL">Клиент отменил заявку</button>
<label>Мастер недоступен до (пусто — до конца смены)<input id="debug-until" type="datetime-local" step="1"></label>
<button data-action="UNAVAILABLE">Мастер выбыл</button>
<label>Новое модельное время<input id="debug-time" type="datetime-local" step="1"></label>
<button data-action="TICK">Перевести время</button></div>
<p><a id="debug-map" target="_blank" rel="noopener">Открыть карту с автообновлением</a></p>
<pre id="debug-result" role="status"></pre>`;
document.body.insertBefore(section,document.querySelector('script'));
let busy=false;
const local=value=>new Date(Date.parse(value)+5*3600000).toISOString().slice(0,19);
const clock=value=>local(value).replace('T',' ');
async function snapshot(){
 const date=$('date').value;
 $('debug-map').href='/map?debug=1&date='+encodeURIComponent(date);
 try{
  const response=await fetch('/api/ui/days/'+encodeURIComponent(date));const day=await response.json();
  if(!response.ok)throw new Error(day.error?.message||'День ещё не загружен');
  $('debug-clock').textContent=`Модельное время: ${clock(day.model_now)} · версия плана: ${day.plan?.plan_version??'не рассчитан'}`;
  $('debug-time').value=local(day.model_now);
  const visits=new Map((day.plan?.routes||[]).flatMap(r=>r.stops.filter(s=>s.type==='VISIT').map(s=>[s.order_id,{...s,staff:r.staff_id}])));
  const cancelled=new Set((day.plan?.cancelled||[]).map(c=>c.order_id));const old=$('debug-order').value;
  $('debug-order').replaceChildren(...day.orders.map(o=>{
   const v=visits.get(o.order_id);const state=cancelled.has(o.order_id)?'Отменён':!v?'Не назначен':Date.parse(v.end)<=Date.parse(day.model_now)?'Завершён по плану':Date.parse(v.start)<=Date.parse(day.model_now)?'В работе по плану':'Назначен';
   return new Option(`${o.order_id} · ${state}${v?' · '+v.staff+' · '+clock(v.start):''} · ${o.address}`,o.order_id);
  }));
  if([...$('debug-order').options].some(o=>o.value===old))$('debug-order').value=old;
 }catch(error){$('debug-clock').textContent=error.message;$('debug-order').replaceChildren();}
}
async function act(action){
 if(busy)return;
 if(action!=='TICK'&&!$('debug-order').value){$('debug-result').textContent='Выберите наряд.';return;}
 if(['FINISH','CANCEL','UNAVAILABLE','TICK'].includes(action)&&!confirm('Изменить состояние выбранной смены? Перевод времени затрагивает всех сотрудников; назад его вернуть нельзя.'))return;
 busy=true;for(const b of section.querySelectorAll('button'))b.disabled=true;
 $('debug-result').textContent='Событие отправляется, план пересчитывается…';
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),60000);
 try{
  const body={date:$('date').value,action,order_id:$('debug-order').value,minutes:$('debug-minutes').value};
  if(action==='TICK')body.time=$('debug-time').value+'+05:00';
  if(action==='UNAVAILABLE'&&$('debug-until').value)body.until=$('debug-until').value+'+05:00';
  const r=await fetch('/debug/event',{method:'POST',signal:controller.signal,headers:{'Content-Type':'application/json','X-Requested-With':'request-panel'},body:JSON.stringify(body)});
  const result=await r.json();if(!r.ok)throw new Error(result.error?.message||result.error||'Событие отклонено');
  $('debug-result').textContent=JSON.stringify(result,null,2);await snapshot();$('date').dispatchEvent(new Event('change'));
 }catch(error){$('debug-result').textContent=error.name==='AbortError'?'Ответ задерживается. Обновите снимок: событие могло сохраниться.':error.message;}
 finally{clearTimeout(timer);busy=false;for(const b of section.querySelectorAll('button'))b.disabled=false;}
}
for(const b of section.querySelectorAll('[data-action]'))b.onclick=()=>act(b.dataset.action);
$('debug-refresh').onclick=snapshot;$('date').addEventListener('change',snapshot);
// Refresh after order creation without coupling to the form implementation.
new MutationObserver(()=>{if(!$('result').textContent.includes('Подбирается'))snapshot();}).observe($('result'),{childList:true});
snapshot();
import './load.js';
