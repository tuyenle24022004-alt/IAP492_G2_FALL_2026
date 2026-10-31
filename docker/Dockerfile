# Image chạy mã hóa THẬT: OpenFHE (xMK-CKKS) chỉ có wheel cho Linux x86_64 nên không chạy được trên Windows.
# Build (từ thư mục gốc dự án):  docker compose -f docker/docker-compose.yml build bs   (hoặc để run_fl_docker.py tự build)
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
ENV PYTHONIOENCODING=utf-8 SECURE_FL_BACKEND=openfhe
