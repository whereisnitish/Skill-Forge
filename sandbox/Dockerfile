# Isolated Python code runner. Contains no application code or secrets.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RUNNER_WORK_ROOT=/tmp
RUN groupadd --system --gid 10001 runner && useradd --system --uid 10001 --gid runner --no-create-home runner
WORKDIR /srv
COPY runner/ /srv/runner/
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
CMD ["python", "-m", "runner.server"]
