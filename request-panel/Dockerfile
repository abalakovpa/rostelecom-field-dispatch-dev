FROM python:3.12-slim
WORKDIR /app
COPY request-panel ./panel
COPY data/service_centers.json data/staff.json data/access_nodes.json data/work_types.csv data/travel_matrix.json ./data/
USER nobody
EXPOSE 8082
CMD ["python", "panel/server.py"]
