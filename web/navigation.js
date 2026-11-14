export function createNavigation(getMap){
 const rail=document.getElementById('workspace-nav'),toggle=document.getElementById('nav-toggle'),backdrop=document.getElementById('nav-backdrop');
 const labels={map:['Наряды и маршруты','Назначения сотрудников и адреса на выбранную дату'],timeline:['План смены по времени','Работы, дорога и перерывы сотрудников'],warnings:['Предупреждения','Активные сигналы и история за выбранную смену']};
 function close(){rail.classList.remove('expanded');rail.classList.add('dismissed');toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-label','Открыть рабочее пространство');backdrop.hidden=true;}
 rail.addEventListener('pointerenter',()=>rail.classList.remove('dismissed'));
 function show(view){
  if(!labels[view])return;
  for(const section of document.querySelectorAll('[data-panel]'))section.hidden=section.dataset.panel!==view;
  for(const button of rail.querySelectorAll('[data-view]')){
   const active=button.dataset.view===view;button.classList.toggle('active',active);
   if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
  }
  document.querySelector('h1').textContent=labels[view][0];document.querySelector('.heading p').textContent=labels[view][1];
  close();
  if(view==='map')requestAnimationFrame(()=>getMap()?.resize());
 }
 for(const button of rail.querySelectorAll('[data-view]'))button.addEventListener('click',()=>show(button.dataset.view));
 toggle.addEventListener('click',()=>{
  const open=!rail.classList.contains('expanded');rail.classList.toggle('expanded',open);toggle.setAttribute('aria-expanded',String(open));toggle.setAttribute('aria-label',open?'Закрыть рабочее пространство':'Открыть рабочее пространство');backdrop.hidden=!open;
 });
 backdrop.addEventListener('click',close);document.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
 return {show};
}
