# LaunchCrew AWS preparation only

No AWS resources, IAM identities, certificates, or DNS records were created in this run. This is a design, not a deployment script. Region proposed: us-east-1. Actual resources: none. Actual deployed region: none.

Cost cap amount: ______

Summit must fill the blank cost cap before any provisioning. No default amount is implied. Estimate container compute, load balancing, private Postgres, storage, traffic, and certificate lifecycle against that cap before approval.

## Isolated resources and IAM

Use a separate LaunchCrew demo resource group, network, security groups, container registry repositories for API and web, and dedicated nonproduction Postgres instance. Proposed compute is two containers on ECS Fargate. A private RDS Postgres instance stores receipts, memory, approvals, audit, and Authlib sessions. Do not share databases, IAM roles, secrets, or resource policies with any other project. No infrastructure implementation is included.

Use separate least-privilege roles for image building, deployment, container image pull, web execution, API execution, and database migration. The web role has no database or provider-secret access. The API role can read only its own runtime configuration and provider credentials. Migration rights are separate from runtime CRUD rights. Human provisioning credentials stay outside the app and repo. Do not use long-lived access keys. Identity providers use Authlib in FastAPI as the sole session authority.

## HTTPS and DNS

The only planned hostname is launchcrew.summitsingh.com through Cloudflare. DNS creation remains unperformed. Do not change parent or unrelated records. Use strict TLS validation from browser to Cloudflare, Cloudflare to an HTTPS origin, and load balancer to both HTTPS container targets. The prepared local containers serve HTTP only; add and verify origin and container TLS before deployment. Require verified TLS for API to Postgres, private database networking, secure HttpOnly SameSite cookies, exact public origin checks, and HTTPS OAuth callback URLs. No plaintext public API or database port.

## Teardown and outstanding gates

Schedule teardown after Nov 4 and no later than Nov 9, 2026. Export only approved demo artifacts if retention is requested, then delete demo containers, database and snapshots, load balancer, registry images, network resources, provider secrets, certificates, logs, and the one demo DNS record if created in a later authorized run. Independently verify no recurring charges remain. Report actual resource identifiers and region after any future provisioning, without secrets.

Open gates: owner cost cap, explicit deployment authorization in a future run, identity provider credentials and real sign-in verification, origin and container HTTPS, database TLS, resource and region review, Cloudflare record authorization in that future run, and independent teardown verification. Live Spark, live SAM, v2, and submission are separate and remain unverified or unbuilt. The local trust-auth database configuration is development only and must never be used for deployment.
