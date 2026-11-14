import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
const spec = parse(readFileSync(new URL('../spec/api_spec.yaml', import.meta.url), 'utf8'));
function convert(value: any): any {
  if (Array.isArray(value)) return value.map(convert);
  if (value === null || typeof value !== 'object') return value;
  const out: any = {};
  for (const [key, item] of Object.entries(value)) {
    if (['description', 'example', 'discriminator', 'nullable', 'xml'].includes(key)) continue;
    out[key] = key === '$ref' ? String(item).replace('#/components/schemas/', 'urn:dispatch:') : convert(item);
  }
  if (value.nullable) return { anyOf: [out, { type: 'null' }] };
  return out;
}
export const definitions: Record<string, any> = Object.fromEntries(
  Object.entries(spec.components.schemas).map(([name, schema]) => [name, { ...convert(schema), $id: `urn:dispatch:${name}` }]),
);
export const schemaRef = (name: string) => ({ $ref: `urn:dispatch:${name}` });

definitions.Plan!.additionalProperties = true;
