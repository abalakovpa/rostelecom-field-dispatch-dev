import {generateRequests} from '/static/load-generator.js';
import {createEventId} from '/static/uuid.js';
const $=id=>document.getElementById(id),box=document.createElement('section');
box.innerHTML=`<hr><h2>Нагрузка и массовое выбытие</h2>
<p>Все заявки поступают на дату из формы выше. Система сама выбирает исполнителей и переносит визиты. Одна операция выполняется за другой; большой прогон может занять много времени.</p>
<label>Количество заявок <input id="load-count" type="number" min="1" max="10000" value="100"></label>
<label>Число для повторения случайной выборки <input id="load-seed" type="number" min="0" max="4294967295" value="1"></label>
<label>Назначение<select id="load-mode"><option value="auto">Автоматическое — для проверки замен и переносов</option><option value="pin">Тестовое закрепление по сотрудникам — для заполнения их графиков</option></select></label>
<p>Генератор чередует совместимые наборы для выбранных мастеров. В автоматическом режиме их фактическую загрузку определяет планировщик; равномерное назначение всем не гарантируется.</p>
<fieldset><legend>Сотрудники для генерации и массового выбытия</legend>
<button type="button" id="staff-all">Выбрать всех</button> <button type="button" id="staff-none">Снять выделение</button>
<label>Выбрать случайных сотрудников <input id="staff-count" type="number" min="1" value="3"></label>
<button type="button" id="staff-random">Выделить указанное количество</button>
<p id="staff-selected" role="status"></p><div id="load-staff" style="max-height:280px;overflow:auto"></div></fieldset>
<p><button type="button" id="load-start">Создать случайные заявки</button> <button type="button" id="staff-out">Выбранные сотрудники выбыли</button></p>
<p>Для выбытия используется модельное время выбранной даты и поле «Мастер недоступен до» выше. Без конца интервала — до конца смены. Время само не продвигается.</p>
<button type="button" id="load-stop" disabled>Остановить после текущего запроса</button>
<button type="button" id="load-export" disabled>Скачать отчёт JSON</button>
<progress id="load-progress" value="0" max="1" style="width:100%"></progress>
<p id="load-status" role="status">Загрузка справочников…</p><div id="load-days"></div><pre id="load-log" style="max-height:300px;overflow:auto"></pre>`;
document.body.insertBefore(box,document.querySelector('script'));
let catalog,stopping=false,report=null;
const checked=()=>[...box.querySelectorAll('input[data-staff]:checked')].map(e=>e.dataset.staff);
function selection(){ $('staff-selected').textContent=`Выбрано: ${checked().length} из ${catalog?.staff.length||0}`; }
function errorText(data){return data?.error?.message||data?.error||'Ошибка ответа';}
async function post(path,body){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),60000);
 try{const response=await fetch(path,{method:'POST',signal:controller.signal,headers:{'Content-Type':'application/json','X-Requested-With':'request-panel'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok){const e=Error(errorText(data));e.status=response.status;throw e;}return data;}finally{clearTimeout(timer);}
}
function progress(){
 const ok=report.results.filter(r=>r.ok),assigned=ok.filter(r=>r.data.assignment),moved=assigned.filter(r=>r.data.assignment.date!==report.date);
 const masters=new Set(assigned.map(r=>r.data.assignment.staff_id));
 $('load-progress').value=report.results.length;
 $('load-status').textContent=`Обработано ${report.results.length}/${report.total} · успешно ${ok.length} · ошибок ${report.results.length-ok.length}${report.kind==='orders'?` · назначено ${assigned.length} · перенесено на другие дни ${moved.length} · без назначения ${ok.length-assigned.length} · задействовано мастеров ${masters.size}`:''}`;
 $('load-log').textContent=report.results.slice(-20).map(r=>`${r.index}. ${r.ok?'OK':'ОШИБКА'} ${r.data?.order_id||r.staff_id||''} ${r.data?.assignment?`${r.data.assignment.staff_id}: ${r.data.assignment.date} ${r.data.assignment.start}`:r.error||''}`).join('\n');
 $('load-days').replaceChildren();
 for(const date of [...new Set(assigned.map(r=>r.data.assignment.date))].sort()){
  const link=document.createElement('a');link.href='/map?debug=1&date='+date;link.target='_blank';link.rel='noopener';link.textContent=`План на ${date}`;link.style.marginRight='12px';$('load-days').append(link);
 }
}
async function run(kind,jobs,meta={}){
 const date=$('date').value;
 if(!jobs.length)throw Error('Выберите хотя бы одного сотрудника');
 if(!confirm(`${kind==='orders'?'Создать заявок':'Отправить событий выбытия'}: ${jobs.length}, дата ${date}? Изменится настоящая база.`))return;
 // Freeze controls across both panels to prevent overlapping debug operations.
 const controls=[...document.querySelectorAll('button,input,select')].map(e=>[e,e.disabled]);
 for(const [e] of controls)e.disabled=true;
 $('load-stop').disabled=false;stopping=false;
 report={kind,date,total:jobs.length,started_at:new Date().toISOString(),...meta,results:[]};
 $('load-progress').max=jobs.length;progress();
 try{
  for(let i=0;i<jobs.length&&!stopping;i++){
   const job=jobs[i];let result;
   try{
    // Only NEW_ORDER requests carry a stable request_id and can be retried safely.
    let data;
    try{data=await post(kind==='orders'?'/create':'/debug/event',job);}catch(e){
     if(kind==='orders'&&(!e.status||e.status>=500))data=await post('/create',job);else throw e;
    }
    result={index:i+1,ok:true,staff_id:job.staff_id,request:job,data};
   }catch(e){result={index:i+1,ok:false,staff_id:job.staff_id,request:job,error:e.message,uncertain:!e.status||e.status>=500};if(result.uncertain)stopping=true;}
   report.results.push(result);progress();
  }
 }finally{
  report.finished_at=new Date().toISOString();report.stopped=report.results.length<jobs.length;
  for(const [e,disabled] of controls)e.disabled=disabled;
  $('load-stop').disabled=true;$('load-export').disabled=false;
  $('load-status').textContent+=(report.stopped?' · остановлено':' · завершено');
  $('date').dispatchEvent(new Event('change'));
 }
}
$('load-stop').onclick=()=>{stopping=true;$('load-stop').disabled=true;};
$('load-export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`debug-${report.kind}-${report.date}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('load-start').onclick=async()=>{try{
 const generated=generateRequests(catalog,{count:Number($('load-count').value),date:$('date').value,seed:Number($('load-seed').value),staffIds:checked(),pin:$('load-mode').value==='pin'});
 await run('orders',generated.requests.map(body=>({...body,request_id:createEventId()})),{seed:$('load-seed').value,mode:$('load-mode').value,eligible_staff:generated.eligibleStaffIds,skipped_staff:generated.skippedStaffIds});
}catch(e){$('load-status').textContent=e.message;}};
$('staff-out').onclick=async()=>{try{const until=$('debug-until').value;
 await run('unavailable',checked().map(staff_id=>({date:$('date').value,action:'UNAVAILABLE',staff_id,...(until?{until:until+'+05:00'}:{})})));
}catch(e){$('load-status').textContent=e.message;}};
for(const [id,selected] of [['staff-all',true],['staff-none',false]])$(id).onclick=()=>{for(const e of box.querySelectorAll('[data-staff]'))e.checked=selected;selection();};
$('staff-random').onclick=()=>{
 const all=[...box.querySelectorAll('[data-staff]')],count=Number($('staff-count').value);
 if(!Number.isInteger(count)||count<1||count>all.length){$('staff-selected').textContent=`Укажите количество от 1 до ${all.length}`;return;}
 for(let i=all.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[all[i],all[j]]=[all[j],all[i]];}
 all.forEach((e,i)=>e.checked=i<count);selection();
};
async function loadCatalog(){
 $('load-start').disabled=true;$('staff-out').disabled=true;
 try{const response=await fetch('/catalog');if(!response.ok)throw Error('Не удалось получить справочники');catalog=await response.json();
  for(const person of catalog.staff){const label=document.createElement('label');label.style.cssText='display:block;margin:6px 0;font-size:14px';const input=document.createElement('input');input.type='checkbox';input.checked=true;input.dataset.staff=person.staff_id;input.onchange=selection;label.append(input,document.createTextNode(` ${person.staff_id} · ${person.display_name||''} · ${person.profiles.join(', ')} · ${person.technologies.join(', ')}`));$('load-staff').append(label);}
  selection();$('load-start').disabled=!catalog.staff.length;$('staff-out').disabled=!catalog.staff.length;$('load-status').textContent='Готово. Выберите количество заявок и нажмите кнопку генерации.';
 }catch(e){$('load-status').textContent=e.message;}
}
loadCatalog();
