"""Validate against the original organizer schemas without maintaining a second copy."""
from functools import lru_cache
import yaml
from jsonschema import Draft7Validator,FormatChecker
from .settings import ROOT
from planner.events import EventError

def convert(value):
    if isinstance(value,list):return [convert(v) for v in value]
    if not isinstance(value,dict):return value
    result={k:convert(v) for k,v in value.items() if k not in ('nullable','discriminator','example')}
    return {'anyOf':[result,{'type':'null'}]} if value.get('nullable') else result

@lru_cache
def validator(name):
    document=yaml.safe_load((ROOT/'api_spec.yaml').read_text(encoding='utf-8'))
    return Draft7Validator(dict(convert({'components':document['components']}),**{'$ref':'#/components/schemas/'+name}),format_checker=FormatChecker())

def validate(name,payload):
    err=next(validator(name).iter_errors(payload),None)
    if err:raise EventError('BAD_REQUEST',f'Некорректное поле: {".".join(map(str,err.absolute_path)) or name}.',422)
