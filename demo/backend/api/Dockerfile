# DEMONSTRATION ONLY: not the team Fastify server.
FROM python:3.12-slim
WORKDIR /app
COPY demo/requirements.txt ./demo/requirements.txt
RUN pip install --no-cache-dir -r demo/requirements.txt
COPY demo/backend ./demo/backend
COPY web ./web
COPY api_spec.yaml .
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "api.main:app", "--app-dir", "demo/backend", "--host", "0.0.0.0", "--port", "8080"]
