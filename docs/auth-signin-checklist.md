# LaunchCrew sign-in provider setup checklist

Status: preparation only. Live Google or Facebook sign-in has NOT been verified, has NOT been enabled by default, and is NOT done in this task. AUTH_ENABLED defaults to false. When AUTH_ENABLED is false, approval_by is demo_placeholder. When AUTH_ENABLED is true and a user is signed in, approval_by is the signed-in user, in the form provider:subject, for example google:demo-test-subject in mocked tests.

Auth source of truth: FastAPI Authlib only. No second auth system. No NextAuth. Next.js does not hold a session. Provider tokens are never persisted, never returned to clients, and never stored in Postgres sessions.

## 1. Scopes, exactly

Do not add scopes. Do not request Drive, publishing, Instagram, or any other scope.

- Google: openid profile email
- Facebook: public_profile email

These are identity scopes only. The backend enforces them in backend/auth.py oauth_client. backend/tests/test_api.py test_identity_only_scopes checks both scope sets.

## 2. Redirect URIs

Register one redirect URI per provider. The backend builds the callback URL as PUBLIC_BASE_URL plus /api/auth/{provider}/callback.

Production, when deployment is verified:

- Google: https://launchcrew.summitsingh.com/api/auth/google/callback
- Facebook: https://launchcrew.summitsingh.com/api/auth/facebook/callback

Local: backend/auth.py validate_config currently requires PUBLIC_BASE_URL with an HTTPS scheme. A plain http localhost callback is therefore NOT accepted by current code. Do not register a plain http URI and present it as working. Local provider callback testing needs an HTTPS local origin, or a later approved code decision about local handling. Do not weaken the HTTPS check in this hardening task. Mocked login and callback tests cover the local login and callback flow without a provider.

## 3. Google setup steps

- [ ] Create a Web application OAuth client in the provider console. No credentials go in the repo, in chat, or in logs.
- [ ] Set the authorized redirect URI from section 2 for the environment being tested.
- [ ] Confirm the requested scopes are exactly openid profile email.
- [ ] Set PUBLIC_BASE_URL to the exact HTTPS origin used in the redirect URI, with no trailing path.
- [ ] Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET only in the deployment environment, never in the repo.
- [ ] Set AUTH_ENABLED to true only for a live sign-in test run approved by Summit, after deployment HTTPS is verified.

## 4. Facebook setup steps

- [ ] Create a Facebook app with Facebook Login. No credentials go in the repo, in chat, or in logs.
- [ ] Set the valid OAuth redirect URI from section 2 for the environment being tested.
- [ ] Confirm the requested scopes are exactly public_profile email.
- [ ] Set PUBLIC_BASE_URL to the exact HTTPS origin used in the redirect URI, with no trailing path.
- [ ] Set FACEBOOK_CLIENT_ID and FACEBOOK_CLIENT_SECRET only in the deployment environment, never in the repo.
- [ ] Set AUTH_ENABLED to true only for a live sign-in test run approved by Summit, after deployment HTTPS is verified.

## 5. Session, rotation, expiry, and logout

- Cookie name: launchcrew_session. Path: /api. Flags: Secure, HttpOnly, SameSite=lax, max age 8 hours.
- Sessions live server-side in Postgres table auth_sessions. Only a hashed opaque id is the key; the raw cookie value is never stored.
- Session lifetime: 8 hours (SESSION_HOURS in backend/auth.py). An expired session is refused with 401, and /api/auth/status reports no user.
- Rotation: login saves the OAuth state session and callback saves the signed-in session with a new opaque value, deleting the old session row. After rotation, the old cookie must get 401 on a protected endpoint. Covered by backend/tests/test_auth_hardening.py rotation tests.
- Logout: POST /api/auth/logout deletes the server session row and expires the client cookie. Logout is idempotent: a missing or already invalid cookie still returns signed_out true. After logout, a protected endpoint must return 401. Covered by backend/tests/test_auth_hardening.py logout tests.
- Failure handling: callback failures return a generic identity verification failure. Provider errors and tokens are not put in responses, logs, receipts, or sessions.

## 6. approval_by recording

- Disabled mode: approval_by is demo_placeholder everywhere, including receipt approvals, the approvals table, and audit actor.
- Enabled and signed in: approval_by is the signed-in user (provider:subject). Approving a run must record that same value in three places: the receipt approvals entry, the approvals table row, and the audit row for approved_for_export. Covered by backend/tests/test_auth_hardening.py.
- Never record a provider token, email address, or full profile as approval_by. Only provider:subject is recorded.

## 7. Test plan for live sign-in (requires Summit approval and deployment HTTPS, NOT in this task)

Do not run this plan until Summit approves it and deployment HTTPS is verified.

- [ ] Confirm /api/health reports auth enabled_unverified and approval_by signed_in_user only after AUTH_ENABLED is set true in the deployment environment.
- [ ] Google: open /api/auth/google/login, complete sign-in, confirm redirect to the app, confirm /api/auth/status shows the signed-in Google user, and confirm the callback URL matches section 2.
- [ ] Facebook: repeat the same flow for /api/auth/facebook/login and confirm /api/auth/status shows the signed-in Facebook user.
- [ ] Create a run, approve it, and confirm approval_by is the signed-in user in the receipt, the approvals table, and audit, not demo_placeholder.
- [ ] Confirm logout: after POST /api/auth/logout, /api/auth/status shows no user and /api/queue returns 401.
- [ ] Confirm expiry handling: after the 8 hour session expiry, a protected endpoint returns 401 and re-login is required.
- [ ] Confirm rotation: after a fresh login and callback, the pre-callback cookie returns 401.
- [ ] Confirm scope check: the provider consent screen shows only the scopes in section 1.
- [ ] Rollback: set AUTH_ENABLED to false in the deployment environment to return to demo_placeholder mode, and confirm /api/health reports disabled_demo.

## 8. What is NOT done

Live sign-in, live Spark, live SAM, CI execution, demo video, submission, connectors, and provisioning are all NOT done in this task. This checklist is preparation and mocked-test coverage only. Live sign-in remains unverified until the section 7 plan is approved and run against a verified HTTPS deployment.
