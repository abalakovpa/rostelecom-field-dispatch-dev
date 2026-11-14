"""Deadline rules for generated panel orders; input API deadlines remain untouched."""
from datetime import datetime,timedelta,timezone
LOCAL=timezone(timedelta(hours=5))
def calculate_deadline(work,registered_at,slot_end,is_repeat=False):
    kind=work['deadline_kind']
    if kind=='SLOT':return slot_end
    registered=datetime.fromisoformat(registered_at).astimezone(LOCAL)
    value=work.get('repeat_deadline_value') if is_repeat else None
    if value is None:value=work['deadline_value']
    if not isinstance(value,int) or value<0:raise ValueError('Invalid deadline rule')
    if kind=='HOURS':return (registered+timedelta(hours=value)).isoformat()
    if kind=='WORKING_DAYS':
        # Current demo calendar: Monday-Friday, public holidays not supplied.
        result=registered
        while value:
            result+=timedelta(days=1)
            if result.weekday()<5:value-=1
        return result.isoformat()
    raise ValueError('Unknown deadline kind')
