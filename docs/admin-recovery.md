# Admin-created learner recovery links

In organization Users, a current organization Admin can generate a recovery link for a local-password learner. Share the link privately with the named learner. Anyone holding it can choose that learner's new password. It expires after 15 minutes, works once, and is replaced when another link is generated. Closing the dialog clears the displayed link. It cannot be retrieved later.

The learner opens `/recover`, chooses and confirms a password, then signs in normally. Opening a link never consumes it. Recovery sends no email, creates no session, and does not alter MFA, backup codes, email verification, membership, role, courses, or assignments. Successful redemption resets password lockout and invalidates older access, refresh, and pending-MFA sessions by credential fingerprint. Legacy unstamped sessions still require a valid issuance time at or after any password-change cutoff.

## Eligibility and deployment

- The issuer needs a real sign-in with recognized human authentication provenance, actual Admin membership (role 1), and current organization authentication/MFA policy compliance. API-token impersonation, Maintainer, and superadmin-only authority are insufficient.
- The target must differ from the issuer and must not be a superadmin. They must have exactly one membership in the issuing organization, with canonical global learner role 4 (`role_global_user`) and no elevated rights.
- Issuer or target password changes invalidate outstanding links. Redemption also refuses links whose current roles, membership identities, or relevant policy no longer match, and rechecks current issuer MFA compliance, including elapsed grace.
- Use the configured primary frontend origin. API `hosting_config.frontend_domain`/`ssl` must match web `NEXT_PUBLIC_LEARNHOUSE_DOMAIN`/`NEXT_PUBLIC_LEARNHOUSE_HTTPS`. HTTPS is required except for loopback development. Host and Origin checks do not trust caller-supplied forwarded identity.
- PostgreSQL owns the current grant and atomically consumes it with the password update. The additive `r20261006_recovery` migration follows `m20260906_mentions` and tolerates a table already created by startup's model bootstrap. There is one current row per target, not a historical grant chain.
- Redis is required for throttling, not one-use correctness. A Redis outage fails recovery closed. Authenticated issuance is limited per issuer and issuer/target. Redemption uses an atomic 20-attempt/5-minute budget for each known, unexpired grant digest, so learners behind the same web proxy do not share a small global budget. Unknown/expired capabilities allocate no Redis keys and perform no password hashing. Replacement gets a fresh budget.

## Privacy

The learner document is a route-handler HTML response outside the React layouts. It has no app scripts, analytics, or session hooks. A fresh nonce CSP permits only its inline script/style and same-origin submission. It reads the fragment into local memory, immediately removes it from the address bar, and submits only to `/api/recovery/redeem` with credentials omitted. Responses are no-store/no-referrer.

The admin link lives only in component state. Before issuance, replay stops; telemetry is suppressed for the remainder of that browser document, including after the dialog closes. Secret-bearing UI is also explicitly blocked from replay. Recovery request/response bodies and error events are excluded from Sentry. API audit messages contain only action, issuer ID, target ID, and organization ID, never credentials, links, hashes, or email addresses.

## Repeatable verification

From `apps/api`, run:

```sh
uv run pytest src/tests/routers/test_admin_recovery.py src/tests/security/test_recovery_postgres.py src/tests/security/test_recovery_rate_limit.py src/tests/security/test_recovery_session_cutover.py src/tests/security/test_recovery_telemetry.py
```

Set `RECOVERY_TEST_POSTGRES_URL` to an isolated loopback `postgresql+asyncpg://` database to enable real SQL concurrency/session-race tests. Each fixture creates and drops only its own uniquely named schema. Set `RECOVERY_TEST_REDIS_URL` to an isolated loopback Redis service to enable the atomic limiter test, which cleans up only its own synthetic key. These tests reject non-loopback URLs and skip when the variables are absent. Never point them at production.

From `apps/web`, run `bun test tests/admin-recovery.test.ts`. It covers the actual route handlers, CSP/nonces, cold/stale-cookie navigation, host/origin checks, fragment scrubbing, bounded bodies, password errors, credential-omitted submission, and secret-safe telemetry configuration. Browser verification should additionally exercise keyboard focus, copy/replace/close, and generated-link/error states on a short mobile viewport without recording a real link.
