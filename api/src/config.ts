function readPort(): number {
  const port = Number(process.env.PORT ?? 8080);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('PORT must be an integer between 1 and 65535');
  }
  return port;
}
export const config = {
  port: readPort(),
  databaseUrl: process.env.DATABASE_URL?.trim() || undefined,
  logLevel: process.env.LOG_LEVEL?.trim() || 'info',
} as const;

