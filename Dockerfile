# Production-образ (ТЗ п.57).
# Для разработки — Dockerfile.dev с runserver и монтированием исходников.

# ---------- этап сборки ----------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Сборочные пакеты остаются в этом слое и в финальный образ не попадают
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && /opt/venv/bin/pip install --no-cache-dir gunicorn

# ---------- финальный образ ----------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_ENV=production \
    PROMETHEUS_MULTIPROC_DIR=/dev/shm/prometheus

WORKDIR /app

# Только рантайм: libpq для psycopg, curl для health-чека.
# Компиляторов в production-образе быть не должно.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

# Non-root: процесс, скомпрометированный через уязвимость в зависимости,
# не должен иметь прав root в контейнере.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R appuser:appuser /app

COPY --chown=appuser:appuser . /app/

USER appuser

# collectstatic на этапе сборки: в рантайме он требовал бы прав на запись
# и выполнялся бы на каждом старте каждой реплики.
RUN DJANGO_ENV=development SECRET_KEY=build-only \
    python manage.py collectstatic --noinput --clear 2>/dev/null || true

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

# exec-форма обязательна: в shell-форме процессом с PID 1 станет sh,
# и SIGTERM не дойдёт до gunicorn — graceful shutdown не сработает (ТЗ п.44).
CMD ["gunicorn", "--config", "gunicorn.conf.py", "config.wsgi:application"]
