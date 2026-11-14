"""Build an explicit, transactional pgAdmin import from the validated local files."""
import json
from collections import defaultdict
from pathlib import Path
from validate_data import main as validate, read, work_rows

ROOT=Path(__file__).resolve().parents[1]

def literal(value):
    if value is None:return 'NULL'
    if isinstance(value,bool):return 'TRUE' if value else 'FALSE'
    if isinstance(value,(int,float)):return str(value)
    if isinstance(value,dict):return literal(json.dumps(value,ensure_ascii=False,separators=(',',':')))+'::jsonb'
    if isinstance(value,list):return 'ARRAY['+','.join(literal(x) for x in value)+']'
    # All generated strings are data; single quotes are escaped, backslashes stay literal.
    return "'"+value.replace("'","''")+"'"

def main():
    validate() # Never export unchecked or manually corrupted files.
    output=['-- Generated synthetic data. Apply AFTER 001_initial.sql to an EMPTY dispatch schema.',
            '-- No plans/events are simulated by this import. Re-running is intentionally rejected.',
            'BEGIN;',"SET LOCAL search_path = dispatch, public;",
            'SET LOCAL standard_conforming_strings = on;',
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM service_centers) OR EXISTS (SELECT 1 FROM planning_days) OR EXISTS (SELECT 1 FROM training_orders) THEN RAISE EXCEPTION 'Import requires empty tables; no data was overwritten'; END IF; END $$;"]
    def insert(table,row):
        output.append(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join(literal(v) for v in row.values())});")
    centers=read('service_centers.json');staff=read('staff.json');nodes=read('access_nodes.json');works=work_rows()
    reference=dict(service_centers=centers,staff=staff,access_nodes=nodes,work_types=works)
    for center in centers:
        insert('service_centers',{k:v for k,v in center.items() if k!='opening_hours'}|
            dict(opening_open=center['opening_hours']['open'],opening_close=center['opening_hours']['close']))
    for person in staff:
        shift=person['shift']
        insert('staff',{k:v for k,v in person.items() if k!='shift'}|
            dict(shift_start=shift['start'],shift_end=shift['end'],break_duration_min=shift['break_duration_min'],
                 break_window_from=shift['break_window']['from'],break_window_to=shift['break_window']['to']))
    buildings={b['building_id']:b for node in nodes for b in node['buildings']}
    for building in buildings.values():insert('buildings',building)
    for node in nodes:
        insert('access_nodes',{k:v for k,v in node.items() if k!='buildings'})
        for b in node['buildings']:insert('access_node_buildings',dict(access_node_id=node['access_node_id'],building_id=b['building_id']))
    for work in works:insert('work_types',work)
    travel=read('travel_matrix.json');insert('travel_matrices',dict(matrix_id=travel['matrix_id'],payload=travel))
    days=defaultdict(list)
    for order in read('orders_train.json'):
        insert('training_orders',dict(order_id=order['order_id'],payload=order))
        days[order['slot']['start'][:10]].append({k:v for k,v in order.items() if k!='fact'})
    for day,orders in sorted(days.items()):
        now=day+'T08:30:00+05:00'
        insert('planning_days',dict(date=day,model_now=now,matrix_id=travel['matrix_id'],reference_snapshot=reference,
            input_snapshot=dict(date=day,now=now,orders=orders,absent_staff_ids=[])))
        for order in orders:
            insert('orders',dict(date=day)|{k:v for k,v in order.items() if k!='slot'}|
                dict(slot_start=order['slot']['start'],slot_end=order['slot']['end']))
    output+=['COMMIT;',"SELECT 'service_centers' AS entity, count(*) FROM dispatch.service_centers UNION ALL SELECT 'staff',count(*) FROM dispatch.staff UNION ALL SELECT 'orders',count(*) FROM dispatch.orders UNION ALL SELECT 'training_orders',count(*) FROM dispatch.training_orders;"]
    target=ROOT/'db'/'seeds'/'001_generated_data.sql';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text('\n'.join(output)+'\n',encoding='utf-8');print(f'SQL import created: {target}')

if __name__=='__main__':main()
