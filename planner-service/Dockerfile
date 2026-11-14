FROM python:3.12-slim
WORKDIR /app
COPY planner.py planner_openapi.py ./
COPY planner-service/server.py ./server.py
USER nobody
EXPOSE 8090
CMD ["python", "server.py"]
COPY planner-service/policies.py ./policies.py
