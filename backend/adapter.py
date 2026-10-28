"""Reuse v1 agents, pipeline, and receipt gates without new run JSON files."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from launchcrew import agents, run, receipts
from backend.sam import verify_configured_demo

ROOT = Path(__file__).resolve().parents[1]


def preview(profile, idea):
    # Existing preview has no model calls. Temporary profile writes are avoided here.
    agents.validate(profile)
    return {'dry_run': True, 'profile': profile, 'sample_idea': idea,
            'first_action': 'Read facts_file, apply decision_rules, and prepare a draft for approval.',
            'model_called': False, 'side_effects': False}


def _memory_effects(memory_items):
    claims, blocked, expertise, used = [], [], None, []
    for item in (memory_items or []):
        content = item.get('content') if isinstance(item, dict) else {}
        if not isinstance(content, dict):
            content = {}
        used.append({'id': item.get('id'), 'kind': item.get('kind'), 'title': item.get('title')})
        claim = content.get('claim')
        if isinstance(claim, str) and claim.strip():
            if item.get('kind') == 'blocked_rule':
                blocked.append(claim)
            else:
                claims.append(claim)
        for extra in content.get('blocked_claims', []) if isinstance(content.get('blocked_claims'), list) else []:
            if isinstance(extra, str) and extra.strip():
                blocked.append(extra)
        if item.get('kind') == 'profile' and isinstance(content.get('expertise'), str) and content['expertise'].strip():
            expertise = content['expertise']
    return claims, blocked, expertise, used


def execute(run_id, idea, profile, seed, memory_items=None, checker_profile='standard', brief=None, campaign_day=None, extra_claims=None, profile_expertise=None):
    captured = []
    (ROOT / '.local').mkdir(exist_ok=True)
    claims, blocked, expertise, used = _memory_effects(memory_items)
    for claim in (extra_claims or []):
        if isinstance(claim, str) and claim.strip() and claim not in claims:
            claims.append(claim)
    if profile_expertise and isinstance(profile_expertise, str) and profile_expertise.strip():
        expertise = profile_expertise
    with TemporaryDirectory(dir=ROOT / '.local') as directory:
        for name in ('Scout', 'Maker', 'Checker'):
            agents.save_agent(agents.load_agent(name, ROOT / 'agents'), directory)
        maker = copy.deepcopy(profile)
        maker['name'] = 'Maker'
        if expertise:
            maker['expertise'] = expertise
        agents.save_agent(maker, directory)
        try:
            run.run_pipeline(idea, ROOT / 'facts/demo_facts.json', directory, run_id,
                             seed_unverified_claim=seed, model_enabled=True,
                             visual_verifier=verify_configured_demo,
                             receipt_writer=lambda receipt, path: captured.append(receipt),
                             memory_claims=claims, blocked_claims=blocked,
                             checker_profile=checker_profile, brief=brief, campaign_day=campaign_day)
        except Exception:
            if not captured:
                raise
    receipt = captured[0]
    receipt['memory_used'] = used
    receipt['checker_profile'] = checker_profile
    receipt['memory_claims'] = claims
    receipt['blocked_claims'] = blocked
    if brief is not None:
        receipt['campaign_brief'] = brief
    if campaign_day is not None:
        receipt['campaign_day'] = campaign_day
    if expertise:
        receipt['memory_profile_expertise'] = expertise
    return receipt


def export_pack(receipt):
    # Keep v1 export validation and serialization semantics.
    (ROOT / '.local').mkdir(exist_ok=True)
    with TemporaryDirectory(dir=ROOT / '.local') as directory:
        path = receipts.export_receipt(receipt, Path(directory) / 'pack.json')
        return path.read_bytes()
