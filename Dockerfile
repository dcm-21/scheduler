FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Manila DB_PATH=/data/request-system.db PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY templates templates
COPY static static
VOLUME /data
EXPOSE 5051
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5051", "app:app"]
