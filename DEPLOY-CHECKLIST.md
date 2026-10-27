# LaunchCrew deployment checklist, preparation only

No AWS or DNS commands are authorized in this run. Target is launchcrew.summitsingh.com only. This is an isolated demo, separate from Koru Shield production.

- [ ] Coordinator prices a smallest suitable container host or serverless container, TLS, logs, and Cloudflare custom-domain record. Recommend us-east-1, subject to confirmation.
- [ ] Summit fills cost cap: __________, budget period: __________, before actual provisioning. Provisioning is approved in principle when the web UI is ready; no provisioning in Stage C.
- [ ] Separate deployment and runtime IAM roles and resources, no production data, production credentials, or shared secrets. No database unless coordinator approved.
- [ ] Build Dockerfile locally and inspect the image contents. Python standard library only. No API key, .env, credentials, or receipt history in image. Run as non-root.
- [ ] Configure PORT (default 8765); container explicitly binds 0.0.0.0. Host startup remains local-only by default.
- [ ] Provide writable runs storage for non-root UID 10001. Single instance only for file-based receipts. Confirm restart persistence or accept temporary demo receipts explicitly.
- [ ] Set bounded log retention, no request bodies, headers, or secrets. Report inventory and cost before and after deployment.
- [ ] Configure HTTPS with valid TLS and custom-domain validation on the selected AWS endpoint.
- [ ] DNS creation for launchcrew.summitsingh.com is approved under the LaunchCrew-demo-only exception, with no other DNS change to the parent domain of launchcrew.summitsingh.com. In a later deployment stage, create the launchcrew.summitsingh.com record in Cloudflare, not Route53. Coordinator confirms the exact record target from the selected service, never assumes a generic service URL supports custom-domain TLS automatically.
- [ ] Health check: GET / returns 200, profiles and demo facts render. Confirm pending export refusal, clean approval success, blocked approval refusal, and JSON download. No external action routes.
- [ ] Before public exposure, choose an access boundary for the demo, such as Cloudflare Access. Current UI has no authentication; every visitor with access can approve demo receipts. Public exposure requires this separate deployment decision.
- [ ] Rollback: stop container/service, remove the Cloudflare demo DNS record, preserve only approved demo artifacts as needed, verify endpoint is unavailable.
- [ ] After Nov 4 through Nov 9: stop and delete isolated service and image artifacts, remove demo DNS and validation records, remove demo TLS resources when unused, delete demo logs/storage according to retention, remove isolated IAM roles after dependencies, and report remaining resources and actual cost.
- [ ] Final submission remains a separate Summit tap after demo readiness.
