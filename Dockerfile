# One leader-election node. The algorithm code has no third-party dependencies.
FROM python:3.12-slim
WORKDIR /app
COPY bully ./bully
ENV PYTHONUNBUFFERED=1 BULLY_PORT=9000 BULLY_STATE_DIR=/data
EXPOSE 9000/udp
ENTRYPOINT ["python", "-m", "bully", "node"]
