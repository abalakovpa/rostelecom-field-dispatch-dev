import {employeeFitsOrder} from './order-options.js';

export function randomSource(seed){
 let state=Number(seed)>>>0;
 return ()=>{state=(state+0x6D2B79F5)>>>0;let v=state;v=Math.imul(v^(v>>>15),v|1);v^=v+Math.imul(v^(v>>>7),v|61);return ((v^(v>>>14))>>>0)/4294967296;};
}
const choose=(items,rng)=>items[Math.floor(rng()*items.length)];
function shuffled(items,rng){const a=[...items];for(let i=a.length-1;i>0;i--){const j=Math.floor(rng()*(i+1));[a[i],a[j]]=[a[j],a[i]];}return a;}

export function generateRequests(catalog,{count,date,seed,staffIds,pin=false}){
 if(!Number.isInteger(count)||count<1||count>10000)throw Error('Количество заявок: целое число от 1 до 10000');
 if(!/^\d{4}-\d{2}-\d{2}$/.test(date))throw Error('Выберите дату');
 const rng=randomSource(seed);
 const pairs=catalog.buildings.flatMap(building=>catalog.works.map(work=>({building,work})));
 const staff=catalog.staff.filter(p=>staffIds.includes(p.staff_id)).map(person=>({person,pairs:pairs.filter(({building,work})=>employeeFitsOrder(person,building,work))}));
 const eligible=staff.filter(s=>s.pairs.length);
 if(!eligible.length)throw Error('У выбранных сотрудников нет совместимых адресов и работ');
 const requests=[];let cycle=[];
 for(let i=0;i<count;i++){
  if(!cycle.length)cycle=shuffled(eligible,rng);
  const {person,pairs}=cycle.pop(),{building,work}=choose(pairs,rng);
  const [h,m]=(person.shift?.start||person.shift_start||'09:00').split(':').map(Number);
  const [eh,em]=(person.shift?.end||person.shift_end||'18:00').split(':').map(Number);
  const first=Math.ceil((h*60+m)/30),last=Math.max(first,Math.floor((eh*60+em-120)/30));
  const minutes=(first+Math.floor(rng()*(last-first+1)))*30;
  requests.push({date,time:`${String(Math.floor(minutes/60)).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`,building_id:building.building_id,work_type_code:work.code,staff_id:pin?person.staff_id:''});
 }
 return {requests,eligibleStaffIds:eligible.map(s=>s.person.staff_id),skippedStaffIds:staff.filter(s=>!s.pairs.length).map(s=>s.person.staff_id)};
}
