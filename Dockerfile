FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/issues.db \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY issue_tracker ./issue_tracker

RUN mkdir -p /data

EXPOSE 8080
VOLUME ["/data"]

CMD ["python", "app.py"]
