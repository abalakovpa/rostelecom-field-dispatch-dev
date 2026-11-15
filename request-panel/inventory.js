const $=id=>document.getElementById(id),kinds=['ONT','ROUTER','STB'];
const demand=document.createElement('fieldset');demand.innerHTML='<legend>Оборудование для этой заявки</legend><p>Количество расходуется при начале визита. Нехватка у мастера требует поездки за пополнением.</p>';
for(const k of kinds){const label=document.createElement('label');label.textContent=k+' ';const input=document.createElement('input');input.type='number';input.id='equipment-demand-'+k;input.min=0;input.max=10000;input.required=true;input.value=k==='ROUTER'?1:0;input.oninput=()=>document.dispatchEvent(new Event('equipment-change'));label.append(input);demand.append(label);}
document.querySelector('form').insertBefore(demand,document.querySelector('form button'));
export function requiredEquipment(){return Object.fromEntries(kinds.map(k=>[k,Number($('equipment-demand-'+k).value)]));}
export function setEquipmentDefaults(building){for(const k of kinds)$('equipment-demand-'+k).value=k==='ROUTER'?1:k==='ONT'&&building?.technology==='PON'?1:0;}

const panel=document.createElement('section');panel.innerHTML=`<hr><h2>Оборудование сотрудников</h2>
<p>Остаток показан на модельное время выбранной даты. При визите оборудование списывается в начале работ; пополнение доступно после окончания остановки в СЦ.</p>
<button type="button" id="inventory-refresh">Обновить остатки</button>
<label>Сотрудник<select id="inventory-staff"></select></label><p id="inventory-current"></p>
<fieldset id="inventory-edit"><legend>Стартовый комплект выбранной смены</legend><p>Задаётся до создания заявок и событий. Не изменяет остальные дни и общие справочники.</p></fieldset>
<button type="button" id="inventory-save">Сохранить стартовый комплект</button><p id="inventory-status" role="status"></p>
<div style="overflow:auto"><table id="inventory-table" style="width:100%;border-collapse:collapse"></table></div>`;
document.body.insertBefore(panel,document.querySelector('script'));
for(const k of kinds){const label=document.createElement('label');label.textContent=k+' ';const input=document.createElement('input');input.type='number';input.id='equipment-start-'+k;input.min=0;input.max=10000;input.value=0;label.append(input);$('inventory-edit').append(label);}
let snapshot;
const counts=value=>kinds.map(k=>`${k}: ${value[k]}`).join(' · ');
function choose(){const person=snapshot?.staff.find(p=>p.staff_id===$('inventory-staff').value);if(!person)return;
 $('inventory-current').textContent=`Сейчас: ${counts(person.current)}. Вместимость после пополнения: ${counts(person.capacity)}.`;
 for(const k of kinds){$('equipment-start-'+k).value=person.initial[k];$('equipment-start-'+k).max=person.capacity[k];}
 $('inventory-edit').disabled=!snapshot.editable;$('inventory-save').disabled=!snapshot.editable;
}
async function refresh(){try{
 const r=await fetch('/api/ui/days/'+encodeURIComponent($('date').value)+'/inventory');const data=await r.json();if(!r.ok)throw Error(data.error?.message||'Не удалось получить остатки');snapshot=data;
 const old=$('inventory-staff').value;$('inventory-staff').replaceChildren(...data.staff.map(p=>new Option(`${p.staff_id} · ${p.display_name||''}`,p.staff_id)));if(data.staff.some(p=>p.staff_id===old))$('inventory-staff').value=old;
 $('inventory-status').textContent=data.editable?'Стартовый комплект можно задать до заявок.':'Смена уже используется: стартовый комплект закрыт для редактирования. Пополнение выполняется маршрутом.';
 const table=$('inventory-table');table.replaceChildren();
 const header=document.createElement('tr');for(const text of ['Сотрудник','В начале смены','Остаток сейчас','После пополнения','Пополнения в плане']){const th=document.createElement('th');th.textContent=text;th.style.cssText='padding:8px;text-align:left;border-bottom:1px solid #ccc';header.append(th);}table.append(header);
 for(const p of data.staff){const row=document.createElement('tr');for(const text of [p.staff_id,counts(p.initial),counts(p.current),counts(p.capacity),p.restocks.map(s=>`${s.location_id}: ${s.start} — ${s.end}`).join('; ')||'Не требуется']){const cell=document.createElement('td');cell.textContent=text;cell.style.cssText='padding:8px;border-bottom:1px solid #ddd';row.append(cell);}table.append(row);}choose();
 }catch(e){$('inventory-status').textContent=e.message;}}
$('inventory-staff').onchange=choose;$('inventory-refresh').onclick=refresh;$('date').addEventListener('change',refresh);
$('inventory-save').onclick=async()=>{const date=$('date').value,button=$('inventory-save');button.disabled=true;
 try{const r=await fetch('/api/ui/days/'+encodeURIComponent(date)+'/inventory',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'request-panel'},body:JSON.stringify({staff_id:$('inventory-staff').value,equipment_start:Object.fromEntries(kinds.map(k=>[k,Number($('equipment-start-'+k).value)]))})});const result=await r.json();if(!r.ok)throw Error(result.error?.message||'Не удалось сохранить');await refresh();$('date').dispatchEvent(new Event('change'));}catch(e){$('inventory-status').textContent=e.message;}finally{button.disabled=!snapshot?.editable;}};
new MutationObserver(()=>{if(!$('result').textContent.includes('Подбирается'))refresh();}).observe($('result'),{childList:true});
refresh();
