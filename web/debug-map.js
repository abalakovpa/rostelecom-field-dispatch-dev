// Loaded only by the debug panel's map proxy when debug=1.
const requested=new URLSearchParams(location.search).get('date');
let selected=false,last='',running=false;
const badge=document.createElement('p');badge.textContent='Режим отладки · автообновление каждые 3 секунды';badge.style.cssText='position:fixed;bottom:0;right:8px;background:white;padding:8px;z-index:2000;font:12px system-ui';document.body.append(badge);
setInterval(async()=>{
 if(running||document.hidden)return;
 const day=document.getElementById('day'),refresh=document.getElementById('refresh');
 if(!day||!refresh||refresh.disabled)return;
 if(!selected&&requested){
  if(![...day.options].some(o=>o.value===requested))return;
  day.value=requested;day.dispatchEvent(new Event('change'));selected=true;return;
 }
 if(!day.value)return;running=true;
 try{
  const response=await fetch('/api/ui/days/'+encodeURIComponent(day.value),{signal:AbortSignal.timeout(10000)});
  if(!response.ok)throw new Error('HTTP '+response.status);
  const snapshot=await response.json(),key=JSON.stringify([snapshot.date,snapshot.model_now,snapshot.plan?.plan_version]);
  if(key!==last){last=key;if(!refresh.disabled)refresh.click();}
  badge.textContent='Отладка · данные проверены '+new Date().toLocaleTimeString('ru-RU');
 }catch(error){badge.textContent='Отладка · нет обновления: '+error.message;}finally{running=false;}
},3000);
