// An existing shift must be replanned through an event, never rebuilt from zero.
export function planAction(day,eventId){
 const base=`/api/v1/days/${encodeURIComponent(day.date)}`;
 return day.plan
  ? {url:base+'/events',body:{event_id:eventId,type:'TIME_TICK',timestamp:day.model_now}}
  : {url:base+'/plan',body:{time_limit_sec:30}};
}
