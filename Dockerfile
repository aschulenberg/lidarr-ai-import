FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY lidarr_ai_import ./lidarr_ai_import

RUN mkdir -p /app/data

ENV DB_PATH=/app/data/lidarr_ai_import.db

ENTRYPOINT ["python", "main.py"]
CMD ["serve"]
