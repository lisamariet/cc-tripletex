FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/*.py app/
COPY app/handlers/ app/handlers/
COPY app/error_patterns.json app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
