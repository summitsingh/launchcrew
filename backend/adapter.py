"""Reuse v1 agents, pipeline, and receipt gates without new run JSON files."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from launchcrew import agents, run, receipts
from launchcrew.checker_policies import FLOOR_NOTE, MATCHING_NOTE, describe_supported, parse_checker_agent
from backend.sam import verify_configured_demo

ROOT = Path(__file__).resolve().parents[1]


def preview(profile, idea):
    # Existing preview has no model calls. Temporary profile writes are avoided here.
    agents.validate(profile)
    enforcement = parse_checker_agent(profile)
    return {'dry_run': True, 'profile': profile, 'sample_idea': idea,
            'first_action': 'Read facts_file, apply decision_rules, and prepare a draft for approval.',
            'model_called': False, 'side_effects': False,
            'checker_enforcement': enforcement,
            'enforcement_note': FLOOR_NOTE + ' ' + MATCHING_NOTE,
            'supported_policies': describe_supported()}


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


def execute(run_id, idea, profile, seed, memory_items=None, checker_profile='standard', brief=None, campaign_day=None, extra_claims=None, profile_expertise=None, scout_profile=None, maker_profile=None, checker_agent=None):
    captured = []
    (ROOT / '.local').mkdir(exist_ok=True)
    claims, blocked, expertise, used = _memory_effects(memory_items)
    for claim in (extra_claims or []):
        if isinstance(claim, str) and claim.strip() and claim not in claims:
            claims.append(claim)
    if profile_expertise and isinstance(profile_expertise, str) and profile_expertise.strip():
        expertise = profile_expertise
    effective_scout = copy.deepcopy(scout_profile) if scout_profile is not None else agents.load_agent('Scout', ROOT / 'agents')
    effective_maker = copy.deepcopy(maker_profile) if maker_profile is not None else copy.deepcopy(profile)
    effective_checker = copy.deepcopy(checker_agent) if checker_agent is not None else agents.load_agent('Checker', ROOT / 'agents')
    for candidate in (effective_scout, effective_maker, effective_checker):
        agents.validate(candidate)
    if expertise:
        effective_maker['expertise'] = expertise
    with TemporaryDirectory(dir=ROOT / '.local') as directory:
        for stage, selected in (('Scout', effective_scout), ('Maker', effective_maker), ('Checker', effective_checker)):
            # Preserve the original profile identity in the stage file. The
            # pipeline loads by stage filename, so the custom name, role,
            # personality, expertise, and rules reach their actual stage.
            path = Path(directory) / (stage.lower() + '.json')
            path.write_text(json.dumps(selected, indent=2, sort_keys=True) + '\n', encoding='utf-8')
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
    receipt['legacy_agent_name'] = profile.get('name') if isinstance(profile, dict) else None
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
