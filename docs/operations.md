# Operations: observability, backups and troubleshooting

## Logging

* `LOG_FORMAT=json` (default in production) emits one JSON object per line: timestamp, level, logger, message,
  `request_id` and any structured `extra` fields (`user_id`, `attempt_id`, `task`, `latency_ms`, …).
* Every request gets an `X-Request-ID` (an incoming valid header is reused, otherwise generated). It is returned to
  the client, attached to every log line and shown on the 500 page so support can correlate reports.
* Event names are stable and greppable: `account.registered`, `attempt.submitted`, `attempt.evaluated`,
  `mentor.completed`, `mentor.provider_error`, `billing.webhook`, `reminders.daily`, `runner.unreachable`,
  `task.failed`, `task.retry`, `cleanup.completed`, …
* Never logged: answers, code, passwords, tokens, API keys, email bodies.

## Exception reporting

Unhandled exceptions are logged with tracebacks by Django's handlers. To add Sentry (or similar), install its SDK
and initialise it in `config/settings/prod.py` behind an environment variable; set `send_default_pii=False`.

## Health checks

| Endpoint | Type | Checks | Use for |
|---|---|---|---|
| `GET /healthz/` | Liveness | process is serving requests — no dependencies | restart decisions |
| `GET /readyz/` | Readiness | database `SELECT 1`, cache round-trip, Celery broker connection (skipped in eager mode) | routing traffic; returns **503** with per-check status when not ready |

Liveness deliberately ignores dependencies: restarting web pods would not fix a database outage. The sandbox has
its own `GET /healthz`.

## Background jobs

* Failed tasks (after retries) are logged as `task.failed` and stored in **Admin → Core → Task failures**;
  retries are logged as `task.retry`. Mark rows resolved once handled; resolved rows are pruned after 30 days.
* Queue monitoring: run [Flower](https://flower.readthedocs.io/) (`celery -A config flower`) behind
  authentication, or alert on Redis list length for the `celery` queue.
* Alert on: readiness failures; `task.failed` rate; `runner.unreachable`/queued attempts older than 10 minutes;
  `mentor.provider_error` rate by `code` (`timeout`, `rate_limited`, `unavailable`, `refused`, `malformed`);
  `billing.webhook` failures (HTTP 500 responses to Stripe).
* AI usage metrics live on `MentorRequest` (status, source, provider, model, error code, input/output tokens,
  latency). Aggregate them for cost and error dashboards.
* Beat must run as a single instance. Missed hours are harmless: reminders and pre-builds are idempotent and the
  Today page builds plans on demand.

## Audit trail

`LearningEvent` records goal changes, recommendations, hints, reveals, submissions, evaluations, mastery and
review updates, milestones and achievements (no answer content). `ReviewRecord`, `SkillEvidence` and
`AttemptEvaluation` make every mastery and schedule change traceable to a specific attempt.

## Backup and restore

**PostgreSQL** is the only stateful store that must be backed up (Redis holds caches, rate-limit counters and the
broker queue; losing it delays queued tasks but loses no learning data).

```bash
# Nightly logical backup (keep 30 days; encrypt at rest; store off-site)
pg_dump --format=custom --no-owner --dbname="$DATABASE_URL" --file="skillforge-$(date +%F).dump"

# Restore into an empty database
createdb skillforge_restore
pg_restore --no-owner --dbname=postgres://.../skillforge_restore skillforge-YYYY-MM-DD.dump
DATABASE_URL=postgres://.../skillforge_restore python manage.py migrate   # applies any newer migrations
DATABASE_URL=postgres://.../skillforge_restore python manage.py check
```

Prefer managed point-in-time recovery where available. **Rehearse a restore** at least quarterly. After a
restore, run `seed_catalog` (idempotent) and `check_skill_graph`. Deleted accounts may persist in backups until the
backups expire — state this in the privacy policy (the draft does).

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Unstyled pages | Assets not built: run `npm ci && npm run build` (development) or rebuild the image. |
| `FileNotFoundError: Icon … is not vendored` (DEBUG) | A template uses a new Lucide icon: run `npm run vendor`. |
| "Code execution isn't available" | `CODE_RUNNER_URL`/`CODE_RUNNER_TOKEN` unset or runner down; check `GET http://sandbox:8080/healthz` from the worker. |
| Coding attempts stuck "Evaluating…" | Worker not running or runner unreachable; `retry_pending_evaluations` re-dispatches every 10 minutes; attempts fail permanently after 5 evaluation errors. |
| No reminder emails | User hasn't enabled them, email unverified, wrong timezone/hour, beat not running, or SMTP failing (see notification `email_status`/`email_error` in the admin). |
| Emails fail with `SMTPAuthenticationError` | Wrong `SMTP_USERNAME`/`SMTP_PASSWORD`. For Gmail use an app password (requires 2-Step Verification), not the account password. `python manage.py send_test_email --to you@example.com` reports the exact error. |
| Emails land in spam | Send from a domain with SPF, DKIM and DMARC records; a personal Gmail sender is fine for testing but not for production volume. |
| Email links point at the wrong host | Set `SITE_URL` — every link in an email is built from it. |
| Changing how an email looks | Edit `templates/emails/<name>.html` and `.txt`, then `python manage.py preview_emails` and open `email-previews/index.html`. |
| Plan upgrade not applied | Webhook not configured or failing signature checks — check `billing.webhook_rejected` logs and Stripe's webhook dashboard. |
| 429 responses | Rate limit hit; limits are per IP/user and reset within the window. Behind proxies, check `TRUSTED_PROXY_COUNT`. |
| `ImproperlyConfigured: DJANGO_SECRET_KEY…` | Production refuses short/dev keys — generate a long random key. |
| Recommendations look repetitive | Check skill readiness (prerequisites), available challenge count for the path, and `ENGINE_*` settings. Each recommendation's `reason_data` stores the full score breakdown. |
| Port 8000 already in use locally | `python manage.py runserver 127.0.0.1:8765` |
