import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'planner-service'))
import unittest
from copy import deepcopy
from policies import calculate,groups_for
from test_planner_openapi import sample,at
from planner_openapi import plan_openapi

class AutomaticPolicyTest(unittest.TestCase):
    def test_later_slot_is_selected_after_temporary_outage(self):
        reference,matrix,day=sample();day['orders']=day['orders'][:2]
        previous=plan_openapi(reference,matrix,day)
        event={'event_id':'OUT-AUTO','type':'STAFF_UNAVAILABLE','timestamp':at('10:20:00'),'staff_id':'ST-001','until':at('14:00:00'),'reason':'ILLNESS'}
        day['now']=event['timestamp'];original=deepcopy(day)
        result=calculate(dict(reference=reference,matrix=matrix,day=day,previous_plan=previous,event=event,time_limit_sec=2))
        self.assertEqual(day,original)
        self.assertTrue(result['_order_updates'])
        update=result['_order_updates'][0]
        self.assertEqual(update['order_id'],day['orders'][1]['order_id'])
        self.assertGreater(update['slot']['start'],update['old_slot']['start'])
        self.assertTrue(any(s.get('order_id')==update['order_id'] for r in result['routes'] for s in r['stops']))
        self.assertTrue(any(a.get('applied') and a['suggested_action']=='RESCHEDULE' for a in result['alerts']))
    def test_fourth_incident_order_preserves_group_identity(self):
        reference,matrix,day=sample();reference['work_types'][0]['pgp_relevant']=True
        for i,o in enumerate(day['orders']):o['registered_at']=at(f'08:{i*10:02}:00')
        groups=groups_for(reference,day,None,[]);self.assertEqual(len(groups),1)
        original=deepcopy(groups)
        fourth=deepcopy(day['orders'][0]);fourth['order_id']='ORD-20261026-0004';fourth['registered_at']=at('09:10:00');day['orders'].append(fourth)
        updated=groups_for(reference,day,{'incident_groups':groups},[])
        self.assertEqual(updated[0]['group_id'],groups[0]['group_id']);self.assertEqual(updated[0]['detected_at'],groups[0]['detected_at'])
        self.assertEqual(len(updated[0]['order_ids']),4);self.assertEqual(groups,original)
    def test_equipment_shortage_inserts_restock(self):
        reference,matrix,day=sample();reference['staff'][0]['equipment_start']={'ONT':0,'ROUTER':0,'STB':0}
        result=calculate(dict(reference=reference,matrix=matrix,day=day,time_limit_sec=1))
        route=result['routes'][0]['stops'];self.assertTrue(any(s['type']=='RESTOCK' for s in route))
    def test_sufficient_equipment_needs_no_restock_for_single_visit(self):
        reference,matrix,day=sample();day['orders']=day['orders'][:1]
        result=calculate(dict(reference=reference,matrix=matrix,day=day,time_limit_sec=1))
        self.assertFalse(any(s['type']=='RESTOCK' for r in result['routes'] for s in r['stops']))

class FutureCalendarTest(unittest.TestCase):
    def request(self,occupied=False):
        from datetime import timedelta
        reference,matrix,day=sample();day['orders']=day['orders'][:2]
        for o in day['orders']:o['deadline']='2026-10-27T18:00:00+05:00'
        previous=plan_openapi(reference,matrix,day)
        event={'event_id':'NEXT-DAY','type':'STAFF_UNAVAILABLE','timestamp':at('10:20:00'),'staff_id':'ST-001','until':None,'reason':'ILLNESS'}
        day['now']=event['timestamp'];calendar={}
        if occupied:
            target=deepcopy(day);target['date']='2026-10-27';target['now']='2026-10-27T00:00:00+05:00';target['orders']=target['orders'][:1]
            order=target['orders'][0];order['order_id']='ORD-20261027-0100'
            order['slot']={k:v.replace('2026-10-26','2026-10-27') for k,v in order['slot'].items()};order['latest_start']=order['latest_start'].replace('2026-10-26','2026-10-27')
            calendar[target['date']]={'input':target,'plan':plan_openapi(reference,matrix,target),'events':[]}
        return dict(reference=reference,matrix=matrix,day=day,previous_plan=previous,event=event,calendar=calendar,time_limit_sec=3)
    def test_next_day_reservation_preserves_existing_appointments(self):
        request=self.request(True);before=deepcopy(request)
        result=calculate(request);self.assertEqual(request,before)
        self.assertTrue(result['_future_transfers'])
        transfer=result['_future_transfers'][0];self.assertEqual(transfer['to_date'],'2026-10-27')
        old=request['calendar']['2026-10-27']['plan']
        booked={(r['staff_id'],s['order_id'],s['start'],s['end']) for r in old['routes'] for s in r['stops'] if s['type']=='VISIT'}
        actual={(r['staff_id'],s['order_id'],s['start'],s['end']) for r in transfer['target_plan']['routes'] for s in r['stops'] if s['type']=='VISIT'}
        self.assertTrue(booked<=actual)
        self.assertTrue(any(row[1]==transfer['order_id'] for row in actual))
        self.assertFalse(any(u['order_id']==transfer['order_id'] for u in result['unassigned']))
    def test_overdue_order_still_receives_next_day_appointment(self):
        request=self.request()
        for o in request['day']['orders']:o['deadline']=at('18:00:00')
        result=calculate(request)
        self.assertTrue(result['_future_transfers'])
        self.assertEqual(result['_future_transfers'][0]['to_date'],'2026-10-27')


class AfterShiftTest(unittest.TestCase):
    def test_2100_request_moves_to_next_day(self):
        reference,matrix,day=sample();day['orders']=day['orders'][:1]
        order=day['orders'][0];order['slot']={'start':at('21:00:00'),'end':at('23:00:00')};order['latest_start']=at('21:10:00');order['deadline']='2026-10-29T18:00:00+05:00'
        result=calculate(dict(reference=reference,matrix=matrix,day=day,time_limit_sec=2))
        self.assertTrue(result['_future_transfers'])
        transfer=result['_future_transfers'][0];self.assertEqual(transfer['to_date'],'2026-10-27')
        visit=next(s for r in transfer['target_plan']['routes'] for s in r['stops'] if s.get('order_id')==order['order_id'])
        self.assertGreaterEqual(visit['start'],'2026-10-27T09:00:00+05:00');self.assertLessEqual(visit['end'],'2026-10-27T18:00:00+05:00')

class SameDayPriorityTest(unittest.TestCase):
    def test_free_time_today_is_used_before_future_dates(self):
        reference,matrix,day=sample();day['orders']=day['orders'][:1]
        request=dict(reference=reference,matrix=matrix,day=day,time_limit_sec=1)
        result=calculate(request)
        self.assertFalse(result['_future_transfers'])
        visit=next(s for r in result['routes'] for s in r['stops'] if s['type']=='VISIT')
        self.assertTrue(visit['end'].startswith(day['date']))
