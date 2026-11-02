# Competitive Gap Analysis for LaunchCrew

Date: 2026-11-01. Scope: hackathon demo for small business digital content (AI draft packs, human approval, receipts, multi-platform publishing, AI product images). Method: read LaunchCrew repo docs and code listings only (no code changes); fetched getsocialclaw.com pages; used official feature, pricing, and docs pages for competitors; used community reporting that quotes Reddit, G2, Trustpilot, and Capterra threads for pain points. Every claim below cites its source. No em dashes are used in this file by rule.

## 1. What LaunchCrew already implements

Sources: [README.md](../README.md), [gap-program.md](gap-program.md), route listing of `backend/app.py`, component listing of `web/src/components`, `agent_presets/` directory listing.

### 1.1 AI draft packs with human approval and receipts

- Scout, Maker, and Checker pipeline turns approved demo facts into a launch pack, with deterministic checks and a stored receipt per run ([README.md](../README.md)).
- Individual approval only. No batch approval and no automatic approval ([README.md](../README.md)).
- Server-bound approval integrity: copy and channel-variant copy are refused with 422 before approval ([README.md](../README.md)).
- Run review shows Checker blocking unverified claims, and receipts record the full check and event history ([README.md](../README.md)).
- Campaign Week creates seven pending packs in one transaction, each with its own approval and export gates ([README.md](../README.md)).
- Memory items and replay compare stored receipts without taking actions ([README.md](../README.md)).

### 1.2 Scheduling, calendar, and publishing

- Content calendar with week and month views, empty-slot gap indicators, and campaign placement that creates 7 slots ([README.md](../README.md)).
- Schedule slots with a 3-condition Validate Gate (pack approved, format check passed, channel variants approved) and schedule-export JSON ([README.md](../README.md)).
- Ready-slot autonomous publish executor with SHA-256 idempotency key, bounded retries, binding re-check at execution time, and a global kill switch ([README.md](../README.md)).
- Authorization model: once a slot is Ready, the executor may post autonomously at the scheduled time, while any post-approval edit drops the slot back to needs approval ([README.md](../README.md)).
- Cross-post verification board tracking pending to posted to verified, with exact-text match versus mismatch detection ([README.md](../README.md)).
- Social account connections for Instagram, Facebook, Threads, X, TikTok, Pinterest, YouTube, and LinkedIn, with Reddit, WordPress, Discord, and Telegram behind flags; personal-account block; encrypted tokens at rest; one-tap disconnect preserving receipts ([README.md](../README.md)).
- Routes observed in `backend/app.py` include `/api/calendar/slots`, `/api/publish/execute-due`, `/api/publish/kill-switch`, `/api/social/connections`, and `/api/calendar/schedule-export`.

### 1.3 AI creation and media

- Format library with aspect-ratio checks and channel capability cards ([README.md](../README.md)).
- Curated trend format picker with mandatory source labels and deterministic screening ([README.md](../README.md)).
- Media library: upload once with SHA-256 digests, non-destructive 4:5, 1:1, 16:9, and 9:16 derivatives, multi-channel attachment without re-upload ([README.md](../README.md)).
- Owner focal-point crop variants ([gap-program.md](gap-program.md)).
- Owner-saved post templates with gated apply ([gap-program.md](gap-program.md)).
- Viral format generator from owner screenshots or screen recordings plus confirmed product facts, gated by per-workspace credit cap ([README.md](../README.md)).
- AI product image characters library with render-ready prompt packs, plus OpenAI gpt-image-1, xAI grok-2-image, and Gemini imagen-4 adapters; keys stay in owner provider accounts; keyless requests fail closed with 503 ([gap-program.md](gap-program.md)).
- AI media creative packs for owner-shot media with draft provenance on the receipt ([gap-program.md](gap-program.md)).
- Seat roles on workspace keys: owner, editor, viewer, with viewer keys read-only ([gap-program.md](gap-program.md)).
- Custom agents and crew presets, including Drop and Finance presets with distinct Checker policies ([gap-program.md](gap-program.md), `agent_presets/` lists analyst, designer, drop, finance, research, support).

### 1.4 Analytics, outcomes, and agent surfaces

- Analytics pull restricted to verified posts, recording source label and fetched time, with unreported metrics shown as not reported instead of fake zeros ([README.md](../README.md)).
- Outcome capture on deliveries and runs ([README.md](../README.md), routes `/api/runs/{run_id}/outcomes` and `/api/calendar/slots/{slot_id}/deliveries/{channel}/outcomes` in `backend/app.py`).
- Agent surfaces: workspace-key REST API, hosted MCP server, CLI schedule apply, and an installable skill document sharing one validation logic ([README.md](../README.md)).
- Web UI panels observed in `web/src/components`: calendar-view, connections-view, media-library, format-library, trend-picker, verification-board, publish-executor-panel, analytics-pull-panel, viral-generator-panel, fact-library, product-facts-form, quickstart-templates, run-outcomes, resume-last-run, agent-surfaces-panel, drive-intake-form, import-suggestions-form, photo-check, model-status, theme-toggle, waitlist-form.

### 1.5 Explicitly not built (owner-gated or out of scope)

- Rendered video and voice bytes, live pixels, second-account proofs, demo video, and teardown verification ([gap-program.md](gap-program.md)).
- Live Spark model budget, live SAM photo check, and Google Drive OAuth remain blocked on external credits or allowlists and report honest fallback states ([README.md](../README.md)).
- Next in the gap program queue: engagement triage intake with suggested replies and approve-then-mark-handled but no auto-send; voice memo intake with transcript draft source; cloud storage connector that stays unconfigured by default ([gap-program.md](gap-program.md)).

## 2. SocialClaw (getsocialclaw.com) positioning and features

Sources: fetched pages at [SocialClaw home](https://getsocialclaw.com/), [scheduling API](https://getsocialclaw.com/social-media-scheduling-api), [scheduler](https://getsocialclaw.com/social-media-scheduler), and [cheapest social media API guide](https://getsocialclaw.com/blog/cheapest-social-media-api).

- Positioned as the publishing layer for AI agents, with dashboard, API, CLI, and MCP access ([SocialClaw home](https://getsocialclaw.com/)).
- Scheduler plans and queues posts across 11 networks ([SocialClaw scheduler](https://getsocialclaw.com/social-media-scheduler)).
- Platform list shown: Instagram, TikTok, X, LinkedIn, Facebook, YouTube, Reddit, Discord, Telegram, WordPress, Pinterest, Snapchat ([SocialClaw home](https://getsocialclaw.com/)).
- AI scheduler option where an agent picks slots and writes copy, plus management workspace with accounts, assets, and approvals ([SocialClaw home](https://getsocialclaw.com/)).
- Media studio generates video, voice, and images in app; analytics covers reach and engagement per account ([SocialClaw home](https://getsocialclaw.com/)).
- Viral video generator for AI-edited promo videos and a UGC creator marketplace for real human clips ([SocialClaw home](https://getsocialclaw.com/)).
- Developer surfaces: REST scheduling API with validate and apply, MCP server with 18 tools for Claude, ChatGPT, and Cursor, CLI for terminal or CI posting, and repeatable posting workflows ([SocialClaw home](https://getsocialclaw.com/)).
- Free tools for lead generation: Instagram caption generator, LinkedIn post generator, best-time-to-post calculator, schedule validator ([SocialClaw home](https://getsocialclaw.com/)).
- Pricing reported on its own comparison page: 7-day trial, plans from $15 per month for 3 accounts and 200 posts, up to $67 per month for 20 accounts and 1,000 posts, with full HTTP API on every plan ([SocialClaw Metricool alternatives](https://getsocialclaw.com/metricool-alternatives), [cheapest social media API guide](https://getsocialclaw.com/blog/cheapest-social-media-api)).

## 3. Competitor feature comparison (official sources)

### 3.1 Scheduling

- Buffer Publish plans and schedules content across social platforms, with per-channel posting times and time zones, queue, calendar, and send-now options ([Buffer pricing](https://buffer.com/pricing), [Martech Zone review of Buffer queue behavior](https://martech.zone/buffer-plan-publish-and-reply-in-one-place/)).
- Hootsuite offers unlimited scheduled posting, bulk scheduling of up to 350 posts at once, and best-time-to-post recommendations ([Hootsuite plans](https://www.hootsuite.com/plans), [Hootsuite review on per-user pricing](https://www.lilachbullock.com/hootsuite-pricing/)).
- Later offers a visual drag-and-drop calendar, bulk and CSV scheduling, recurring and seasonal content libraries, and per-network post customization ([Later schedulers guide](https://later.com/blog/best-social-media-schedulers/), [Later vs Buffer comparison](https://boomp.net/blog/later-vs-buffer-differences-comparison)).
- Canva Content Planner schedules designs directly to Facebook Pages, Instagram, LinkedIn, and other destinations from the editor ([Canva for social media, sourced from Canva pages](https://professionalstoolkit.com/articles/canva-for-social-media), [Hootsuite content calendar tools on Canva](https://blog.hootsuite.com/content-calendar-tools/)).
- Meta Business Suite creates or schedules posts, stories, and ads for Facebook and Instagram from one desktop or mobile place ([Meta Business Suite official](https://www.facebook.com/business/tools/meta-business-suite)).
- X offers native scheduled posts plus an Ads scheduling path; third-party dashboards publish through the X API at the scheduled minute ([X business scheduled posts help](https://business.x.com/en/help/campaign-editing-and-optimization/scheduled-tweets.html), [X API pricing explainer](https://kurums.com/x-api-pricing/)).
- Pippit AI (CapCut commerce product) lists schedule posting and a content publisher among its platform tools ([Pippit AI home](https://www.pippit.ai/)).

### 3.2 AI creation

- Buffer AI Assistant helps create, refine, and repurpose content, with an AI caption assistant on every plan ([Buffer pricing](https://buffer.com/pricing), [GoodFirms Hootsuite alternatives on Buffer AI](https://www.goodfirms.co/social-media-marketing-software/blog/best-hootsuite-alternatives)).
- Hootsuite AI assistant generates captions and images, with trend-based scripting assistance ([Hootsuite plans](https://www.hootsuite.com/plans), [Hootsuite review](https://www.saasblogging.com/hootsuite-review)).
- Later includes AI caption writing and hashtag suggestions ([Later schedulers guide](https://later.com/blog/best-social-media-schedulers/)).
- Canva ships Magic tools, templates, and Brand Kits; Business plans add 100 Brand Kits and brand controls ([Canva for social media, sourced from Canva pages](https://professionalstoolkit.com/articles/canva-for-social-media), [Hootsuite content calendar tools on Canva](https://blog.hootsuite.com/content-calendar-tools/)).
- Pippit AI offers a video agent, AI image generator, AI design, avatars, talking photos, product showcase, and background generation for e-commerce sellers ([Pippit AI home](https://www.pippit.ai/)).
- SocialClaw media studio generates video, voice, and images in app ([SocialClaw home](https://getsocialclaw.com/)).

### 3.3 Approvals

- Buffer offers one approval step on its Team plan, with in-app commenting and client collaboration invites ([Planable Hootsuite vs Buffer](https://planable.io/blog/hootsuite-vs-buffer/), [SelectHub Buffer vs Planable](https://www.selecthub.com/social-media-management-software-tools/buffer-vs-planable/)).
- Hootsuite keeps multi-layered approval workflows, permissions, and audit trails on its Advanced plan tier ([Planable Hootsuite vs Buffer](https://planable.io/blog/hootsuite-vs-buffer/), [SocialPilot Hootsuite alternatives](https://www.socialpilot.co/hootsuite-alternatives)).
- Later offers collaboration with submit-and-approve workflows and external feedback links on Growth and Scale plans ([Pallyy scheduling tools survey](https://pallyy.com/blog/social-media-scheduling-tools), [PostPlanify scheduling tools test](https://postplanify.com/blog/social-media-scheduling-tools)).
- Canva team plans support design approvals before publishing and brand controls that restrict members to kit colors and fonts ([Canva for social media, sourced from Canva pages](https://professionalstoolkit.com/articles/canva-for-social-media)).
- Meta Business Suite splits permissions into groups covering posts, approvals and publishing, content library, inbox, and client review ([RecurPost Meta Business Suite comparison](https://recurpost.com/compare/recurpost-vs-meta-business-suite/)).

### 3.4 Analytics

- Buffer rebuilt analytics as Insights, with performance overview, custom reports, exports, and AI takeaways on paid plans ([Metricool vs Buffer](https://professionalstoolkit.com/articles/metricool-vs-buffer), [Buffer review](https://www.linktly.com/marketing-software/buffer-review/)).
- Hootsuite offers customizable analytics reports and templates plus brand and competitor monitoring and benchmarking ([Hootsuite plans](https://www.hootsuite.com/plans), [Hootsuite review](https://kurums.com/hootsuite-review/)).
- Later includes built-in analytics with its visual planning workflow ([Later schedulers guide](https://later.com/blog/best-social-media-schedulers/)).
- Meta Business Suite ships free Insights with reach and engagement metrics for Pages and Instagram ([Meta Business Suite official](https://www.facebook.com/business/tools/meta-business-suite), [Brandwatch Facebook scheduling tools](https://www.brandwatch.com/blog/facebook-s)).
- X Analytics is available to X Premium subscribers with centralized metrics for Premium Business accounts ([ContentStudio X analytics tools](https://contentstudio.io/blog/twitter-analytics-tools), [X Premium Business profile reporting](https://twstalker.com/premiumbusiness)).
- Pippit AI lists data analytics and post performance reporting tied to scheduled content ([Pippit AI home](https://www.pippit.ai/), [Pippit AI ecommerce review](https://ecommerceguide.com/apps/capcut-commerce/)).

### 3.5 Inbox and engagement

- Buffer Community gives one shared inbox for engagement across accounts ([Buffer pricing](https://buffer.com/pricing), [Planable Hootsuite vs Buffer](https://planable.io/blog/hootsuite-vs-buffer/)).
- Hootsuite Nest unifies DMs, comments, and mentions with automations for replies and routing plus inbox reporting ([Hootsuite review](https://influencermarketinghub.com/hootsuite/), [Hootsuite alternatives on inbox](https://www.fs-poster.com/blog/cheaper-hootsuite-alternatives)).
- Meta Business Suite ships a unified inbox for Messenger and Instagram DMs plus comments in one free hub ([Meta Business Suite official](https://www.facebook.com/business/tools/meta-business-suite), [Sked Social Instagram tools](https://skedsocial.com/blog/best-instagram-automation-tools)).
- Later does not center on an inbox; its strength is visual planning, media library, grid preview, and Link in Bio ([Later vs Buffer comparison](https://boomp.net/blog/later-vs-buffer-differences-comparison)).
- X ships DMs and mentions natively, with API-based third-party inbox access gated by paid X API tiers ([X API pricing explainer](https://kurums.com/x-api-pricing/)).

### 3.6 Pricing posture (official pages, annual billing where stated)

- Buffer: free for 3 channels; paid from about $5 to $6 per channel per month; Team adds collaboration and approvals ([Buffer pricing](https://buffer.com/pricing), [Toolglade Buffer review](https://www.toolglade.com/tool/buffer)).
- Hootsuite: Standard $99, Professional $199, Advanced $399 per user per month on annual billing; approvals and advanced analytics sit at the top tier ([Hootsuite plans](https://www.hootsuite.com/plans), [Hootsuite pricing check](https://www.lilachbullock.com/hootsuite-pricing/)).
- Later: free plan for 1 channel; paid plans scale by social sets with collaboration and approvals on upper tiers ([Later schedulers guide](https://later.com/blog/best-social-media-schedulers/), [Later pricing](https://later.com/pricing/)).
- Canva: Pro around $15 per month with Content Planner scheduling; Teams per-user pricing adds approvals and brand controls ([Hootsuite content calendar tools on Canva](https://blog.hootsuite.com/content-calendar-tools/), [Canva for social media](https://professionalstoolkit.com/articles/canva-for-social-media)).
- Meta Business Suite: free for Facebook, Instagram, Messenger, and WhatsApp assets managed natively ([Meta Business Suite official](https://www.facebook.com/business/tools/meta-business-suite), [RecurPost Meta Business Suite comparison](https://recurpost.com/compare/recurpost-vs-meta-business-suite/)).
- SocialClaw: flat workspace pricing from $15 per month with API, CLI, and MCP on every plan ([SocialClaw Metricool alternatives](https://getsocialclaw.com/metricool-alternatives)).
- X API: pay-per-use including per-post publish fees, which third-party schedulers pass through in cost structure ([X API pricing explainer](https://kurums.com/x-api-pricing/)).

## 4. Community pain points (SMB owners, creators, and small agencies)

Sources here are community-reporting pages that quote Reddit threads, G2, Trustpilot, and Capterra reviews, plus practitioner essays. They are cited as reported pain, not as vendor claims.

- Manual cross-posting eats hours: posting the same content separately to each network, with replies scattered across inboxes and analytics trapped in each dashboard ([MediaOne management tools guide](https://mediaonemarketing.com.sg/social-media-management-tools-how-to-choose-and-use-them-effectively-in-2026/), [Agorapulse signs you need a new tool](https://www.agorapulse.com/blog/social-media-management/signs-you-need-a-new-social-media-tool/)).
- Approval purgatory is the top workflow complaint: clients forget to approve, feedback scatters across email and docs, versions get confused, and posts miss their publish window ([Planable agency workflow](https://planable.io/blog/social-media-workflow/), [Sked Social workflow challenges](https://skedsocial.com/en-au/blog/social-media-workflow-challenges)).
- Dedicated schedulers are seen as weak on approvals: one practitioner essay states Buffer and Hootsuite are scheduling tools first and were never really built for the approval process ([Medium approval problem essay](https://medium.com/@admin_3099/the-smm-approval-problem-nobody-talks-about-and-how-we-fixed-it-e6c19bc93ee1)).
- Price resentment clusters at two poles: Hootsuite per-seat pricing starting near $99 per user pushes out small teams, while per-channel pricing penalizes covering many networks ([Lilach Bullock Hootsuite alternatives](https://www.lilachbullock.com/best-hootsuite-alternatives-social-media-scheduling/), [Signal Daily scheduling value piece](https://news.sunbposolutions.com/social-media-scheduling-tools-worth-it-small-business), [Dev.to per-seat teardown](https://dev.to/saptadev27/stop-paying-per-seat-a-2026-pricing-teardown-of-10-social-media-automation-tools-5013)).
- Gated features sting: approvals and advanced analytics locked behind top tiers leave small-plan users feeling restricted ([Nuelink Hootsuite alternatives with user review complaints](https://blog.nuelink.com/hootsuite-alternatives/), [SocialPilot Hootsuite alternatives](https://www.socialpilot.co/hootsuite-alternatives)).
- Reddit-favored small-agency picks reward simple approvals, multi-client handling, and low price over suite depth: names recurring in Reddit-praised roundups include Publer, Metricool, SocialBee, and Planable for approval-heavy teams ([Themecoircle Reddit-praised tools](https://www.themecircle.net/top-6-reddit-praised-social-media-tools-built-for-small-agencies-handling-multiple-clients/), [Medium Hootsuite alternatives for SMB](https://medium.com/@lybatuoc6/what-are-the-best-hootsuite-alternatives-for-a-small-business-b88cdae28727)).
- Small businesses overpay for agency suites or underpay for tools that fail at Instagram publishing; either mistake costs more than the subscription ([Lilach Bullock scheduler chooser](https://www.lilachbullock.com/choose-social-media-post-scheduler/)).
- Content supply is the other half of the pain: solo owners have nothing to post, so AI-first drafting and product-to-post flows matter as much as scheduling ([Medium Hootsuite alternatives for SMB](https://medium.com/@lybatuoc6/what-are-the-best-hootsuite-alternatives-for-a-small-business-b88cdae28727), [AgentReacher startup playbook](https://agentreacher.com/blog/social-media-management-for-startups)).

## 5. Gap analysis: LaunchCrew versus the field

### 5.1 Where LaunchCrew leads or differentiates

- Claim-level honesty: Checker blocks unverified claims and receipts record the block, versus competitors whose AI assistants draft freely without a claim gate ([README.md](../README.md), [Buffer pricing AI assistant](https://buffer.com/pricing)).
- Receipts as proof: stored run receipts, replay diffs, and a verification board with exact-text match detection go further than standard publish logs ([README.md](../README.md), [Hootsuite plans reporting](https://www.hootsuite.com/plans)).
- Approval law with execution binding: binding re-check at publish time plus automatic demotion on post-approval edit is stricter than one-step approvals elsewhere ([README.md](../README.md), [Planable Hootsuite vs Buffer approvals](https://planable.io/blog/hootsuite-vs-buffer/)).
- Agent-native surfaces: REST plus MCP plus CLI plus skill document matches SocialClaw developer positioning while competitors mostly ship one API ([README.md](../README.md), [SocialClaw home](https://getsocialclaw.com/)).
- Flat workspace model with seat roles on keys undercuts per-seat pricing resentment ([gap-program.md](gap-program.md), [Dev.to per-seat teardown](https://dev.to/saptadev27/stop-paying-per-seat-a-2026-pricing-teardown-of-10-social-media-automation-tools-5013)).

### 5.2 Gaps that matter for the SMB pain point

- No unified inbox. Every direct rival except Later ships one; LaunchCrew engagement triage is intake only with no live comment pull ([gap-program.md](gap-program.md), [Hootsuite review inbox](https://influencermarketinghub.com/hootsuite/), [Meta Business Suite official](https://www.facebook.com/business/tools/meta-business-suite)).
- No best-time or auto-scheduling. Buffer, Hootsuite, Later, and SocialClaw free tools all guide timing; LaunchCrew slots are manual ([Later schedulers guide](https://later.com/blog/best-social-media-schedulers/), [SocialClaw home free tools](https://getsocialclaw.com/)).
- No bulk or CSV scheduling. Hootsuite bulk-schedules up to 350 posts; Later supports bulk and CSV; LaunchCrew places one campaign week at a time ([Hootsuite plans](https://www.hootsuite.com/plans), [Later vs Buffer comparison](https://boomp.net/blog/later-vs-buffer-differences-comparison)).
- No link-in-bio or landing destination. Buffer Start Page and Later Link in Bio are standard SMB must-haves; LaunchCrew has a landing-page verify route but no hosted bio page ([Buffer pricing](https://buffer.com/pricing), [Later schedulers guide](https://later.com/blog/best-social-media-schedulers/)).
- No first-comment or hashtag scheduling. Buffer schedules first comments and offers hashtag management; LaunchCrew has no equivalent ([Buffer pricing features via Martech Zone](https://martech.zone/buffer-plan-publish-and-reply-in-one-place/), [Later schedulers guide hashtag suggestions](https://later.com/blog/best-social-media-schedulers/)).
- No DM automation or saved replies. Hootsuite automates DM responses from Professional up; LaunchCrew triage explicitly forbids auto-send ([gap-program.md](gap-program.md), [Blotato automation tools](https://www.blotato.com/blog/social-media-automation-tools)).
- Thin analytics depth. Competitors add competitor benchmarking, best-time insight, exports, and AI takeaways; LaunchCrew analytics are pull-only on verified posts ([Metricool vs Buffer Insights](https://professionalstoolkit.com/articles/metricool-vs-buffer), [Hootsuite review](https://kurums.com/hootsuite-review/)).
- No social listening or brand monitoring. Hootsuite Lumen and native streams cover this; LaunchCrew trend picker is curated and manual ([Hootsuite review](https://influencermarketinghub.com/hootsuite/), [README.md](../README.md)).
- No video generation path. SocialClaw viral video generator, Pippit video agent, and Canva video all ship; LaunchCrew video bytes are explicitly out of scope ([SocialClaw home](https://getsocialclaw.com/), [Pippit AI home](https://www.pippit.ai/), [gap-program.md](gap-program.md)).
- Single-business workspace assumption. Agencies need multi-client workspaces and external approval links (Planable, Later Growth and Scale); LaunchCrew isolates per-actor workspaces with no client view ([Pallyy scheduling tools survey](https://pallyy.com/blog/social-media-scheduling-tools), [README.md](../README.md)).

## 6. Improvement ideas (mapped to pain)

- Finish engagement triage into a read-only unified inbox first: live comment pull stays owner-gated, drafts stay human-approved, mark-handled closes the loop. Kills inbox scatter without breaking the no-auto-send law ([gap-program.md](gap-program.md), [MediaOne inbox scatter](https://mediaonemarketing.com.sg/social-media-management-tools-how-to-choose-and-use-them-effectively-in-2026/)).
- Add best-time suggestions as guidance only, reusing the deterministic superlative-screening pattern from the trend picker, so timing advice can never become a false fact claim ([README.md](../README.md), [SocialClaw best-time calculator](https://getsocialclaw.com/)).
- Add bulk slot creation from the owner-template library: one template applied across N slots keeps individual approval intact while matching bulk-scheduling expectations ([gap-program.md](gap-program.md), [Hootsuite plans bulk schedule](https://www.hootsuite.com/plans)).
- Ship a hosted link-in-bio page generated from approved packs: smallest publishable destination that answers where the post sends buyers ([Buffer pricing Start Page](https://buffer.com/pricing), [Later schedulers guide](https://later.com/blog/best-social-media-schedulers/)).
- Add first-comment and hashtag scheduling to slots: cheap parity with Buffer and Later inside the existing Ready gate ([Later schedulers guide](https://later.com/blog/best-social-media-schedulers/), [Martech Zone Buffer queue](https://martech.zone/buffer-plan-publish-and-reply-in-one-place/)).
- Add receipt-backed analytics export (CSV and Markdown): turns the honesty advantage into a shareable client report ([Metricool vs Buffer exports](https://professionalstoolkit.com/articles/metricool-vs-buffer)).
- Add external read-only approval links for one client or partner: answers approval purgatory without building agency multi-workspace ([Planable agency workflow](https://planable.io/blog/social-media-workflow/), [Sked Social approval purgatory](https://skedsocial.com/en-au/blog/social-media-workflow-challenges)).
- Keep video out of the hackathon:Slideshow-from-derivatives (pan over existing 9:16 assets) is the only video-shaped scope that fits demo facts without provider bytes ([gap-program.md](gap-program.md), [Pippit AI product showcase](https://www.pippit.ai/tools/product-showcase-design)).

## 7. Must-have features for the SMB pain point

- One calendar across every connected network ([Meta Business Suite official](https://www.facebook.com/business/tools/meta-business-suite)).
- AI drafts constrained by owner facts with visible claim blocking ([README.md](../README.md)).
- One human approval tap before anything can publish ([Planable Hootsuite vs Buffer](https://planable.io/blog/hootsuite-vs-buffer/)).
- Proof it posted: receipts plus posted-to-verified tracking ([README.md](../README.md)).
- One inbox for comments and DMs ([Hootsuite review](https://influencermarketinghub.com/hootsuite/)).
- Timing guidance and bulk creation so a week of posts takes minutes ([Later vs Buffer comparison](https://boomp.net/blog/later-vs-buffer-differences-comparison)).
- A destination link for buyers: link-in-bio page ([Buffer pricing](https://buffer.com/pricing)).
- Flat, legible pricing with no per-seat shock ([Dev.to per-seat teardown](https://dev.to/saptadev27/stop-paying-per-seat-a-2026-pricing-teardown-of-10-social-media-automation-tools-5013)).

## 8. Prioritized build list for the hackathon

Ordered by demo impact per unit of scope. Each item fits the existing Slice pattern: keyless green path, owner-gated live path, receipt provenance.

1. Read-only unified inbox with approve-then-mark-handled triage. Completes queued Slice F with an owner-gated live pull. Direct answer to inbox scatter, the most universal competitor checkbox LaunchCrew lacks ([gap-program.md](gap-program.md), [Meta Business Suite official](https://www.facebook.com/business/tools/meta-business-suite)).
2. Best-time guidance plus bulk slot creation from owner templates. Matches Buffer, Later, and Hootsuite table stakes while keeping individual approval; biggest time-saving story for the demo narrative ([Later schedulers guide](https://later.com/blog/best-social-media-schedulers/), [Hootsuite plans](https://www.hootsuite.com/plans)).
3. Hosted link-in-bio page from approved packs. Smallest new surface, standard SMB must-have, gives every scheduled post somewhere to send buyers ([Buffer pricing](https://buffer.com/pricing), [Later schedulers guide](https://later.com/blog/best-social-media-schedulers/)).
4. First-comment and hashtag scheduling inside the Ready gate. Cheap parity, visible in every demo post, no new provider needed ([Martech Zone Buffer queue](https://martech.zone/buffer-plan-publish-and-reply-in-one-place/)).
5. Receipt-backed analytics export (CSV and Markdown). Turns the honesty differentiator into a client-ready report and answers thin-analytics criticism ([Metricool vs Buffer](https://professionalstoolkit.com/articles/metricool-vs-buffer)).
6. External read-only approval link for one reviewer. Attacks approval purgatory, the top community workflow complaint, without agency multi-workspace scope ([Planable agency workflow](https://planable.io/blog/social-media-workflow/), [Sked Social workflow challenges](https://skedsocial.com/en-au/blog/social-media-workflow-challenges)).
7. Slideshow-from-derivatives for 9:16 video-shaped output. Only if time remains; keeps the no-video-bytes law while showing motion in the demo ([gap-program.md](gap-program.md)).

Explicit non-goals for the hackathon window: social listening, DM automation, multi-client agency workspaces, native mobile apps, and rendered video or voice bytes ([gap-program.md](gap-program.md), [Hootsuite review listening scope](https://influencermarketinghub.com/hootsuite/)).

## 9. Top 5 recommended next features

1. Unified inbox with approve-then-mark-handled triage.
2. Best-time guidance plus bulk slot creation from owner templates.
3. Hosted link-in-bio page from approved packs.
4. First-comment and hashtag scheduling inside the Ready gate.
5. Receipt-backed analytics export in CSV and Markdown.
