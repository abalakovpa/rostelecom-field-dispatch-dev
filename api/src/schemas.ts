import { Type } from '@sinclair/typebox';
export const HealthResponse = Type.Object({
  status: Type.Union([Type.Literal('ok'), Type.Literal('degraded')]),
  service: Type.Literal('api'),
  db: Type.Union([Type.Literal('ok'), Type.Literal('down')]),
  ts: Type.String(),
});
