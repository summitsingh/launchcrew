# Facebook Login owner checklist (M4 blocker)

Status: code complete, unverified live. Routes, session store, token
exchange, UI buttons, and mocked tests are built. No Facebook app
credentials exist in this environment, so live Facebook sign-in is NOT
done and NOT claimed. Health stays enabled_unverified until the owner
records real end-to-end proof for both Google and Facebook.

## Blocker: create the Facebook app and supply credentials

No credential value goes in the repo, in chat, in shell argv, in logs,
in docs, or in screenshots. Values go only into the existing secret and
env mechanism (FACEBOOK_CLIENT_ID plus FACEBOOK_CLIENT_SECRET).

- [ ] In the Meta developer console, create an app with Facebook Login.
- [ ] Set Valid OAuth Redirect URIs to exactly:
  PUBLIC_BASE_URL plus /api/auth/facebook/callback.
  Production, when deployment is verified:
  https://launchcrew.summitsingh.com/api/auth/facebook/callback
- [ ] Request only public_profile and email. Request nothing broader.
- [ ] Copy the App ID into FACEBOOK_CLIENT_ID and the App Secret into
  FACEBOOK_CLIENT_SECRET through the existing secret and env mechanism.
  Record only the secret ARN, never the values.
- [ ] Add the app test users needed for review, complete any app review
  the console requires, and switch the app live only on owner approval.
- [ ] After deployment HTTPS is verified: sign in with Facebook in a
  browser, confirm redirect to the app, confirm /api/auth/status shows
  the signed-in Facebook display name with providers
  ['google', 'facebook'], then run for each provider:
  python scripts/verify_live_auth.py --provider <name>
  --owner-confirmed-live-signin
- [ ] Confirm /api/health reports enabled_verified only after both
  providers are recorded. Until then it must stay enabled_unverified
  (or disabled_demo when auth is off).

## What the code already does

- GET /api/auth/facebook/login starts the OAuth flow with scope
  public_profile email. GET /api/auth/facebook/callback exchanges the
  code server-side, reads id, name, and email from Graph, stores only
  provider:subject plus display name or email in the Postgres session,
  and never persists or returns provider tokens.
- The UI shows a Facebook link next to Google only when status
  providers includes facebook. The signed-in line labels the display
  name or email first and keeps the raw provider:subject id in data.
- Approvals record the signed-in actor (facebook:subject) in the
  receipt, the approvals table, and the audit row, same as Google.
