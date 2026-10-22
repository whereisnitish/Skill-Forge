# SkillForge

**Learn less randomly. Practise more intelligently.**

SkillForge is an adaptive learning SaaS for software engineers. A learner picks a goal, their level and their
available time; SkillForge then recommends one practical challenge at a time, evaluates the answer
deterministically, updates a per-skill mastery estimate (with honest uncertainty), schedules spaced reviews and
uses that evidence to choose what comes next — explaining every recommendation.

It is a modular Django monolith: server-rendered templates + HTMX, PostgreSQL, Redis, Celery, an optional AI
mentor behind a provider abstraction, an optional Stripe integration, and a separate, hardened code-execution
sandbox service.

---

## Contents

- [What's in the box](#whats-in-the-box)
- [Quick start (local)](#quick-start-local)
- [Running with Docker](#running-with-docker)
- [Configuration](#configuration)
- [Tests and quality checks](#tests-and-quality-checks)
- [Project structure](#project-structure)
- [Implementation status](#implementation-status)
- [Documentation](#documentation)

---

## What's in the box

| Area | Highlights |
|---|---|
| **Adaptive engine** (`apps/engine`) | Pure, versioned, unit-tested modules: Beta-evidence mastery model with decay and confidence, SM-2-style review scheduler, prerequisite graph with cycle detection, eligibility, difficulty progression, weighted selection with controlled variation, deterministic explanations. |
| **Evaluation** (`apps/evaluation`) | Deterministic evaluators for multiple choice (incl. partial credit), short answer, keyword rubrics (concept explanations, code review), debugging (line + explanation) and Python code (via the sandbox). Versioned; misconceptions recorded. |
| **Learning loop** (`apps/learning`) | Daily sessions built one recommendation at a time from fresh state, immutable attempts, idempotent evaluation & learner-model updates, review records, audit events, milestones, achievements, analytics, history. |
| **Curriculum** (`apps/catalog`) | 47 skills, 141 versioned challenges across 6 formats, 54 prerequisite edges and 7 curated, versioned learning paths, loaded idempotently from YAML. |
| **Product** | Marketing site, auth (registration, email verification, password reset, account deletion), resumable onboarding with a graded placement check, Today dashboard, challenge workspace (CodeMirror, autosave, hints, reveal), feedback, goals, paths, skill explorer + interactive skill map, mastery, analytics, history, reviews, notifications, settings, billing. |
| **AI mentor** (`apps/mentor`) | Optional. Anthropic provider with JSON-schema output, timeouts, retries, quotas and refusal handling; deterministic curated fallback, always labelled. AI never changes scores. |
| **Operations** | Celery tasks (idempotent, retried, deduplicated), structured JSON logs with request IDs, task-failure records, liveness/readiness checks, rate limiting, CSP with nonces. |

---

## Quick start (local)

Requirements: **Python 3.12+** (3.13 used in development), **Node.js 20+** (for the asset build). PostgreSQL and
Redis are optional locally — without them SQLite, a local-memory cache and inline (eager) Celery tasks are used.

```bash
# 1. Environment file
cp .env.example .env                  # Windows: copy .env.example .env

# 2. Python dependencies
python -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt

# 3. Frontend assets (Tailwind CSS, CodeMirror bundle, vendored htmx/Chart.js/fonts/icons)
npm ci
npm run build

# 4. Database and curated content
python manage.py migrate
python manage.py seed_catalog          # idempotent; safe to re-run after editing content

# 5. Users
python manage.py createsuperuser       # admin at /admin/
python manage.py create_demo_learner   # optional, DEBUG only: demo@skillforge.local / skillforge-demo-2026

# 6. Run
python manage.py runserver
```

Open <http://localhost:8000>. Emails (verification, password reset, reminders) are printed to the console unless
you set `NOTIFICATION_BACKEND=smtp` and the `SMTP_*` variables (see `.env.example`).

### Emails

Every email has its own template in `templates/emails/` (`<name>_subject.txt`, `<name>.txt`, `<name>.html`) on a
shared, table-based layout that works in Gmail, Outlook and Apple Mail, including dark mode and phone widths:
`verify_email`, `verify_email_change`, `password_reset`, `daily_reminder`, `review_due`, `milestone`,
`achievement`, `payment_failed`, `account` and `contact_received` (to `SUPPORT_EMAIL`, Reply-To the sender).
Reminder, milestone and achievement emails carry a one-click `List-Unsubscribe` header; transactional ones don't.

```bash
python manage.py preview_emails                    # writes email-previews/index.html with every email
python manage.py send_test_email --to you@example.com --template all   # real send, subjects prefixed [Test]
```

### Background workers (optional locally)

With `REDIS_URL` set (and `CELERY_TASK_ALWAYS_EAGER=false`), run the worker and scheduler in separate shells:

```bash
celery -A config worker --loglevel=INFO
celery -A config beat --loglevel=INFO
```

### Code-execution sandbox (optional locally)

Python coding challenges are graded only by the sandbox service in `sandbox/`, which requires Linux resource
limits. Without it, coding challenges are clearly marked as unavailable and are never marked as passed. Run it via
Docker Compose (below) or see [docs/deployment.md](docs/deployment.md#code-execution-sandbox).

---

## Running with Docker

```bash
cp .env.example .env   # set DJANGO_SECRET_KEY, DJANGO_DEBUG=false, CODE_RUNNER_TOKEN; BILLING_PROVIDER="" or stripe
docker compose up --build
```

This starts `web` (Gunicorn, runs migrations and `seed_catalog` on start), `worker`, `beat`, `db` (PostgreSQL 17),
`redis` and the hardened `sandbox`. The sandbox sits on an internal network with no internet access and no route
to the database or Redis. See [docs/deployment.md](docs/deployment.md).

---

## Configuration

All configuration comes from environment variables; `.env.example` documents every one. The most important:

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL` | Core Django settings. Production refuses short or dev keys. |
| `DATABASE_URL` | PostgreSQL in production (SQLite default for development). |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_TASK_ALWAYS_EAGER` | Cache, rate limits and Celery broker. |
| `NOTIFICATION_BACKEND`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SUPPORT_EMAIL` | Outgoing email (`console` by default, `smtp` to send). Django's `EMAIL_*` names also work. |
| `AI_PROVIDER`, `AI_MODEL`, `AI_API_KEY`, `AI_TIMEOUT_SECONDS`, `AI_MAX_OUTPUT_TOKENS`, `AI_EFFORT` | Optional AI mentor (`AI_PROVIDER=anthropic`). Default model `claude-opus-5-5`. |
| `CODE_RUNNER_URL`, `CODE_RUNNER_TOKEN`, `CODE_RUNNER_TIMEOUT_SECONDS` | Optional sandbox service. |
| `BILLING_PROVIDER`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_INTERVIEW` | `stripe`, `dev` (DEBUG only) or empty (paid plans unavailable). |
| `ENGINE_WEIGHT_*`, `ENGINE_EXPLORATION_RATE`, `ENGINE_TOP_K` | Tune the recommendation heuristic without code changes. |
| `LOG_LEVEL`, `LOG_FORMAT`, `TRUSTED_PROXY_COUNT`, `RATELIMIT_ENABLED` | Operations. |

---

## Tests and quality checks

```bash
pytest                                   # unit + integration (Playwright tests excluded by default)
pytest --cov                             # with coverage
python -m playwright install chromium    # once
pytest -m e2e tests/e2e                  # browser journeys against a live server
ruff check . && ruff format --check .    # lint + formatting
python -m apps.catalog.content_loader    # validate curriculum YAML (no DB needed)
python -m apps.catalog.verify_solutions  # reference solutions pass, starters fail (trusted content only)
python manage.py check --deploy --settings=config.settings.prod   # needs prod env vars
python manage.py makemigrations --check --dry-run
```

Tests never call live AI or payment services; provider boundaries are mocked (Stripe webhooks are verified with
real HMAC signatures generated in the tests).

**Last local run (Windows 10, Python 3.13.5, SQLite):** see the results recorded in
[docs/limitations.md](docs/limitations.md#verification-record).

---

## Project structure

```
config/                 settings (base/dev/test/prod), URLs, Celery app, WSGI/ASGI
apps/
  core/                 middleware (request IDs, CSP, timezone), rate limiting, health checks, logging,
                        markdown sanitising, template tags, icons, task-failure records, cleanup task
  accounts/             custom User (email login), Profile/preferences, auth flows, settings, deletion
  marketing/            public website, contact form, sitemap
  catalog/              skills, prerequisites, versioned challenges/paths, YAML content + loader/validator,
                        seeding, skill-map layout, explorer views
  engine/               pure adaptive-engine modules (no Django models)
  evaluation/           deterministic evaluators + sandbox client
  learning/             goals, sessions, recommendations, attempts, evaluations, mastery, reviews,
                        events, achievements, analytics, dashboard; views and Celery tasks
  onboarding/           resumable onboarding wizard and placement check
  mentor/               AI provider abstraction, curated fallback, mentor requests
  notifications/        in-app notifications, reminder scheduling, email delivery, unsubscribe
  billing/              plans/entitlements, usage quotas, Stripe + dev adapters, webhooks
sandbox/                standalone code-runner service (stdlib only) + Dockerfile
templates/              layouts, components and pages
frontend/               Tailwind v4 design system (app.css) and CodeMirror entry (editor.js)
static/                 app.js, vendored assets, fonts, images (dist/ is built)
scripts/                vendor.mjs (asset vendoring), screenshots.py, brand_assets.py
tests/                  pytest suite (engine, evaluation, learning, security, accounts, billing,
                        mentor, tasks, catalog, sandbox, admin) and tests/e2e (Playwright)
docs/                   architecture, ERD, engine design, deployment, security, operations, API, limitations
```

---

## Implementation status

See [docs/limitations.md](docs/limitations.md) for the full, honest breakdown of what is **implemented and tested**,
**implemented but not fully verified**, **partial**, and **blocked on external resources**. In short:

- The core adaptive loop, accounts, onboarding, evaluation, learner model, reviews, goals, analytics, mentor
  fallback, notifications, billing webhooks and security controls are implemented and covered by automated tests,
  including Playwright browser journeys.
- PostgreSQL, Redis-backed Celery, Docker images, the sandbox's real code execution, live Anthropic calls and live
  Stripe checkout are implemented and configured but were **not exercised in this development
  environment** (no Docker/PostgreSQL/Redis/Linux available, no credentials). CI is configured to cover the
  PostgreSQL and Linux-sandbox parts.
- Email is configured for Gmail SMTP; the login handshake was verified against `smtp.gmail.com`, and every
  template renders and is covered by tests, but no message has been delivered to a real inbox yet.
- This is a first release ready for review — **not** yet production-ready: legal pages are drafts, and the items
  above need verification in a real environment.

## Documentation

- [Architecture](docs/architecture.md) · [Entity–relationship diagram](docs/erd.md)
- [Adaptive engine design](docs/adaptive-engine.md) · [Content authoring](docs/content-authoring.md) ·
  [Curriculum map](docs/curriculum-map.md)
- [Deployment](docs/deployment.md) · [Operations, monitoring, backup & troubleshooting](docs/operations.md)
- [Security checklist](docs/security.md) · [HTTP endpoints & integrations](docs/api.md)
- [Known limitations, blockers and verification record](docs/limitations.md)
