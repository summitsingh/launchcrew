# LaunchCrew Google-only sign-in checklist, source-only

Status: source wiring only. Live Google sign-in has NOT been verified, has NOT been enabled by default, and is NOT done in this task. Source-only means code plus mocked tests are reviewable here with no provider call. Live-proof means an approved sign-in run against verified HTTPS deployment, which is NOT claimed here. AUTH_ENABLED defaults to false. When false, approval_by is demo_placeholder. When true and signed in, approval_by is google:subject, for example google:synthetic-alpha-01 in mocked tests.

Auth source of truth: FastAPI Authlib only. No second auth system. No NextAuth. Next.js does not hold a session. Provider tokens are never persisted, never returned to clients, and never stored in Postgres sessions.

## 1. Scopes, exactly

Do not add scopes. Do not request Drive, publishing, Instagram, or any other scope.

- Google: openid profile email

Facebook Login stays unpublished and inactive in Google-only mode. No Facebook scope is requested and no Facebook link is shown. The backend keeps Facebook code for later work but Google-only deployment injects no Facebook credential.

Identity scopes only. The backend enforces Google scope in backend/auth.py oauth_client. backend/tests/test_api.py test_identity_only_scopes checks the Google scope set.

## 2. Redirect URIs

The backend builds the callback URL as PUBLIC_BASE_URL plus /api/auth/google/callback. PUBLIC_BASE_URL must be an exact HTTPS origin with no trailing path, query, or fragment. backend/auth.py validate_config refuses any other shape when auth is enabled.

Production, when deployment is verified:

- Google: https://launchcrew.summitsingh.com/api/auth/google/callback

CloudFormation sets PUBLIC_BASE_URL to that exact value in the API task. Local: a plain http localhost callback is NOT accepted by current code. Do not register a plain http URI and present it as working. Mocked login and callback tests cover the local flow without a provider.

## 3. Google setup steps, safe operator path

No credential value goes in the repo, in chat, in shell argv, in logs, or in docs. The private client ID and secret live only in a private Secrets Manager JSON secret with keys google-client-id and google-client-secret.

- [ ] Create a Web application OAuth client in the provider console.
- [ ] Set the authorized redirect URI from section 2 exactly.
- [ ] Confirm the requested scopes are exactly openid profile email.
- [ ] Store the private client ID and secret in Secrets Manager as JSON keys google-client-id and google-client-secret. Record only the secret ARN, never the values.
- [ ] Deploy with EnableGoogleAuth false and GoogleOAuthSecretArn empty for keyless default. AUTH_ENABLED stays false and no Google secret is injected.
- [ ] For an approved live test only, after deployment HTTPS is verified: set EnableGoogleAuth true plus the exact private GoogleOAuthSecretArn. The API task then receives GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET via ECS task secrets, and AUTH_ENABLED becomes true. The IAM grant ApiGoogleAuthPolicy allows secretsmanager:GetSecretValue only on that exact ARN, with no wildcard. No KMS grant is added; if the secret uses a customer managed key, add a key-scoped kms:Decrypt grant separately, never a wildcard.
- [ ] Set EnableGoogleAuth true only for a live sign-in test run with explicit operator approval, after deployment HTTPS is verified.

Provider console reports one approved external test user. That count alone proves nothing about live sign-in from this source. Do not present it as production access or verified sign-in.

## 4. Facebook and Meta, inactive in Google-only mode

- Facebook Login remains unpublished and inactive. No FACEBOOK_CLIENT_ID or FACEBOOK_CLIENT_SECRET is injected by deploy/aws/fargate.yaml.
- The UI shows a Google link only when /api/auth/status providers includes google. It shows no Facebook link in Google-only mode.
- No Meta credential is injected for auth. Leave Meta OAuth and unrelated proposal integrations for later work.

## 5. Session, status, rotation, expiry, logout, and UI cache

- Cookie name: launchcrew_session. Path: /api. Flags: Secure, HttpOnly, SameSite=lax, max age 8 hours.
- Sessions live server-side in Postgres table auth_sessions. Only a hashed opaque id is the key; the raw cookie value is never stored.
- Session lifetime: 8 hours (SESSION_HOURS in backend/auth.py). An expired session is refused with 401, and /api/auth/status reports no user.
- Status: /api/auth/status returns enabled, user, live_verified false, and providers. Providers is ['google'] when Google credentials are configured and auth is enabled, otherwise []. live_verified stays false until actual provider proof. Covered by backend/tests/test_google_auth.py.
- Rotation: login saves the OAuth state session and callback saves the signed-in session with a new opaque value, deleting the old session row. After rotation, the old cookie must get 401 on a protected endpoint. Covered by backend/tests/test_auth_hardening.py and backend/tests/test_google_auth.py.
- Logout: POST /api/auth/logout deletes the server session row and expires the client cookie. Logout is idempotent: a missing or already invalid cookie still returns signed_out true. After logout, a protected endpoint must return 401. The UI shows an explicit Sign out button when signed in. Sign-out plus sign-in plus user switch clear React Query caches for agents, queue, and run plus actor view state (active run, notice, error, export marker), so no previous actor data shows while refetching. Covered by backend/tests/test_google_auth.py, web/tests/google-auth.test.tsx, and web/tests/e2e/google-auth.spec.ts.
- Failure handling: callback failures return a generic identity verification failure. Provider errors and tokens are not put in responses, logs, receipts, or sessions.
- Fail closed: when AUTH_ENABLED is true but Google configuration or PUBLIC_BASE_URL is invalid, backend/auth.py validate_config raises and login plus callback refuse. Anonymous product requests get 401 when enabled. Keyless default is unchanged when disabled.

## 6. approval_by recording

- Disabled mode: approval_by is demo_placeholder everywhere, including receipt approvals, the approvals table, and audit actor.
- Enabled and signed in: approval_by is the signed-in Google user (google:subject). Approving a run must record that same value in three places: the receipt approvals entry, the approvals table row, and the audit row for approved_for_export. Covered by backend/tests/test_google_auth.py two-actor isolation.
- Never record a provider token, email address, or full profile as approval_by. Only provider:subject is recorded.

## 7. Test plan for live sign-in (requires explicit operator approval and deployment HTTPS, NOT in this task)

Do not run this plan until explicit operator approval is recorded and deployment HTTPS is verified. This plan is live-proof, not source-only. Source-only coverage in this repo uses mocked auth status and synthetic subjects only, with no live provider call and no verified sign-in.

- [ ] Confirm /api/health reports auth enabled_unverified and approval_by signed_in_user only after EnableGoogleAuth true plus the exact Google secret ARN is deployed.
- [ ] Confirm /api/auth/status shows providers ['google'] and live_verified false before sign-in.
- [ ] Google: open /api/auth/google/login, complete sign-in, confirm redirect to the app, confirm /api/auth/status shows the signed-in Google user, and confirm the callback URL matches section 2.
- [ ] Create a run, approve it, and confirm approval_by is the signed-in Google user in the receipt, the approvals table, and audit, not demo_placeholder.
- [ ] Confirm second-actor isolation with two real test subjects: each sees only its own queue, runs, memory, and campaigns, with 404 across actors.
- [ ] Confirm logout: after POST /api/auth/logout via the UI Sign out button, /api/auth/status shows no user and /api/queue returns 401, with no stale actor data shown.
- [ ] Confirm expiry handling: after the 8 hour session expiry, a protected endpoint returns 401 and re-login is required.
- [ ] Confirm rotation: after a fresh login and callback, the pre-callback cookie returns 401.
- [ ] Confirm scope check: the provider consent screen shows only the scopes in section 1.
- [ ] Rollback: set EnableGoogleAuth to false in the deployment parameters to return to demo_placeholder mode, and confirm /api/health reports disabled_demo.

## 8. What is NOT done

Live Google sign-in, Google production access, deployed status, live Spark, live SAM, CI execution, demo video, submission, connectors, Meta OAuth, and provisioning are all NOT done in this task. This checklist is source-only plus mocked-test coverage. Live sign-in remains unverified until the section 7 plan is approved and run against a verified HTTPS deployment. Do not claim tests pass, live OAuth, production access, or deployed status from this source change.
