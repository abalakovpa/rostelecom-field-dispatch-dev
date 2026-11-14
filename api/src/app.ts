import { registerUi } from './ui.js';
import Fastify, { type FastifyError, type FastifyInstance } from 'fastify';
import { registerOfficialApi } from './official-api.js';
import { PostgresStore, type Store } from './store.js';
import { httpPlanner, type Planner } from './planning.js';
import { ApiError } from './errors.js';
import { healthRoutes } from './routes/health.js';
export function buildApp(store: Store = new PostgresStore(), planner: Planner = httpPlanner): FastifyInstance {
  const app = Fastify({
    bodyLimit: 100 * 1024 * 1024,
    requestTimeout: 330000,
    logger: {level: process.env.LOG_LEVEL ?? 'info'},
    ajv: {customOptions: {removeAdditional: true, coerceTypes: false, useDefaults: false, strict: false}},
  });
  app.setErrorHandler((error: FastifyError, request, reply) => {
    if (error.validation) return reply.code(400).send({error:{code:'BAD_REQUEST',message:'Request does not match schema',details:error.validation.map(issue=>({field:issue.instancePath,message:issue.message ?? 'Invalid value'}))}});
    if (error instanceof ApiError) return reply.code(error.statusCode).send({error:{code:error.code,message:error.message}});
    if (error.statusCode && error.statusCode < 500) return reply.code(error.statusCode).send({error:{code:'BAD_REQUEST',message:error.message}});
    request.log.error({err:error},'Request failed');
    return reply.code(500).send({error:{code:'INTERNAL_ERROR',message:'Internal server error'}});
  });
  app.setNotFoundHandler((_request,reply)=>reply.code(404).send({error:{code:'NOT_FOUND',message:'Route not found'}}));
  app.register(healthRoutes);
  registerOfficialApi(app,store,planner);
  registerUi(app,store);
  return app;
}


