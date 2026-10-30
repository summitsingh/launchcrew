"""Reuse v1 agents, pipeline, and receipt gates without new run JSON files."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from launchcrew import agents, run, receipts
from launchcrew.checker_policies import FLOOR_NOTE, MATCHING_NOTE, describe_supported, parse_checker_agent
from launchcrew.facts import parse_product_facts
from launchcrew.voice_profile import STYLE_ONLY_NOTICE, snapshot_digest, snapshot_version, validate_profile

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


def _voice_selection(memory_items):
    # First valid voice_profile in selection order wins. Examples are style
    # context only and never become facts; banned terms become Checker vetoes.
    # Fail closed: when selection holds at least one voice_profile but none
    # validates, raise instead of silently running with no enforcement.
    # Skipping an invalid entry to reach a later valid one still enforces
    # the later voice, so only the all-invalid case raises.
    seen_voice = False
    for item in (memory_items or []):
        if not isinstance(item, dict) or item.get('kind') != 'voice_profile':
            continue
        seen_voice = True
        content = item.get('content')
        if not isinstance(content, dict):
            continue
        try:
            snapshot = validate_profile(content)
        except (TypeError, ValueError):
            continue
        try:
            version = snapshot_version(snapshot)
            digest = snapshot_digest(snapshot)
        except (TypeError, ValueError):
            continue
        ref = {'id': item.get('id'), 'title': item.get('title'),
               'version': version, 'digest': digest}
        maker_examples = [{'input': ex['input'], 'approved_output': ex['output']}
                          for ex in snapshot.get('examples', [])]
        return snapshot, ref, maker_examples
    if seen_voice:
        raise ValueError('Invalid voice profile selected; failing closed with no silent drop')
    return None, None, []


def _memory_effects(memory_items):
    # Only brand_fact content.claim may extend the authoritative allowlist.
    # Approval examples and voice profiles are style context only and never
    # become facts. Blocked rules accept the explicit string format and the
    # learned list-of-dicts format; malformed values are ignored, never facts.
    claims, blocked, blocked_rules, expertise, approval_examples, used = [], [], [], None, [], []
    seen_blocked = set()

    def add_blocked(claim, reason, source):
        text = claim.strip()
        if not text or text in seen_blocked:
            return
        seen_blocked.add(text)
        blocked.append(text)
        blocked_rules.append({'id': source.get('id'), 'title': source.get('title'),
                              'claim': text, 'reason': reason})

    for item in (memory_items or []):
        content = item.get('content') if isinstance(item, dict) else {}
        if not isinstance(content, dict):
            content = {}
        kind = item.get('kind')
        used.append({'id': item.get('id'), 'kind': kind, 'title': item.get('title')})
        if kind == 'brand_fact':
            claim = content.get('claim')
            if isinstance(claim, str) and claim.strip() and claim.strip() not in claims:
                claims.append(claim.strip())
        elif kind == 'blocked_rule':
            claim = content.get('claim')
            if isinstance(claim, str) and claim.strip():
                add_blocked(claim, 'Selected memory rule', item)
            raw = content.get('blocked_claims')
            if isinstance(raw, list):
                for entry in raw:
                    if isinstance(entry, str) and entry.strip():
                        add_blocked(entry, 'Selected memory rule', item)
                    elif isinstance(entry, dict):
                        entry_claim = entry.get('claim')
                        entry_reason = entry.get('reason')
                        if isinstance(entry_claim, str) and entry_claim.strip():
                            reason = entry_reason if isinstance(entry_reason, str) and entry_reason.strip() else 'Learned blocked rule'
                            add_blocked(entry_claim, reason.strip(), item)
            # Any other blocked_rule fields are ignored: never approved facts.
        elif kind == 'approval_example':
            idea = content.get('idea')
            post = content.get('post')
            email = content.get('email')
            if not isinstance(idea, str) and isinstance(content.get('input'), str):
                idea = content.get('input')
            if not isinstance(post, str) and isinstance(content.get('approved_output'), str):
                post = content.get('approved_output')
            idea = idea if isinstance(idea, str) else ''
            post = post if isinstance(post, str) else ''
            email = email if isinstance(email, str) else ''
            if idea.strip() or post.strip() or email.strip():
                approval_examples.append({'id': item.get('id'), 'kind': kind, 'title': item.get('title'),
                                          'idea': idea, 'post': post, 'email': email})
            # content.claim on an approval example is intentionally ignored.
        elif kind == 'profile':
            if isinstance(content.get('expertise'), str) and content['expertise'].strip():
                expertise = content['expertise']
            # content.claim on a profile is intentionally ignored for the allowlist.
        elif kind == 'voice_profile':
            # Voice samples are style references only. Any content.claim,
            # content.examples, or content.banned_terms here never enters the
            # factual allowlist; banned terms are enforced separately as vetoes.
            pass
    return claims, blocked, blocked_rules, expertise, approval_examples, used


def execute(run_id, idea, profile, seed, memory_items=None, checker_profile='standard', brief=None, campaign_day=None, extra_claims=None, profile_expertise=None, scout_profile=None, maker_profile=None, checker_agent=None, progress_sink=None, stage_gate=None, product_facts=None, model_admission_factory=None):
    # Invalid product-fact input fails before any pipeline work, so the
    # API reports 422 instead of storing a run.
    parsed_product = parse_product_facts(product_facts)
    captured = []
    (ROOT / '.local').mkdir(exist_ok=True)
    claims, blocked, blocked_rules, expertise, approval_examples, used = _memory_effects(memory_items)
    voice_snapshot, voice_ref, voice_maker_examples = _voice_selection(memory_items)
    memory_sourced = list(claims)
    extras = []
    for claim in (extra_claims or []):
        if isinstance(claim, str) and claim.strip() and claim.strip() not in claims:
            claims.append(claim.strip())
            extras.append(claim.strip())
    if parsed_product is None:
        applied_memory = list(claims)
        withheld_memory = []
        withheld_briefs = []
    else:
        # Owner mode: selected memory items and campaign briefs are
        # suggestions only until the owner explicitly confirms them in
        # product_facts. Only typed confirmed facts become evidence.
        # Blocked-rule vetoes stay active in both modes.
        applied_memory = []
        confirmed_set = set(parsed_product['confirmed_claims'])
        withheld_memory = [c for c in memory_sourced if c not in confirmed_set]
        withheld_briefs = [c for c in extras
                           if c not in confirmed_set and c not in withheld_memory]
    if profile_expertise and isinstance(profile_expertise, str) and profile_expertise.strip():
        expertise = profile_expertise
    effective_scout = copy.deepcopy(scout_profile) if scout_profile is not None else agents.load_agent('Scout', ROOT / 'agents')
    effective_maker = copy.deepcopy(maker_profile) if maker_profile is not None else copy.deepcopy(profile)
    effective_checker = copy.deepcopy(checker_agent) if checker_agent is not None else agents.load_agent('Checker', ROOT / 'agents')
    for candidate in (effective_scout, effective_maker, effective_checker):
        agents.validate(candidate)
    if expertise:
        effective_maker['expertise'] = expertise
    for example in approval_examples:
        post = example.get('post', '')
        email = example.get('email', '')
        if post.strip() and email.strip() and email.strip() != post.strip():
            approved_output = post + '\n\n--- email variant (style reference only) ---\n' + email
        else:
            approved_output = post if post.strip() else email
        merged = {'input': example.get('idea', '') if example.get('idea', '').strip() else 'Approved example (style reference only)',
                  'approved_output': approved_output if approved_output.strip() else 'Approved example output (style reference only)'}
        effective_maker.setdefault('examples', []).append(merged)
    for voice_example in voice_maker_examples:
        # Versioned voice snapshot as Maker style context only. Samples never
        # enter the factual allowlist; they only shape phrasing prompts.
        effective_maker.setdefault('examples', []).append({
            'input': voice_example.get('input', ''),
            'approved_output': voice_example.get('approved_output', ''),
        })
    agents.validate(effective_maker)
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
                             receipt_writer=lambda receipt, path: captured.append(receipt),
                             memory_claims=applied_memory, blocked_claims=blocked,
                             checker_profile=checker_profile, brief=brief, campaign_day=campaign_day,
                             progress=progress_sink, stage_gate=stage_gate,
                             product_facts=product_facts,
                             model_admission_factory=model_admission_factory,
                             voice_snapshot=voice_snapshot, voice_ref=voice_ref)
        except Exception:
            if not captured:
                raise
    receipt = captured[0]
    receipt['memory_used'] = used
    receipt['checker_profile'] = checker_profile
    receipt['memory_claims'] = applied_memory
    if receipt.get('voice_profile') is None and voice_ref is not None:
        # Pipeline already stores the versioned snapshot; this fallback keeps
        # the source/version visible if the pipeline path predates voice.
        receipt['voice_profile'] = {'id': voice_ref.get('id'), 'title': voice_ref.get('title'),
                                    'version': voice_ref.get('version'), 'digest': voice_ref.get('digest'),
                                    'example_count': len(voice_maker_examples),
                                    'banned_term_count': len((voice_snapshot or {}).get('banned_terms', [])),
                                    'banned_terms': list((voice_snapshot or {}).get('banned_terms', [])),
                                    'notice': STYLE_ONLY_NOTICE}
    if isinstance(receipt.get('product_facts'), dict):
        suggested = receipt['product_facts'].setdefault('suggested', [])
        for claim in withheld_memory:
            suggested.append({'field': 'memory', 'label': 'Memory suggestion',
                              'value': claim, 'source': 'memory',
                              'reason': 'Selected memory is a suggestion until explicitly confirmed in product_facts'})
        for claim in withheld_briefs:
            suggested.append({'field': 'campaign_brief', 'label': 'Campaign brief suggestion',
                              'value': claim, 'source': 'campaign_brief',
                              'reason': 'Campaign brief is planning context until explicitly confirmed in product_facts'})
    receipt['blocked_claims'] = blocked
    receipt['memory_blocked_rules'] = blocked_rules
    receipt['memory_examples'] = approval_examples
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
