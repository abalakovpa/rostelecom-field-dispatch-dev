"""Reproducible organizer-style HTTP run against the isolated project copy.

Replaces data in the copy. Requires its API on 127.0.0.1:8083 and PostgreSQL .env.
System time is used only for the report folder; all simulation time is explicit.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import dotenv_values
from api.contracts import validate
from api.repository import DemoRepository,PostgresRepository
from api.settings import Settings
from planner.validate import validate_plan

parse=datetime.fromisoformat
def read(name):return json.loads((ROOT/'data'/name).read_text(encoding='utf-8'))

class Run:
    def __init__(self,limit):
        assert ROOT.name=='dispatcher-next-2026-11-14','Run only in the project copy'
        env=dotenv_values(ROOT/'.env')
        assert env['POSTGRES_DB'].startswith('dispatcher_next'),'Refusing to modify another database'
        self.repo=PostgresRepository(Settings(host=env['POSTGRES_HOST'],port=int(env['POSTGRES_PORT']),
            database=env['POSTGRES_DB'],user=env['POSTGRES_USER'],password=env['POSTGRES_PASSWORD']))
        self.limit=limit
        self.ref=DemoRepository().full_reference();self.matrix=read('travel_matrix.json')
        self.out=ROOT/'data'/'qa'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.out.mkdir(parents=True,exist_ok=True)
        self.report=dict(status='running',database=env['POSTGRES_DB'],url='http://127.0.0.1:8083',
            plan_limit_sec=limit,requests=[],plans=[],events=[],skipped_triggers=[],failures=[],known_limitations=[])
        self.last_plan={};self.coverage=Counter();self.save()

    def save(self):
        (self.out/'report.json').write_text(json.dumps(self.report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    def call(self,method,path,payload=None,expected=200,limit=None):
        if limit is None and method=='POST' and path.endswith('/events'):limit=10
        raw=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None
        request=Request('http://127.0.0.1:8083'+path,data=raw,method=method,headers={'Content-Type':'application/json'})
        began=time.perf_counter()
        try:
            with urlopen(request,timeout=310) as response:status=response.status;data=json.load(response)
        except HTTPError as exc:status=exc.code;data=json.load(exc)
        elapsed=round((time.perf_counter()-began)*1000)
        self.report['requests'].append(dict(method=method,path=path,status=status,wall_ms=elapsed))
        if limit and elapsed>limit*1000:self.report['failures'].append(f'{method} {path}: {elapsed} ms exceeds {limit}s')
        assert status==expected,(method,path,status,data)
        if status!=200:validate('ErrorResponse',data)
        elif method=='PUT':validate('LoadResult',data)
        return data,elapsed

    def state(self,day):
        return self.repo.fetch('SELECT input_snapshot FROM dispatch.planning_days WHERE date=%s',(day,))[0]['input_snapshot']

    def snapshot(self,day):
        return dict(day=self.repo.fetch('SELECT * FROM dispatch.planning_days WHERE date=%s',(day,)),
            plans=self.repo.fetch('SELECT plan_version,payload FROM dispatch.plans WHERE date=%s ORDER BY plan_version',(day,)),
            events=self.repo.fetch('SELECT event_id,payload,result FROM dispatch.events WHERE date=%s ORDER BY event_id',(day,)),
            orders=self.repo.fetch('SELECT * FROM dispatch.orders WHERE date=%s ORDER BY order_id',(day,)))

    def check_plan(self,day,previous=None,event=None):
        plan,_=self.call('GET',f'/api/v1/days/{day}/plan',limit=30)
        validate('Plan',plan)
        state=self.state(day)
        validate_plan(self.ref,state,self.matrix,plan,previous,event)
        assert plan['as_of']==state['now']
        counts=Counter(s['order_id'] for r in plan['routes'] for s in r['stops'] if s['type']=='VISIT')
        counts.update(x['order_id'] for x in plan['unassigned'])
        counts.update(oid for g in plan['pgp_groups'] for oid in g['order_ids'])
        counts.update(x['order_id'] for x in plan['cancelled'])
        assert counts==Counter(o['order_id'] for o in state['orders'])
        for alert in (previous or {}).get('alerts',[]):
            new=next(a for a in plan['alerts'] if a['alert_id']==alert['alert_id'])
            assert new['created_at']==alert['created_at'],'Alert creation time was rewritten'
        orders={o['order_id']:o for o in state['orders']}
        visits=[s for r in plan['routes'] for s in r['stops'] if s['type']=='VISIT']
        late=[s['order_id'] for s in visits if parse(s['end'])>parse(orders[s['order_id']]['deadline'])]
        summary=dict(day=day,version=plan['plan_version'],as_of=plan['as_of'],orders=len(orders),visits=len(visits),
            unassigned=len(plan['unassigned']),pgp_orders=sum(len(g['order_ids']) for g in plan['pgp_groups']),
            cancelled=len(plan['cancelled']),alerts=len(plan['alerts']),late_completion_order_ids=late,
            travel_sec=sum(s.get('travel_sec',0) for r in plan['routes'] for s in r['stops']))
        self.report['plans'].append(summary)
        (self.out/f'{day}-v{plan["plan_version"]}.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
        self.last_plan[day]=plan;self.save()
        return plan

    def event(self,day,event,allow_lunch=False):
        validate('Event',event)
        prior=self.last_plan[day];before=self.snapshot(day)
        try:result,elapsed=self.call('POST',f'/api/v1/days/{day}/events',event,limit=10)
        except AssertionError as exc:
            args=exc.args[0]
            if allow_lunch and isinstance(args,tuple) and args[2]==409 and args[3].get('error',{}).get('code')=='UNAVAILABILITY_BREAK_CONFLICT':
                assert self.snapshot(day)==before
                self.report['known_limitations'].append(dict(event=event,code='UNAVAILABILITY_BREAK_CONFLICT',state_unchanged=True))
                self.save();return False
            raise
        validate('EventResult',result)
        assert result['accepted'] and not result['duplicate']
        assert result['event_id']==event['event_id'] and result['plan_version']==prior['plan_version']+1
        plan=self.check_plan(day,prior,event)
        after=self.snapshot(day)
        assert after['plans'][:-1]==before['plans'],'Saved plan history changed'
        assert len(after['events'])==len(before['events'])+1
        assert after['day'][0]['model_now']==parse(event['timestamp'])
        self.coverage[event['type']]+=1
        self.report['events'].append(dict(event=event,wall_ms=elapsed,processing_ms=result['processing_ms'],version=plan['plan_version']))
        print(f'{day} {event["type"]}: version {plan["plan_version"]}, {elapsed} ms',flush=True)
        self.save();return True

    def load(self):
        self.call('GET','/api/v1/health')
        self.call('PUT','/api/v1/reference',self.ref,limit=60)
        assert self.repo.days()==[],'The API and test connection refer to different databases'
        self.call('PUT','/api/v1/reference/travel-matrix',self.matrix,limit=60)
        orders=read('orders_train.json')
        for day in sorted({o['slot']['start'][:10] for o in orders}):
            now=day+'T08:30:00+05:00'
            payload=dict(date=day,now=now,orders=[o for o in orders if o['slot']['start'][:10]==day and parse(o['registered_at'])<=parse(now)])
            self.call('PUT',f'/api/v1/days/{day}',payload,limit=30)
            self.call('POST',f'/api/v1/days/{day}/plan',{'time_limit_sec':self.limit},limit=300)
            self.check_plan(day)
            print(f'{day}: initial plan checked ({len(payload["orders"])} orders)',flush=True)

    def scenario(self):
        scenario=read('events_example.json');day=scenario['date']
        events=deepcopy(scenario['events']);triggers=deepcopy(scenario.get('triggers',[]))
        while events or triggers:
            plan=self.last_plan[day];now=parse(self.state(day)['now']);candidates=[]
            for trigger in triggers:
                pair=next(((r,s) for r in plan['routes'] for s in r['stops'] if s.get('order_id')==trigger['order_id']),None)
                if not pair:continue
                route,stop=pair;at=parse(stop['start'])+timedelta(minutes=trigger['fire_after_start_min'])
                if at<now or at>=parse(stop['end']):continue
                event=dict(event_id=trigger['trigger_id'],type=trigger['type'],order_id=trigger['order_id'],staff_id=route['staff_id'],timestamp=at.isoformat())
                if trigger['type']=='VISIT_DELAYED':event['expected_end']=(parse(stop['end'])+timedelta(minutes=trigger['extra_duration_min'])).isoformat()
                else:event.update(actual_end=at.isoformat(),transferred_to=trigger['transferred_to'])
                candidates.append((at,event,trigger))
            if events:candidates.append((parse(events[0]['timestamp']),events[0],None))
            if not candidates:break
            _,event,trigger=min(candidates,key=lambda x:x[0])
            if trigger:triggers.remove(trigger)
            else:events.pop(0)
            self.event(day,event,allow_lunch=True)
        for trigger in triggers:
            self.report['skipped_triggers'].append(dict(trigger=trigger,reason='Target visit was not active/assigned long enough to fire in the evaluated plans'))
        self.save()

    def controlled(self):
        # A second, explicit API scenario guarantees coverage of visit-bound events
        # even when the example trigger's particular order remains unassigned.
        day='2026-10-13';prefix='QA-CONTROL-'
        def active_candidate(excluded=()):
            now=parse(self.state(day)['now'])
            rows=[(max(now,parse(s['start'])+timedelta(minutes=1)),r,s) for r in self.last_plan[day]['routes']
                for s in r['stops'] if s['type']=='VISIT' and s['order_id'] not in excluded
                and max(now,parse(s['start'])+timedelta(minutes=1))<parse(s['end'])]
            assert rows,'No eligible visit for coverage scenario'
            return min(rows,key=lambda x:(x[0],x[1]['staff_id']))
        at,route,stop=active_candidate()
        self.event(day,dict(event_id=prefix+'DELAY',type='VISIT_DELAYED',timestamp=at.isoformat(),staff_id=route['staff_id'],order_id=stop['order_id'],expected_end=(parse(stop['end'])+timedelta(minutes=15)).isoformat()))
        delayed=stop['order_id'];at,route,stop=active_candidate([delayed])
        self.event(day,dict(event_id=prefix+'TRANSFER',type='ORDER_TRANSFERRED',timestamp=at.isoformat(),staff_id=route['staff_id'],order_id=stop['order_id'],actual_end=at.isoformat(),transferred_to='STATION_EQUIPMENT'))
        # Retry, ID collision and out-of-order events must not write anything.
        accepted=self.report['events'][-1]['event'];before=self.snapshot(day)
        duplicate,_=self.call('POST',f'/api/v1/days/{day}/events',accepted)
        assert duplicate['duplicate'];assert self.snapshot(day)==before
        self.call('POST',f'/api/v1/days/{day}/events',dict(accepted,timestamp=(at+timedelta(seconds=1)).isoformat()),expected=409)
        self.call('POST',f'/api/v1/days/{day}/events',dict(event_id=prefix+'EARLY',type='TIME_TICK',timestamp=(at-timedelta(seconds=1)).isoformat()),expected=409)
        assert self.snapshot(day)==before
        self.report['idempotency_and_error_rollback']='passed'
        state=self.state(day);now=state['now']
        locked={s['order_id'] for r in self.last_plan[day]['routes'] for s in r['stops'] if s['type']=='VISIT' and parse(s['start'])<parse(now)}
        order=next(o for o in state['orders'] if o['order_id'] not in locked)
        self.event(day,dict(event_id=prefix+'CANCEL',type='ORDER_CANCELLED',timestamp=now,order_id=order['order_id'],reason='CUSTOMER_REQUEST'))
        assert any(c['order_id']==order['order_id'] for c in self.last_plan[day]['cancelled'])
        order=deepcopy(next(o for o in state['orders'] if parse(o['slot']['start'])>parse(now)+timedelta(hours=1)))
        order.update(order_id='ORD-20261013-9998',registered_at=now,is_repeat=False,previous_order_id=None)
        self.event(day,dict(event_id=prefix+'NEW',type='NEW_ORDER',timestamp=now,order=order))
        self.event(day,dict(event_id=prefix+'TICK',type='TIME_TICK',timestamp=(parse(now)+timedelta(minutes=1)).isoformat()))
        person=next(p for p in self.ref['staff'] if p['shift']['start']=='12:00')
        self.event(day,dict(event_id=prefix+'OUT',type='STAFF_UNAVAILABLE',timestamp=(parse(now)+timedelta(minutes=1)).isoformat(),staff_id=person['staff_id'],until=day+'T12:30:00+05:00',reason='VEHICLE_BREAKDOWN'))
        # Unknown objects are semantic errors, not malformed JSON.
        before=self.snapshot(day)
        self.call('POST',f'/api/v1/days/{day}/events',dict(event_id=prefix+'UNKNOWN',type='ORDER_CANCELLED',timestamp=self.state(day)['now'],order_id='ORD-20261013-9999',reason='CUSTOMER_REQUEST'),expected=422)
        assert self.snapshot(day)==before

    def finish(self):
        required={'NEW_ORDER','ORDER_CANCELLED','VISIT_DELAYED','ORDER_TRANSFERRED','STAFF_UNAVAILABLE','TIME_TICK'}
        assert required<=set(self.coverage),self.coverage
        manifest=json.loads((ROOT/'docs/copy_origin.json').read_text(encoding='utf-8'))
        changed=[rel for rel,digest in manifest['source_hashes'].items() if hashlib.sha256((Path(manifest['source'])/rel).read_bytes()).hexdigest()!=digest]
        assert not changed,changed
        self.report.update(event_type_coverage=dict(self.coverage),original_files_checked=len(manifest['source_hashes']),original_files_changed=changed)
        self.report['status']='failed' if self.report['failures'] else ('passed_with_known_limitation' if self.report['known_limitations'] else 'passed')
        self.save()
        (ROOT/'data/qa/latest.json').write_text(json.dumps(dict(directory=str(self.out),status=self.report['status']),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        lines=['# Сценарная проверка API','',f'Статус: **{self.report["status"]}**. Проверка копии, отдельная PostgreSQL, реальный HTTP.',
            '',f'Проверено планов: {len(self.report["plans"])}. Принято событий: {len(self.report["events"])}. Начальных дней: 10 (3500 нарядов).',
            f'Лимит первоначального расчёта: {self.limit} с; это функциональная проверка, не итоговая оценка качества оптимизации.',
            '', '| День | Версия | Визиты | Не назначено | В ПГП | Отменено | Предупреждения |', '|---|---:|---:|---:|---:|---:|---:|']
        latest={p['day']:p for p in self.report['plans']}
        for p in latest.values():lines.append(f'| {p["day"]} | {p["version"]} | {p["visits"]} | {p["unassigned"]} | {p["pgp_orders"]} | {p["cancelled"]} | {p["alerts"]} |')
        lines+=['','Проверены формат ответов, H1–H10, модельное время, учёт нарядов, неизменность старых версий, повторная доставка и откат отклонённых событий.',
            f'Максимальное время HTTP-обработки принятого события: {max(e["wall_ms"] for e in self.report["events"])} мс.',
            f'Не сработало условных триггеров примера: {len(self.report["skipped_triggers"])}; подробные причины в report.json. Дополнительный сценарий обеспечивает все шесть типов событий.',
            f'Известных отклонений по строгому правилу обеда: {len(self.report["known_limitations"])}. Правило не менялось.',
            f'Исходных файлов проверено: {len(manifest["source_hashes"])}; изменений нет.',
            '', 'Планы каждой версии и подробный журнал HTTP сохранены рядом с отчётом. Это проверка локального набора; скрытый валидатор организаторов здесь не запускался.']
        if self.report['failures']:lines+=['','Ошибки:']+['- '+f for f in self.report['failures']]
        (self.out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print(f'Report: {self.out}',flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-limit',type=int,default=5,choices=range(1,301))
    args=parser.parse_args();run=Run(args.plan_limit)
    try:
        run.load();run.scenario();run.controlled();run.finish()
    except Exception as exc:
        run.report['status']='failed';run.report['failures'].append(str(exc));run.save()
        print(f'FAILED: {exc}\nPartial report: {run.out}',flush=True)
        raise
    return int(run.report['status']=='failed')

if __name__=='__main__':raise SystemExit(main())
