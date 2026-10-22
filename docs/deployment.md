# Deployment guide

SkillForge ships as two images: the **application** (`Dockerfile`, used for `web`, `worker` and `beat`) and the
**sandbox** (`sandbox/Dockerfile`). `docker-compose.yml` wires a complete production-like stack and is the
reference for any platform (Kubernetes, ECS, Fly, Render, a VM with Compose…).

> Status: the images and Compose file were written for this release but could not be built in the development
> environment (no Docker available). Build and smoke-test them before relying on them — see
> [limitations](limitations.md).

## 1. Prerequisites

| Component | Notes |
|---|---|
| PostgreSQL 15+ | `DATABASE_URL=postgres://user:pass@host:5432/db`. Connections are persistent (`DATABASE_CONN_MAX_AGE`, default 60 s) with health checks. |
| Redis 7+ | Cache, rate limits (`REDIS_URL`) and Celery broker (`CELERY_BROKER_URL`, a separate DB index is recommended). |
| SMTP / email API | `NOTIFICATION_BACKEND=smtp` plus `SMTP_*` (any Django-compatible backend also works via `EMAIL_BACKEND`). Use a domain you can authenticate (SPF, DKIM, DMARC). |
| TLS-terminating proxy | Set `TRUSTED_PROXY_COUNT` to the number of proxies so rate limiting sees real client IPs. |
| Optional: Anthropic API key | AI mentor (`AI_PROVIDER=anthropic`, `AI_API_KEY`). |
| Optional: Stripe account | Paid plans (see §6). |
| Optional: Linux host for the sandbox | Preferably with gVisor (`runsc`). |

## 2. Required environment (production)

```bash
DJANGO_SETTINGS_MODULE=config.settings.prod          # default in the image
DJANGO_SECRET_KEY=<50+ random characters>            # python -c "import secrets; print(secrets.token_urlsafe(50))"
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=skillforge.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://skillforge.example.com
SITE_URL=https://skillforge.example.com
DATABASE_URL=postgres://...
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_TASK_ALWAYS_EAGER=false
NOTIFICATION_BACKEND=smtp
SMTP_HOST=smtp.example.com SMTP_PORT=587          # 587 = STARTTLS, 465 = SSL
SMTP_USERNAME=... SMTP_PASSWORD=...               # from your secret store
SMTP_FROM=no-reply@example.com                    # sent as "SkillForge <no-reply@example.com>"
SUPPORT_EMAIL=support@example.com                 # receives contact-form messages
DJANGO_ADMIN_URL=<something-unguessable>/
LOG_FORMAT=json
TRUSTED_PROXY_COUNT=1
```

`config/settings/prod.py` refuses to start with a short or development secret key, or with
`BILLING_PROVIDER=dev`. It enables HTTPS redirects, HSTS (1 year; preload is opt-in via
`DJANGO_HSTS_PRELOAD=true`), secure `__Host-` cookies and JSON logging.

## 3. Release steps

```bash
docker build -t skillforge-app .
docker build -t skillforge-sandbox ./sandbox
# then, once per release, in a one-off container:
python manage.py migrate --noinput
python manage.py seed_catalog          # idempotent; creates new content versions only when content changed
python manage.py check --deploy
python manage.py createsuperuser       # first deploy only
python manage.py send_test_email --to you@example.com --template all   # check SMTP, links and rendering
```

Processes:

```bash
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60
celery -A config worker --loglevel=INFO --concurrency=4 --max-tasks-per-child=200
celery -A config beat --loglevel=INFO          # exactly ONE beat instance
```

Static files are collected into the image at build time and served by WhiteNoise with compression and
far-future cache headers (hashed filenames).

Health checks: point the load balancer's **liveness** probe at `/healthz/` and the **readiness** probe at
`/readyz/` (checks database, cache and broker; returns 503 when one is down). See
[operations.md](operations.md#health-checks).

## 4. Code-execution sandbox

The sandbox runs learner code; treat its host as hostile.

* Run it **only** from `sandbox/Dockerfile` (non-root uid 10001, no application code or secrets).
* Required: `RUNNER_TOKEN` (same value as the app's `CODE_RUNNER_TOKEN`). Optional: `RUNNER_MAX_CONCURRENCY`,
  `RUNNER_MEMORY_LIMIT_MB`.
* Container hardening (as in `docker-compose.yml`): `read_only: true`, small `tmpfs` `/tmp`, `cap_drop: [ALL]`,
  `no-new-privileges`, `pids_limit`, memory and CPU limits, and an **internal network** shared only with the web
  and worker containers (no internet, no database, no Redis).
* Strongly recommended: a user-space kernel such as **gVisor** (`runtime: runsc`) or a microVM (Firecracker), and a
  dedicated node pool.
* Inside, every submission runs in a fresh interpreter in its own session with `RLIMIT_CPU`, `RLIMIT_AS`
  (256 MB), `RLIMIT_FSIZE`, `RLIMIT_NOFILE`, `RLIMIT_NPROC=0` and no core dumps; a wall-clock timeout kills the
  whole process group; the working directory is private and deleted afterwards; an audit hook additionally refuses
  sockets, subprocesses and writes outside the working directory.
* Set `CODE_RUNNER_URL=http://sandbox:8080` on web and worker. Per-user concurrency (default 1) is enforced by the
  app; global concurrency by the runner (503 when saturated; the app retries).

Run `pytest tests/test_sandbox.py` on a Linux host to execute the runner's isolation tests.

## 5. AI mentor

```bash
AI_PROVIDER=anthropic
AI_API_KEY=<key>                      # never commit; inject from your secret manager
AI_MODEL=claude-opus-5-5              # default
AI_EFFORT=medium                      # low | medium | high — trades depth for latency/cost
AI_TIMEOUT_SECONDS=45
AI_MAX_OUTPUT_TOKENS=4000             # includes thinking tokens on current models
AI_USE_SERVER_FALLBACKS=true          # server-side refusal fallback on supported models
AI_REQUESTS_PER_MINUTE=6              # per user; daily quotas come from the plan
```

Without these the mentor serves curated guidance, clearly labelled. Provider errors fall back the same way.

## 6. Stripe billing

1. Create Products/Prices for **Pro** and **Interview Preparation** (monthly). Set `STRIPE_PRICE_PRO` and
   `STRIPE_PRICE_INTERVIEW`.
2. Set `BILLING_PROVIDER=stripe` and `STRIPE_SECRET_KEY`.
3. Add a webhook endpoint `https://<host>/billing/webhooks/stripe/` subscribed to `checkout.session.completed`,
   `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted` and
   `invoice.payment_failed`; put its signing secret in `STRIPE_WEBHOOK_SECRET`.
4. Enable the Customer Portal (used by "Manage billing").

Entitlements change only when a signature-verified webhook arrives — never from the checkout redirect. Events
are processed exactly once (`WebhookEvent` is unique per event id and written in the same transaction).

## 7. Scaling notes

* Web is stateless; scale horizontally. Sessions are database-backed.
* Workers scale horizontally; keep a single beat. Reminder tasks iterate users in chunks — at large scale, shard by
  timezone offset.
* Indexed hot paths: attempts by `(user, submitted_at)`, `(user, local_date)`, `(user, challenge)`; reviews by
  `(user, due_at)`; recommendations by `(user, status)`; events by `(user, occurred_at)`.
* The dashboard and history pages run a bounded number of queries (tested).

## 8. Backups

See [operations.md — Backup and restore](operations.md#backup-and-restore).
