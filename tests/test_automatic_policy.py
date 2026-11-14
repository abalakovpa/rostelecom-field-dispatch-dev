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
