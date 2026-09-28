FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Start from the project root so the `src` package is importable. Running from
# /app/src puts /app/src on sys.path instead of /app, which breaks every
# `from src.core...` import in the codebase.
ENV PYTHONUNBUFFERED=1 \
    APP_PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn src.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
