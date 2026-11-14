export const DISPLAY_TIME_ZONE='Asia/Yekaterinburg';
export const time=value=>new Intl.DateTimeFormat('ru-RU',{hour:'2-digit',minute:'2-digit',timeZone:DISPLAY_TIME_ZONE}).format(new Date(value));
export const fullTime=value=>new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone:DISPLAY_TIME_ZONE}).format(new Date(value));
// Staff shift clocks and the interface both use the dataset city (UTC+5).
export const shiftTime=(date,clock)=>time(`${date}T${clock.slice(0,5)}:00+05:00`);
export function warningIndicator(plan,alerts=plan?.alerts||[]){
 if(!plan)return {state:'unknown',count:0,label:'Предупреждения: план ещё не рассчитан'};
 const count=alerts.filter(a=>a.status==='ACTIVE').length;
 return {state:count?'alert':'clear',count,label:count?`Активных предупреждений: ${count}`:'Активных предупреждений нет'};
}
