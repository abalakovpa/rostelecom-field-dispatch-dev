import unittest
from copy import deepcopy
from planner_openapi import plan_openapi
from test_planner_openapi import sample,at

class InventoryRoutesTest(unittest.TestCase):
    def new_order_during_visit(self,routers):
        reference,matrix,full=sample()
        day=deepcopy(full);day['orders']=day['orders'][:1]
        day['_equipment_start_by_staff']={'ST-001':{'ONT':0,'ROUTER':routers,'STB':0}}
        initial=plan_openapi(reference,matrix,day)
        added=deepcopy(full['orders'][1]);added['registered_at']=at('09:15:00')
        day['orders'].append(added);day['now']=at('09:15:00')
        event={'type':'NEW_ORDER','event_id':'MID-VISIT','timestamp':day['now'],'order':added}
        updated=plan_openapi(reference,matrix,day,previous=initial,event=event)
        self.assertFalse(updated['unassigned'])
        first=next(s for s in initial['routes'][0]['stops'] if s['type']=='VISIT')
        frozen=next(s for s in updated['routes'][0]['stops'] if s.get('order_id')==first['order_id'])
        for key in ('start','end','arrival','location_id'):self.assertEqual(first[key],frozen[key])
        self.assertEqual(reference['staff'][0]['equipment_start']['ROUTER'],1)
        return updated['routes'][0]['stops']
    def test_enough_stock_goes_directly_to_new_order_without_depot(self):
        stops=self.new_order_during_visit(2)
        self.assertFalse(any(s['type']=='RESTOCK' for s in stops))
        self.assertEqual(len([s for s in stops if s['type']=='VISIT']),2)
    def test_depleted_stock_adds_depot_between_visits(self):
        stops=self.new_order_during_visit(1)
        meaningful=[s['type'] for s in stops if s['type'] in ('VISIT','RESTOCK')]
        self.assertEqual(meaningful,['VISIT','RESTOCK','VISIT'])
    def test_equal_service_start_prefers_shorter_restock_trip(self):
        reference,matrix,day=sample();day['orders']=day['orders'][1:2]
        reference['staff'][0]['equipment_start']={'ONT':0,'ROUTER':0,'STB':0}
        second=deepcopy(reference['service_centers'][0]);second['service_center_id']='SC-02'
        reference['service_centers'].insert(0,second)
        # SC-02 is a longer trip; the original center must win despite list order.
        matrix['points'].append('SC-02')
        for key in ['durations_sec','distances_m']:
            for row in matrix[key]:row.append(1200)
            matrix[key].append([1200,1200,1200,0])
        result=plan_openapi(reference,matrix,day)
        restock=next(s for s in result['routes'][0]['stops'] if s['type']=='RESTOCK')
        self.assertEqual(restock['location_id'],'SC-01')
