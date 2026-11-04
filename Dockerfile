FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=8080 \
    GEM_SOLVER=auto GEM_THREADS=2 GEM_PROCESSES=2 GEM_HOSTED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8080

# One worker: loaded models are cached in process memory. Threads serve concurrent requests.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
