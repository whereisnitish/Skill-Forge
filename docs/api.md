# HTTP endpoints and integrations

SkillForge has **no public REST API** in this release. Pages are server-rendered; HTMX requests return HTML
partials. Machine-to-machine endpoints are limited to health checks, the Stripe webhook and the sandbox runner.
Django REST Framework was intentionally not added — see [architecture](architecture.md#architectural-decisions).

## Machine endpoints

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /healthz/` | none | Liveness: `{"status": "ok"}` |
| `GET /readyz/` | none | Readiness: `{"status": "ok"|"unavailable", "checks": {...}}`, 503 when not ready |
| `POST /billing/webhooks/stripe/` | `Stripe-Signature` HMAC | Stripe events; CSRF-exempt; returns `processed`, `ignored` or `duplicate`; 400 on bad signature; 500 (retry) on processing failure |
| `GET/POST /app/notifications/unsubscribe/<signed-token>/` | signed token (90 days) | One-click unsubscribe (RFC 8058); CSRF-exempt by design |
| `GET /robots.txt`, `GET /sitemap.xml` | none | SEO |

## HTMX endpoints (session-authenticated, CSRF-protected)

| Method & path | Returns |
|---|---|
| `POST /app/plan/<id>/skip/` | `_current_challenge.html` with the next recommendation |
| `POST /app/challenges/<slug>/hint/` | hints panel with the next hint revealed |
| `POST /app/challenges/<slug>/solution/` | solution panel (marks the draft as assisted) |
| `POST /app/challenges/<slug>/autosave/` | `204 No Content` |
| `POST /app/challenges/<slug>/syntax/` | syntax check result (parse only — never executes) |
| `GET /app/attempts/<id>/status/` | evaluation result partial (polled while code is evaluated) |
| `POST /app/mentor/ask/` | mentor response partial (polls `GET /app/mentor/<id>/` while pending) |
| `GET /app/history/?…` (`HX-Target: history-results`) | filtered history results |
| `GET /app/skills/?…` (`HX-Target: skill-results`) | filtered skill list or map |
| `POST /settings/{profile,learning,notifications,appearance,email,password}/` | the re-rendered settings card |
| `POST /settings/theme/` | `204`, sets the theme cookie (and profile when signed in) |
| `POST /app/notifications/<id>/read/` | the updated notification item |

Errors for HTMX requests return the status code with a human-readable `X-SF-Message` header, which the client
shows as a toast.

## Sandbox runner API (internal network only)

```
POST /run
Authorization: Bearer <RUNNER_TOKEN>
Content-Type: application/json

{"code": "def f(): ...", "tests": [{"id": "1", "code": "assert f() == 1"}], "time_limit_seconds": 3}
```

Limits: body ≤ 128 KB, code ≤ 20 000 chars, 1–20 tests (≤ 4 000 chars each, ids `[A-Za-z0-9_-]{1,32}`), per-test
time limit 0.5–5 s.

Response `200`:

```json
{"status": "completed|compile_error|timeout|crashed",
 "tests": [{"id": "1", "status": "passed|failed|error|timeout|not_run", "message": "..."}],
 "stdout": "...", "error": "...", "duration_ms": 123}
```

`400` invalid request · `401` bad token · `413` body too large · `503` busy or unsupported platform (the app
retries). `GET /healthz` → `{"status": "ok"}`.

## Outbound integrations

| Service | Library | Where |
|---|---|---|
| Anthropic Messages API | `anthropic` (official SDK) | `apps/mentor/providers.py` — `beta.messages.create` with JSON-schema `output_config`, effort, server-side fallbacks, no SDK retries (Celery retries) |
| Stripe | `stripe` (`StripeClient`) | `apps/billing/adapters.py` (Checkout, Portal, cancel), `apps/billing/views.py` (signature verification) |
| SMTP / email provider | Django email backends | `apps/core/emails.py` |
