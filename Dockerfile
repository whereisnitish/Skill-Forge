# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Stage 1: build frontend assets (Tailwind CSS, CodeMirror bundle, vendored libs)
# ---------------------------------------------------------------------------
FROM node:22-slim AS assets
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY scripts/ scripts/
COPY frontend/ frontend/
COPY templates/ templates/
COPY apps/ apps/
COPY static/ static/
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python application
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod
RUN groupadd --system --gid 10000 app && useradd --system --uid 10000 --gid app --home /app app
WORKDIR /app
COPY requirements/ requirements/
RUN pip install -r requirements/base.txt
COPY . .
COPY --from=assets /build/static/ /app/static/
COPY --from=assets /build/apps/core/icons/ /app/apps/core/icons/
# collectstatic needs a syntactically valid key at build time only; the real one is injected at runtime.
RUN DJANGO_SECRET_KEY=build-only-placeholder-key-not-used-at-runtime-0123456789 \
    DJANGO_ALLOWED_HOSTS=localhost python manage.py collectstatic --noinput
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=3)"
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
