# LaunchCrew AWS deployment preparation, Item C

Status: preparation only. Zero resources created. Zero DNS records created. No live endpoint exists. Provisioning requires a separate Summit authorization tap with a filled cost cap and budget period. This document authorizes no deployment or DNS operation.

Cost cap amount:

Budget period:

## Isolated resources and access

Plan a separate LaunchCrew demo account boundary where available, plus a dedicated resource group, VPC/network, subnets, security groups, and ECR repositories for API and web images. A resource group alone is an inventory boundary, not an access boundary. Enforce isolation with account and IAM policies and network rules. Make no Koru Shield production changes.

Use separate least-privilege IAM roles for image build, deployment, image pull, web execution, API execution, and database migration. Scope each role to its required resources and actions. The web role must have no database or provider-secret access. The API role may read only its own runtime configuration, including its own required provider secrets. Do not share secrets, roles, databases, or resource policies with any other project. Use no production data or production credentials. Keep human credentials outside the repository and application images.

Separate database migration privileges from runtime CRUD privileges. The current API Containerfile runs migrations at startup; before deployment, separate that operation from API runtime startup and execute it only with the migration role. Runtime database users must not acquire schema migration rights. This preparation makes no code or container changes.

## Region proposal

Recommend us-east-1, explicitly subject to Summit confirmation. The region is not confirmed and nothing is provisioned in it. Report the confirmed region and isolated resource inventory in any later authorized run.

## Public compute endpoint and TLS

Primary recommendation: evaluate App Runner services for API and web as the public container endpoint, fronted by Cloudflare at launchcrew.summitsingh.com. ECS Fargate with an appropriate public HTTPS endpoint is the alternate, also reachable through Cloudflare. The existing docs/aws-prep.md proposes ECS Fargate; these are preparation alternatives, not existing services.

Require verified TLS from browser to Cloudflare, Cloudflare to the HTTPS origin, and HTTPS from the endpoint to container targets. Local containers serve HTTP only. Origin and container TLS must be added and verified before any deployment. App Runner selection is conditional on proving the full required TLS path, including the container target hop; managed public HTTPS alone does not establish that requirement. If the proposed service cannot satisfy it, use a compatible public container endpoint, such as a validated ECS Fargate configuration. Do not waive container TLS to select a service.

Plan the web public base and API routing so the web calls the API through the approved public base. Verify custom-domain support, certificate validation and renewal, origin hostname validation, strict Cloudflare origin verification, secure cookies, exact allowed origins, and HTTPS identity-provider callback URLs before public exposure. Identity-provider configuration and real sign-in remain open gates. No DNS record, certificate, endpoint, or service is created by this preparation. Do not create launchcrew.summitsingh.com or any subdomain in this run.

## Postgres plan

Prefer isolated managed Postgres on RDS. An isolated container database is an alternate only after its persistence, backup, recovery, and maintenance plan is approved. Use private networking only, restrictive security groups, and no public database port. Plan private API connectivity and verify it with the selected compute service before deployment.

Require database TLS with certificate-chain and hostname verification, for example a client verify-full equivalent. Verify both API and migration connections use TLS and reject invalid certificates. Keep a separate migration role and database identity, with runtime CRUD permissions scoped to the application. The trust-auth configuration in local compose.yaml is development only and must never be used for deployment. Do not deploy trust authentication or the local plaintext database connection settings.

## Bounded logs and cost draft

Log retention limit: TBD, to be set to a finite value at provisioning time before services start. Do not log request bodies, headers, or secrets. Apply bounded retention to application, endpoint, database, and any enabled infrastructure logs. Report the log inventory, destinations, retention values, storage, and actual cost without secrets.

All estimates depend on the filled cost cap and budget period, confirmed region, selected architecture, and expected usage. No spending is authorized here.

| Line item | Draft estimate |
| --- | --- |
| Compute, API and web | TBD pending the filled cap and budget period |
| Load balancing/endpoint | TBD pending the filled cap and budget period |
| Managed Postgres | TBD pending the filled cap and budget period |
| Storage, including database snapshots and registry images | TBD pending the filled cap and budget period |
| Traffic | TBD pending the filled cap and budget period |
| TLS/certificate lifecycle | TBD pending the filled cap and budget period |
| Logs | TBD pending the filled cap and budget period |
| Total | TBD |

## Future authorized deployment verification only

Do not run these checks now. No live endpoint exists. Perform them only after a separate Summit deployment tap, a filled cost cap and budget period, and explicit future Cloudflare record authorization.

1. At https://launchcrew.summitsingh.com, verify WEB 200 for the web page, API 200 for the configured public API route, and WEB API 200 for an actual web request to the API through the public base. Record the exact routes and results without secrets. A direct API response alone does not verify the web-to-API path.
2. Confirm profiles and demo facts render using demo data only.
3. Confirm pending export refusal, clean approval success, blocked approval refusal, and JSON download of an approved demo artifact. Confirm refusal paths do not yield exportable artifacts.
4. Check HTTPS, certificate chains, hostnames, expiry and renewal plans, strict Cloudflare origin verification, and the HTTPS container target hop. Confirm no plaintext public API exposure.
5. Check verified database TLS from the deployed API and migration path, rejection of invalid certificates, private connectivity, and absence of a public database port.
6. Verify real identity-provider sign-in, session behavior, and the chosen public access boundary only in that separately authorized deployment. Do not claim mocked auth checks establish live sign-in.

## Teardown and reporting

Schedule teardown after Nov 4 and no later than Nov 9, 2026. Delete demo containers, database and snapshots, endpoint/service and any load balancer, registry images, network resources, provider secrets, certificates, and logs. Delete the one demo DNS record only if it was created in a later authorized run. Remove isolated IAM roles and remaining demo storage after dependencies are removed. Preserve only explicitly approved demo exports if requested.

Report resources and actual cost before provisioning, after provisioning, and after teardown, without secrets. Before provisioning, report the empty demo inventory and any verified actual cost separately from the draft estimate; no billing or credential access occurs in this run. After provisioning, include resource identifiers, region, endpoint, log inventory, retention, and actual cost. After teardown, independently verify deletion, endpoint unavailability, DNS removal if applicable, residual snapshots/images/logs/secrets/certificates, and any delayed charges. Report remaining resources and actual cost, and verify no recurring demo charges remain.

## Open gates and scope

- Filled cost cap amount and budget period.
- Separate Summit deployment authorization tap.
- Identity-provider credentials supplied securely outside the repo and real sign-in verification.
- Origin and container HTTPS, including proof the selected endpoint supports the full required TLS path.
- Verified database TLS and private connectivity.
- Region confirmation; us-east-1 remains a proposal.
- Explicit Cloudflare record authorization in a future run.
- Separate migration execution and runtime CRUD permissions before deployment.
- Independent teardown verification within the stated window.

SAM, CI, video, submission, and connectors are explicitly out of scope and are not claimed complete. No live Spark or live SAM calls, AWS provisioning, DNS creation, cost cap changes, AWS credential use, or META_API_KEY use occur in this preparation. No production changes occur.

## Local verification record

Docs-only, no code change, no backend test run required. Read docs/aws-prep.md, DEPLOY-CHECKLIST.md, README.md deployment/auth status sections, compose.yaml, and containers/*.Containerfile. Existing docs/aws-prep.md is unchanged.

Direct read-only check outside the Codex sandbox: podman pod ps returns no pods, and podman ps shows no running LaunchCrew containers. The LaunchCrew pod is down, so the compose.yaml execution path is unexecuted. Do not run compose up, build images, stop, rebuild, reset, or change Podman state. No Podman state was changed in this run. The one exited container visible in podman ps is unrelated to LaunchCrew and was left untouched.

No provisioning, DNS, live sign-in, SAM, CI, video, submission, connectors, Podman build, or compose execution was performed. Coordinator verification completed on the feature branch; main is untouched and no merge is claimed here.
