# Status, known limitations and blockers

This document is deliberately candid. "Tested" means covered by automated tests that were actually run;
"not fully verified" means implemented and configured but not exercised in the development environment.

## Verification record

Environment: Windows 10, Python 3.13.5, Node 22.21, SQLite, Chromium (Playwright 1.64). No Docker, PostgreSQL,
Redis or Linux host was available; no AI or Stripe credentials were used. Gmail SMTP credentials were configured
and the STARTTLS login was verified (no message was sent during verification).

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check .` | All checks passed |
| Formatting | `ruff format --check .` | 203 files already formatted |
| Unit + integration tests | `pytest --cov` | **209 passed, 5 skipped** (POSIX-only sandbox execution tests), 2 deselected (browser tests), 88% line coverage |
| Browser journeys | `pytest -m e2e tests/e2e` | **2 passed** (register → onboarding with placement check → challenge → feedback → dashboard → history revisit; mobile navigation, no horizontal overflow at 390 px, theme persistence; no console errors) |
| Curriculum | `python -m apps.catalog.content_loader` | 47 skills, 141 challenges, 7 paths; 0 errors, 0 warnings |
| Reference solutions | `python -m apps.catalog.verify_solutions` | 21 coding challenges; 0 problems |
| Migrations | `manage.py makemigrations --check --dry-run` | No changes detected |
| Deployment checks | `manage.py check --deploy --settings=config.settings.prod` | 1 warning: `security.W021` (HSTS preload is an intentional opt-in) |
| Seeding idempotency | `seed_catalog` twice | second run: all 141 challenges unchanged, nothing duplicated |
| Visual QA | `scripts/screenshots.py` + targeted captures | Landing, auth, onboarding, Today (empty & populated), workspace (all formats), feedback, skill map, mastery, analytics, history, settings, billing — desktop and phone widths, dark and light themes. All 10 emails via `preview_emails` at 680 px (light) and 360/390 px (dark), checked for horizontal overflow. Issues found and fixed: hero connector lines, clipped week chart, grid overflow on phones, fieldset overflow in code blocks, misleading code ligatures, email chip row overflowing at 360 px, wrapping status pills and bright row borders in dark-mode email. |

## Implemented and tested

* Registration, login/logout, email verification, password reset, profile/preferences, email change, account
  deletion, rate limiting, CSRF, security headers, safe redirects, cross-user isolation.
* Onboarding wizard (resumable) with a graded placement check that creates real diagnostic attempts.
* Curriculum loading/validation/versioning; skill graph cycle protection; version immutability.
* Adaptive engine: mastery, scheduling, eligibility, difficulty, selection, explanations, streaks (pure unit tests).
* Learning loop: daily plan, recommendations with persisted reasons, skip, submit, deterministic evaluation of
  multiple choice, short answer, concept explanation, code review and debugging; mastery and review updates;
  idempotency; milestones; achievements; time-zone boundaries; free-plan limits; bounded query counts.
* Goals (create, edit, pause/resume/archive, primary goal, focus skills, path version upgrade), paths, skill
  explorer and map, mastery pages, analytics (including empty states), history filters, reviews, notifications.
* AI mentor with mocked provider: valid output, malformed output, refusals, truncation, auth errors, timeouts,
  rate limits, connection errors, quotas, missing key → curated fallback (always labelled).
* Background tasks: reminders (local hour, preferences, verification, deduplication), email delivery idempotency
  and retry, unsubscribe (link and one-click header only on optional emails), daily pre-build idempotency, evaluation retries, runner-outage handling, task-failure
  records, cleanup.
* Billing: entitlements, quotas, signature verification, idempotent webhooks, subscription state transitions,
  unpaid checkouts, rollback on processing failure, dev adapter gated by DEBUG.

## Implemented but not fully verified here

| Item | Why | How to verify |
|---|---|---|
| PostgreSQL | Not installed locally; tests ran on SQLite | CI job runs the suite with `TEST_DATABASE=postgres` |
| Redis cache, Celery worker and beat with a real broker | Not installed; tasks ran eagerly | `docker compose up`, watch `celery inspect ping`, `/readyz/` |
| Docker images and Compose stack | Docker unavailable | `docker compose up --build`, smoke test |
| Sandbox code execution | Requires Linux rlimits; 5 execution tests skipped on Windows | `pytest tests/test_sandbox.py` on Linux (CI), then a coding challenge end to end |
| Python coding challenges end to end | Depend on the sandbox | as above |
| Live Anthropic API calls | No credentials; provider mocked at the SDK boundary | set `AI_PROVIDER/AI_API_KEY`, ask the mentor, check `MentorRequest` metadata |
| Stripe Checkout / Portal | No credentials; webhook path tested with real HMAC signatures | Stripe test mode + `stripe listen --forward-to` |
| SMTP delivery to inboxes | Login to `smtp.gmail.com` verified; tests use the locmem backend; rendering checked in browser previews, not in real mail clients | `python manage.py send_test_email --to you@example.com --template all`, then check Gmail, Outlook and Apple Mail (light and dark) |
| GitHub Actions workflow | Not executed | push to a repository |
| Accessibility | Semantic HTML, labels, focus styles, reduced motion, non-colour status cues and table alternatives were built in and spot-checked; no automated axe audit or screen-reader testing yet | run axe/Lighthouse and a screen-reader pass |

## Partially implemented

* **Teams plan** — listed with a "Talk to us" contact flow; team workspaces are not built (the UI says so).
* **AI-generated challenges** — the model supports `source=ai_generated` and a `review_status` gate (only approved
  challenges are recommended), but no generation pipeline is included.
* **Data export** for learners is not implemented (deletion is).
* **Internationalisation** — English only.
* **Exception reporting** — integration point documented; no Sentry SDK wired in.
* **Staff 2FA** — not implemented; recommended before launch.

## Blocked on external resources

| Needed | Unlocks |
|---|---|
| Anthropic API key | Live AI mentor |
| Stripe account (keys, price ids, webhook secret) | Paid plans |
| Verified sending domain (SPF, DKIM, DMARC) | Production-grade deliverability (a personal Gmail sender is fine for testing) |
| Linux hosting with Docker (ideally gVisor) | Sandbox and coding challenges; production deployment |
| Legal review | Publishing the privacy policy and terms (currently drafts) |

## Known limitations

* Recommendation weights and mastery parameters are unvalidated heuristics (see
  [adaptive-engine.md](adaptive-engine.md#8-limitations-and-next-steps)).
* Keyword rubrics measure coverage of key ideas, not reasoning quality.
* Learners can game their own scores (rubric keywords; tampering with the in-process test harness); this only
  affects their own record.
* Reminder scheduling iterates users hourly; shard by timezone at large scale.
* `npm audit` reports a dev-only advisory in Tailwind's file watcher (not shipped).

## Next improvements (prioritised)

1. Run the PostgreSQL + Linux sandbox CI job and a Docker Compose smoke test; fix anything they surface.
2. Accessibility audit (axe, keyboard-only and screen-reader passes) and fixes.
3. Staff 2FA, Sentry integration, Flower behind auth, alerting on the signals in [operations.md](operations.md).
4. Learner data export (JSON) to complement deletion.
5. Calibrate engine parameters from real data; offline evaluation of alternative models (IRT/BKT); A/B testing via
   strategy versions.
6. Content: more challenges per skill (≥ 5) so reviews rarely repeat; additional tracks.
7. AI-assisted challenge drafting with mandatory human review using the existing `review_status` workflow.
8. Teams: organisations, seats, shared paths and progress reporting.
