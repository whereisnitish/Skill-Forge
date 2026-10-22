# Security checklist

## Controls in place

| Area | Control | Verified by |
|---|---|---|
| Authentication | Django password hashing (PBKDF2 default), validators incl. 10-char minimum and common-password check; email login; POST-only logout | `tests/test_accounts.py` |
| Email verification & reset | HMAC tokens bound to user state and time-limited (verify: 3 days, reset: 3 hours); single use; reset doesn't reveal whether an email exists; tokens generated inside the task, never sent through the broker | `tests/test_accounts.py` |
| Sessions & CSRF | HttpOnly, SameSite=Lax; `Secure` + `__Host-` prefixed cookies in production; CSRF on every state change (HTMX sends the token header) | `test_csrf_is_enforced` |
| Authorization | Every learner query is scoped to `request.user`; foreign objects return 404 (no existence leak); recommendation ids from other users are ignored | `test_cannot_read_or_modify_another_users_data`, `test_lists_only_show_own_records`, `test_recommendation_ids_from_other_users_are_ignored_on_submit` |
| Redirects | `next` parameters validated with `url_has_allowed_host_and_scheme` | `test_login_does_not_redirect_offsite`, `test_resend_verification_ignores_offsite_next` |
| Rate limiting | Login (per IP and per email), registration, password reset, verification resend, contact, submissions, hints, autosave, mentor (per minute + daily quota), checkout | `test_login_is_rate_limited`, `test_registration_is_rate_limited`, `test_request_rate_limit_and_dedupe` |
| Output encoding | Django auto-escaping; Markdown rendered then sanitised with nh3 (no scripts, event handlers or `javascript:` URLs) | `test_rendered_user_content_is_escaped`, `test_markdown_rendering_is_sanitised` |
| Headers | CSP with per-request script nonce and no `unsafe-eval`; `frame-ancestors 'none'`; X-Frame-Options DENY; nosniff; strict referrer policy; COOP; Permissions-Policy; HSTS in production | `test_security_headers` |
| Input validation | Django forms; evaluators validate answers (unknown options, line ranges, lengths, word limits); malformed input produces 4xx without side effects | `test_malformed_input_is_rejected_safely` |
| Code execution | Separate sandbox service; never in web/worker; see [deployment](deployment.md#4-code-execution-sandbox) | `tests/test_sandbox.py` (POSIX tests run in Linux CI) |
| AI | No names/emails sent; learner text delimited and declared non-instructional; structured output validated; quotas; refusals and errors fall back; AI cannot change scores | `tests/test_mentor.py` |
| Billing | Signature-verified webhooks; idempotent event processing; checkout redirect grants nothing; dev adapter impossible in production | `tests/test_billing.py` |
| Secrets | Environment only; `.env` git-ignored; production refuses weak secret keys | `config/settings/prod.py` |
| Errors | Custom 4xx/5xx pages; 500 page shows only a request id; no stack traces with `DEBUG=False` | manual |
| Logging | Ids, timings and error types only — never answers, passwords, tokens or keys | code review |
| Admin | Configurable URL (`DJANGO_ADMIN_URL`); learning records read-only in the admin | `tests/test_admin.py` |
| Account deletion | Password + typed confirmation; cascades all learning data; cancels Stripe subscription first | `test_account_deletion_removes_learning_data` |

## Pre-launch checklist

- [ ] `python manage.py check --deploy --settings=config.settings.prod` passes (HSTS preload is a deliberate
      opt-in).
- [ ] Unique `DJANGO_SECRET_KEY`, `CODE_RUNNER_TOKEN`, database and Redis passwords from a secret manager.
- [ ] `DJANGO_ADMIN_URL` changed; staff accounts use strong passwords (consider adding 2FA for staff).
- [ ] TLS everywhere; `TRUSTED_PROXY_COUNT` matches the real proxy chain.
- [ ] Sandbox deployed with the hardening in `docker-compose.yml`, ideally under gVisor, on separate nodes.
- [ ] Stripe webhook secret configured; test mode verified end to end before live mode.
- [ ] Email domain authentication (SPF, DKIM, DMARC) configured.
- [ ] Backups configured and a restore rehearsed.
- [ ] Legal pages reviewed by a qualified professional (currently drafts).
- [ ] Dependency audit (`pip-audit`, `npm audit`) clean or triaged.

## Accepted risks and notes

* **Registration reveals existing emails** ("An account with this email already exists"). Common SaaS
  trade-off; mitigated by rate limiting. Password reset does not reveal existence.
* **Learners can cheat their own code score.** Tests run in the same interpreter as learner code (the runner's
  result line is nonce-tagged, which stops naive spoofing, but determined code could tamper with the harness). Scores
  only affect the learner's own learning record; there is no competitive ranking.
* **Keyword rubrics can be gamed** by listing keywords. Long passages copied from the prompt earn no credit; the UI
  explains how scoring works. Only the learner's own record is affected.
* **Email delivery is at-least-once.** A crash between sending and recording could duplicate one email; the
  claim-before-send step prevents concurrent duplicates.
* **npm audit** reports a `braces` advisory in Tailwind's file watcher (`@parcel/watcher`), used only by
  `npm run watch:css` during development. It is not shipped.
* The audit hook in the sandbox harness is defence in depth, not a boundary; isolation comes from the container,
  rlimits and network policy.
