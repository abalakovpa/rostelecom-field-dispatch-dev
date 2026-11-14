"""Validate UI examples without importing FastAPI or the prototype planner."""
from pathlib import Path
from copy import deepcopy
import json
import pytest
import yaml
from jsonschema import Draft7Validator,FormatChecker

ROOT=Path(__file__).resolve().parents[1]
OFFICIAL=yaml.safe_load((ROOT/'api_spec.yaml').read_text(encoding='utf-8'))
UI=yaml.safe_load((ROOT/'contracts/ui-api.yaml').read_text(encoding='utf-8'))
EXAMPLES=json.loads((ROOT/'contracts/examples/manifest.json').read_text(encoding='utf-8'))

def convert(value):
    if isinstance(value,list):return [convert(v) for v in value]
    if not isinstance(value,dict):return value
    result={k:convert(v) for k,v in value.items() if k not in ('nullable','discriminator','example')}
    if '$ref' in result:result['$ref']=result['$ref'].replace('../api_spec.yaml#','#')
    return {'anyOf':[result,{'type':'null'}]} if value.get('nullable') else result

def validator(name):
    schemas=deepcopy(OFFICIAL['components']['schemas'])|deepcopy(UI['components']['schemas'])
    return Draft7Validator(convert(dict(components=dict(schemas=schemas),**{'$ref':'#/components/schemas/'+name})),format_checker=FormatChecker())

@pytest.mark.parametrize('example',EXAMPLES,ids=lambda e:e['file'])
def test_documented_exchange_conforms_to_contract(example):
    payload=json.loads((ROOT/'contracts/examples'/example['file']).read_text(encoding='utf-8'))
    validator(example['schema']).validate(payload)

def test_ui_contract_does_not_redefine_official_endpoints_or_plan():
    assert all(path.startswith('/api/ui/') for path in UI['paths'])
    assert 'Plan' not in UI['components']['schemas']
    assert UI['components']['schemas']['UiDay']['properties']['plan']['allOf'][0]['$ref']=='../api_spec.yaml#/components/schemas/Plan'

def test_planned_ui_response_can_omit_official_optional_summary():
    payload=json.loads((ROOT/'contracts/examples/day-planned.json').read_text(encoding='utf-8'))
    payload['plan'].pop('summary',None)
    validator('UiDay').validate(payload)
