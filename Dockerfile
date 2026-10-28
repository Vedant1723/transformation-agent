FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    AUTH_MODE=gateway \
    LOG_LEVEL=INFO \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2

WORKDIR /app/backend

# CPU PyTorch supports the existing model and feedback-training worker.
COPY backend/requirements.txt backend/requirements-training.txt ./
RUN python -m pip install -r requirements.txt \
    && python -m pip install -r requirements-training.txt \
       --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip check

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app

COPY --chown=app:app backend/app ./app
COPY --chown=app:app backend/scripts ./scripts
COPY --chown=app:app backend/alembic ./alembic
COPY --chown=app:app backend/alembic.ini ./alembic.ini
COPY --chown=app:app model-runs/expanded-resume-20260921-114948/ /app/model-runs/expanded-resume-20260921-114948/
RUN chown app:app /app/model-runs

USER app
EXPOSE 8000

# Dependency readiness is exposed separately at /transformation-agent/ready.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/transformation-agent/health', timeout=8)" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
