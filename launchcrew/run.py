"""LaunchCrew demo pipeline. Local drafts and receipts only."""
import argparse
import copy
import json
import os
from pathlib import Path

from . import agents
from .checker_policies import effective_policies, parse_checker_agent, policy_blocks, policy_reason
from .facts import (OWNER_SOURCE_LABEL, check_sentence, check_claims, check_draft,
                     founder_variant, load_facts, normalize, parse_product_facts,
                     product_section, split_sentences)
from .receipts import create_receipt, save_receipt, timestamp, failed_receipt
from .model_meta import (DATA_BASIS_V2, data_mode_for_attempts, sanitize_model_name,
                         variant_for_attempt)
from .spark import spark_for_agent
from .wonder import wonder_synthesize_for_scout


STRICT_HYPE = ('amazing', 'incredible', 'revolutionary', 'unbeatable', 'perfect',
               'best', 'greatest', 'fastest', 'cheapest', 'only', 'guaranteed')


def _blocked_names(blocked_claims):
    return {normalize(c) for c in (blocked_claims or []) if isinstance(c, str) and normalize(c)}


def _effective_policies(checker_profile, checker_policies, checker_agent):
    if checker_policies is not None:
        return sorted({str(p) for p in checker_policies if isinstance(p, str)})
    return effective_policies(checker_profile, checker_agent)


def _policy_block_for_claim(claim, policies):
    for policy in policies:
        if policy_blocks(policy, claim):
            return {'claim': claim, 'reason': policy_reason(policy)}
    return None


def check_pack(draft, facts, blocked_claims=None, checker_profile='standard', checker_policies=None, checker_agent=None):
    # Deterministic claim safety is never skipped: blocked_claims and the
    # supported policies only add blocks, they never verify an unverified claim.
    # Legacy keys verified_count, blocked_count, blocked_claims, and
    # revision_instructions keep their exact shapes. New claim_results adds
    # per-claim verdict (supported/unsupported/conflicts) with quoted fact
    # evidence, while retaining legacy verified booleans. Verdict is factual;
    # verified is final (factual plus blocked rules and policy).
    policies = _effective_policies(checker_profile, checker_policies, checker_agent)
    blocked_names = _blocked_names(blocked_claims)
    results = check_claims(draft['claims'], facts)
    blocked = []
    claim_results = []
    seen_texts = set()
    for r in results['results']:
        if normalize(r['claim']) in blocked_names:
            blocked.append({'claim': r['claim'], 'reason': 'Blocked by selected memory rule'})
            claim_results.append({'claim': r['claim'], 'verified': False,
                                  'verdict': r.get('verdict', 'unsupported'),
                                  'evidence': r.get('evidence'),
                                  'reason': 'Blocked by selected memory rule',
                                  'blocked': True, 'source': 'explicit_claim'})
        elif not r['verified']:
            blocked.append(r)
            claim_results.append({'claim': r['claim'], 'verified': False,
                                  'verdict': r.get('verdict', 'unsupported'),
                                  'evidence': r.get('evidence'), 'reason': r['reason'],
                                  'blocked': True, 'source': 'explicit_claim'})
        else:
            hit = _policy_block_for_claim(r['claim'], policies)
            if hit is not None:
                blocked.append(hit)
                claim_results.append({'claim': r['claim'], 'verified': False,
                                      'verdict': r.get('verdict', 'supported'),
                                      'evidence': r.get('evidence'),
                                      'reason': hit['reason'],
                                      'blocked': True, 'source': 'explicit_claim'})
            else:
                claim_results.append({'claim': r['claim'], 'verified': True,
                                      'verdict': r.get('verdict', 'supported'),
                                      'evidence': r.get('evidence'), 'reason': r['reason'],
                                      'blocked': False, 'source': 'explicit_claim'})
        seen_texts.add(r['claim'])
    for result in check_draft(draft['post'] + '\n' + draft['email'], facts):
        if result['claim'] not in [r['claim'] for r in blocked]:
            if normalize(result['claim']) in blocked_names:
                blocked.append({'claim': result['claim'], 'reason': 'Blocked by selected memory rule'})
            else:
                hit = _policy_block_for_claim(result['claim'], policies)
                if hit is not None:
                    blocked.append(hit)
                else:
                    blocked.append(result)
    # Draft-text verdicts for every unique sentence, including supported ones
    # that check_draft omits. Explicit-claim texts are not duplicated.
    for sentence_result in (check_sentence(s, facts) for s in split_sentences(
            (draft.get('post') or '') + '\n' + (draft.get('email') or ''))):
        text = sentence_result['claim']
        if text in seen_texts:
            continue
        seen_texts.add(text)
        if normalize(text) in blocked_names:
            claim_results.append({'claim': text, 'verified': False,
                                  'verdict': sentence_result.get('verdict', 'unsupported'),
                                  'evidence': sentence_result.get('evidence'),
                                  'reason': 'Blocked by selected memory rule',
                                  'blocked': True, 'source': 'draft_text'})
        elif not sentence_result['verified']:
            claim_results.append({'claim': text, 'verified': False,
                                  'verdict': sentence_result.get('verdict', 'unsupported'),
                                  'evidence': sentence_result.get('evidence'),
                                  'reason': sentence_result['reason'],
                                  'blocked': True, 'source': 'draft_text'})
        else:
            hit = _policy_block_for_claim(text, policies)
            if hit is not None:
                claim_results.append({'claim': text, 'verified': False,
                                      'verdict': sentence_result.get('verdict', 'supported'),
                                      'evidence': sentence_result.get('evidence'),
                                      'reason': hit['reason'],
                                      'blocked': True, 'source': 'draft_text'})
            else:
                claim_results.append({'claim': text, 'verified': True,
                                      'verdict': sentence_result.get('verdict', 'supported'),
                                      'evidence': sentence_result.get('evidence'),
                                      'reason': sentence_result['reason'],
                                      'blocked': False, 'source': 'draft_text'})
    verified = sum(1 for c in draft['claims'] if c not in [b['claim'] for b in blocked])
    supported = sum(1 for r in claim_results if r['verdict'] == 'supported')
    unsupported = sum(1 for r in claim_results if r['verdict'] == 'unsupported')
    conflicts = sum(1 for r in claim_results if r['verdict'] == 'conflicts')
    return {'verified_count': verified, 'blocked_count': len(blocked),
            'blocked_claims': [{'claim': r['claim'], 'reason': r['reason']} for r in blocked],
            'revision_instructions': ['Remove ' + r['claim'] + '; replace with an approved facts file claim.' for r in blocked],
            'claim_results': claim_results, 'supported_count': supported,
            'unsupported_count': unsupported, 'conflicts_count': conflicts}


def make_draft(claims):
    # Deterministic keyless fallback: safe, labelled, never model-written.
    # Separate sentences keep the draft and explicit claims auditable together.
    # Post and email stay identical here for legacy fallback compatibility;
    # model-safe drafts use make_distinct_draft for channel structure.
    text = '. '.join(claims) + '.'
    return {'post': text, 'email': text, 'claims': list(claims),
            'draft_origin': 'deterministic_fallback', 'model_written': False,
            'maker_schema': 'none_fallback', 'model_used': 'none'}


def _distinct_post_email(claims):
    # Format-specific structure from safe claims only, no extra factual
    # wording. Post is a single paragraph in order; email is one claim per
    # line in reverse order when that stays distinct. Both split into the
    # same verified sentences, so Checker still passes. Distinctness is
    # formatting and order only, not new copy. Honest limit: single-claim
    # drafts differ only by trailing period vs bare line.
    if not claims:
        return '.', '.'
    post = '. '.join(claims) + '.'
    ordered = list(reversed(claims)) if len(claims) > 1 else list(claims)
    email = '\n'.join(c.strip().rstrip('.!?') for c in ordered)
    if email == post:
        email = '\n'.join(ordered)
    return post, email


def make_distinct_draft(claims, model_used=None, maker_schema='structured_post_email'):
    # Model-safe draft: distinct post/email built only from independently
    # verified safe claims. Caller must have rejected every unsafe sentence
    # via check_pack before calling. Model metadata is measured, not claimed.
    post, email = _distinct_post_email(list(claims))
    return {'post': post, 'email': email, 'claims': list(claims),
            'draft_origin': 'model_safe', 'model_written': True,
            'maker_schema': maker_schema, 'model_used': model_used or 'unknown'}


def _clean_model_lines(lines):
    cleaned = []
    for line in lines or []:
        if not isinstance(line, str):
            continue
        text = line.strip()
        if text:
            cleaned.append(text)
    return cleaned


SEED_CLAIM = 'best in Texas'


def _seed_marker(seed_enabled, v1_claims=None, v1=None, v2_claims=None, v2=None):
    # Explicit deterministic marker for the demo test seed. v1 records the
    # unsupported claim and its block; v2 always removes it. Holds under both
    # model-safe and deterministic fallback paths.
    claim = SEED_CLAIM if seed_enabled else None
    v1_included = bool(seed_enabled and v1_claims is not None and SEED_CLAIM in (v1_claims or []))
    if not v1_included and seed_enabled and isinstance(v1, dict):
        text = (v1.get('post') or '') + '\n' + (v1.get('email') or '')
        v1_included = SEED_CLAIM in text
    v2_included = False
    if isinstance(v2, dict):
        text = (v2.get('post') or '') + '\n' + (v2.get('email') or '')
        v2_included = SEED_CLAIM in list(v2_claims or []) or SEED_CLAIM in text
    elif v2_claims is not None:
        v2_included = SEED_CLAIM in list(v2_claims or [])
    return {'enabled': bool(seed_enabled), 'claim': claim,
            'v1_included': bool(v1_included), 'v2_included': bool(v2_included),
            'v2_removed': bool(seed_enabled and v1_included and not v2_included),
            'note': 'Demo test seed only; v1 records the block, v2 removes it.'}


def _sanitized_model_name(name):
    return sanitize_model_name(name)


def _attempt_variant(kind, result):
    if not result.get('attempted', False):
        return None
    if result.get('mode') == 'spark':
        name = result.get('model_used')
    else:
        name = result.get('attempted_model', result.get('model_used'))
    return variant_for_attempt(kind, name)


def _attempt_pair(kind, result):
    variant = _attempt_variant(kind, result)
    if variant is None:
        return None
    provider = result.get('request_provider')
    if not isinstance(provider, str) or provider not in ('meta', 'unknown', 'none'):
        provider = 'unknown'
    if provider == 'none':
        provider = 'unknown'
    return (variant, provider)


def _data_mode_for_attempts(attempted_variants):
    pairs = [(v, 'meta') for v in attempted_variants]
    mode, note, _ = data_mode_for_attempts(pairs)
    return (mode, note)


def model_usage(attempts):
    """Only allowlisted metadata can reach persistent receipts."""
    successful = [r for _, r in attempts if r['mode'] == 'spark']
    attempted_pairs = [(kind, r) for kind, r in attempts if r.get('attempted', False)]
    attempted = [r for _, r in attempted_pairs]
    errors = [r['error_type'] for _, r in attempts if r.get('error_type')]
    pairs = [_attempt_pair(kind, r) for kind, r in attempted_pairs]
    pairs = [p for p in pairs if p is not None]
    data_mode, data_mode_note, aggregate = data_mode_for_attempts(pairs)
    sanitized_successful = [_sanitized_model_name(r.get('model_used')) for r in successful]
    first_model = successful[0].get('model_used') if successful else 'none'
    first_model = first_model if first_model == 'none' or _sanitized_model_name(first_model) != 'unknown' else 'unknown'
    return {'spark_calls': sum(int(r.get('attempted', False)) for kind, r in attempts if kind == 'spark'),
            'spark_mode': 'spark' if successful else 'deterministic_fallback',
            'mode': 'spark' if successful else (errors[0] if errors else 'deterministic_fallback'),
            'model_used': first_model,
            'models_used': sorted(set(sanitized_successful)),
            'error_types': errors, 'wonder_used': any(kind == 'wonder' and r['mode'] == 'spark' for kind, r in attempts),
            'wonder_attempts': sum(int(r.get('attempted', False)) for kind, r in attempts if kind == 'wonder'),
            'token_counts': {name: sum(r.get('usage', {}).get(name, 0) for _, r in attempts)
                             for name in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
            'tokens_known': bool(attempted) and all('total_tokens' in r.get('usage', {}) for r in attempted),
            'data_mode': data_mode,
            'data_mode_note': data_mode_note,
            'data_basis': DATA_BASIS_V2,
            'request_provider': aggregate}


def _snapshot_examples(profile):
    # Allowlisted deep copy of profile examples only: input and
    # approved_output strings. Anything else on an example entry (including
    # anything credential-like) is dropped, and non-string or blank entries
    # are skipped. Examples are untrusted style references for prompts, never
    # verified facts: they never enter the review allowlist, which is built
    # only from sourced Scout facts with verified is True.
    snapshot = []
    examples = profile.get('examples')
    if not isinstance(examples, list):
        return snapshot
    for example in examples:
        if not isinstance(example, dict):
            continue
        given = example.get('input')
        shown = example.get('approved_output')
        if not isinstance(given, str) or not isinstance(shown, str):
            continue
        if not given.strip() and not shown.strip():
            continue
        snapshot.append({'input': given[:2000], 'approved_output': shown[:2000]})
    return snapshot


def _stage_snapshot(profile):
    return {'name': profile.get('name'), 'role': profile.get('role'),
            'personality': profile.get('personality'), 'expertise': profile.get('expertise'),
            'decision_rules': list(profile.get('decision_rules', [])),
            'veto_scope': list(profile.get('veto_scope', [])),
            'examples': _snapshot_examples(profile)}


def run_pipeline(idea, facts_path, agents_path, out, approve=False, seed_unverified_claim=False, receipt_writer=save_receipt, model_enabled=True, visual_verifier=None, memory_claims=None, blocked_claims=None, checker_profile='standard', brief=None, campaign_day=None, scout_profile=None, maker_profile=None, checker_agent=None, progress=None, stage_gate=None, product_facts=None):
    """Optional progress(event) is called at real stage boundaries only: each
    call corresponds to pipeline work that already happened (completed) or
    is about to happen (started). The event dict carries stage, state,
    profile, evidence, and timestamp. Each completed stage emits one event
    and one receipt audit entry for the same observed moment, so the two
    share their timestamp and profile; started notes keep their own earlier
    readings. The prepared receipt event and the completed note are
    different observations (prepared vs stored) with distinct readings.
    Optional stage_gate(stage) is called before each stage's work; it
    exists for controlled timing tests and defaults to unused. Both stay
    plain stdlib callables so the core gains no transport dependency."""
    model_enabled = model_enabled and bool(os.environ.get('META_API_KEY', '').strip())
    events = []
    attempts = []
    step = 'load_agents'
    profiles = None
    effective = []
    enforcement = None
    parsed_product = None
    product_allowlist = []
    try:
        overrides = {'Scout': scout_profile, 'Maker': maker_profile, 'Checker': checker_agent}
        profiles = {}
        for name in ('Scout', 'Maker', 'Checker'):
            override = overrides.get(name)
            if override is not None:
                profiles[name] = agents.validate(copy.deepcopy(override))
            else:
                profiles[name] = agents.load_agent(name, agents_path)
        effective = effective_policies(checker_profile, profiles['Checker'])
        enforcement = parse_checker_agent(profiles['Checker'])
        enforcement['effective_policies'] = list(effective)
        enforcement['legacy_checker_profile'] = checker_profile
        step = 'load_facts'
        parsed_product = parse_product_facts(product_facts)
        facts, _ = load_facts(facts_path)
        if parsed_product is None:
            claims = list(facts['approved_claims'])
            for claim in (memory_claims or []):
                if isinstance(claim, str) and claim.strip() and claim not in claims:
                    claims.append(claim)
        else:
            # Owner mode: the demo template never becomes owner evidence.
            # Only explicitly confirmed owner claims authorize drafts.
            # Memory and brief inputs stay as suggestions or planning
            # context handled by the caller. Suggestions stay out.
            # Safety: rebuild the facts object from confirmed claims only,
            # dropping every bundled demo field (material, price, product,
            # audience, channel, brand_voice, design) so check_claim and
            # check_sentence cannot match unconfirmed demo values even via
            # blob containment. Verdicts also ignore non-allowlist values.
            claims = list(parsed_product['confirmed_claims'])
            facts = {'approved_claims': list(claims), 'sources': [OWNER_SOURCE_LABEL],
                     'memory_claims': list(memory_claims or [])}
        if parsed_product is None:
            facts['approved_claims'] = list(claims)
            facts['memory_claims'] = list(memory_claims or [])
        product_allowlist = list(claims)
        blocked_names = _blocked_names(blocked_claims)

        def event(step, agent, action, profile_name=None, at=None):
            events.append({'step': step, 'agent': agent, 'profile': profile_name or agent,
                           'action': action, 'timestamp': at or timestamp()})

        def note(stage, state, profile_name=None, evidence=None, at=None):
            if progress is None:
                return
            progress({'stage': stage, 'state': state, 'profile': profile_name or stage,
                      'evidence': dict(evidence or {}),
                      'timestamp': at if isinstance(at, str) and at else timestamp()})

        def reached(stage, agent, action, profile_name=None, evidence=None):
            # One observed completion, one shared clock reading: the stored
            # step row and the receipt event describe the same moment, so
            # they carry the same timestamp and profile. Started notes keep
            # their own earlier readings. The prepared receipt event and the
            # stored terminal row are different observations (prepared vs
            # committed) and stay distinct.
            at = timestamp()
            event(stage, agent, action, profile_name, at=at)
            note(stage, 'completed', profile_name, evidence, at=at)

        def gate(stage):
            if stage_gate is not None:
                stage_gate(stage)

        # Deterministic checks run before any model call.
        step = 'deterministic_checks'
        gate('deterministic_checks')
        note('deterministic_checks', 'started', 'Scout')
        initial = check_claims(claims, facts)
        if initial['blocked_count']:
            raise ValueError('Approved facts failed deterministic checks')
        reached('deterministic_checks', 'Scout', 'Checked facts file before optional synthesis', profiles['Scout']['name'],
                {'facts': len(claims)})
        task = json.dumps({'idea': idea, 'approved_claims': claims, 'sources': facts['sources']})
        step = 'scout'
        gate('scout')
        note('scout', 'started', profiles['Scout']['name'])
        wonder = wonder_synthesize_for_scout(task, None, profiles['Scout']) if model_enabled else None
        if wonder is not None:
            attempts.append(('wonder', wonder))
        wonder_used = wonder is not None and wonder['mode'] == 'spark'
        model = wonder if wonder_used else (spark_for_agent(profiles['Scout'], task, stage='Scout') if model_enabled else {
            'mode': 'deterministic_fallback', 'model_used': 'none', 'attempted': False})
        if not wonder_used:
            attempts.append(('spark', model))

        def model_candidate(name, text):
            if not model_enabled:
                return None
            result = spark_for_agent(profiles[name], text, stage=name)
            attempts.append(('spark', result))
            return result if result['mode'] == 'spark' else None

        scout = {'facts_used': [{'claim': c, 'verified': True, 'verdict': 'supported',
                                        'evidence': c, 'sources': facts['sources']} for c in claims],
                 'risks': ['Risk 1: Unsupported product claims require revision.',
                           'Risk 2: Channel suitability is unverified by this facts file.',
                           'Risk 3: Price and availability need human review before export.'],
                 'sources': facts['sources'], 'model_mode': model['mode'],
                 'model_note': model.get('error_type', 'Optional Scout synthesis received.' if model['mode'] == 'spark' else 'No model synthesis.')}
        if model['mode'] == 'spark':
            raw = model['raw_json']
            candidates = raw.get('facts_used', [])
            if isinstance(candidates, list):
                for candidate in candidates:
                    if isinstance(candidate, str) and candidate not in claims:
                        result = check_sentence(candidate, facts)
                        scout['facts_used'].append({**result, 'sources': facts['sources'] if result['verified'] else []})
            # Risks are hypotheses for review, never approved product facts.
            risks = raw.get('risks', [])
            if isinstance(risks, list):
                scout['risks'].extend('Unverified model risk: ' + r for r in risks if isinstance(r, str))
        reached('scout', 'Scout', 'Produced sourced facts and demo risks; filtered optional model facts', profiles['Scout']['name'],
                {'facts_used': len(scout['facts_used']), 'risks': len(scout['risks']), 'model_mode': model['mode']})
        # Memory blocked rules never enter the Maker draft on their own: they
        # filter the actual candidate claims and draft text in check_pack.
        # Only the explicit demo seed below may add an unsupported claim, so a
        # blocked rule for an absent claim records zero blocks and changes
        # no draft text.
        v1_claims = list(claims)
        if seed_unverified_claim:
            # Demo test seed only, never normal Maker behavior: a single
            # unsupported claim so reviewers can inspect the block and revision.
            v1_claims.append('best in Texas')
        step = 'maker_draft_v1'
        gate('maker_draft_v1')
        note('maker_draft_v1', 'started', profiles['Maker']['name'])
        maker_result = model_candidate('Maker', task)
        maker = maker_result.get('raw_json') if maker_result else None
        maker_model = maker_result.get('model_used') if maker_result else 'none'
        v1 = None
        if maker:
            # Every model string is untrusted. Founder note text is not in the
            # allowlist unless separately confirmed as allowed_claim, so raw
            # founder notes cannot pass check_sentence. No model output
            # bypasses Checker; unsafe candidates fall back deterministically.
            raw_claims = _clean_model_lines(maker.get('claims'))
            raw_post = _clean_model_lines(maker.get('post_lines'))
            raw_email = _clean_model_lines(maker.get('email_lines'))
            # Only exact, independently verified sentences can reach Maker.
            safe = [c for c in raw_claims if check_sentence(c, facts)['verified']]
            if (raw_post or raw_email) and safe:
                # Structured post/email candidate path. Both channels must be
                # present, distinct, and fully clean including policy and
                # blocked rules. Any failure rejects to fallback below.
                if raw_post and raw_email:
                    post_text = '. '.join(l.strip().rstrip('.!?') for l in raw_post) + '.'
                    email_text = '\n'.join(l.strip().rstrip('.!?') for l in raw_email)
                    proposed = {'post': post_text, 'email': email_text, 'claims': list(safe)}
                    if (post_text != email_text
                            and not check_pack(proposed, facts, blocked_claims,
                                               checker_profile, effective)['blocked_count']):
                        v1_claims = safe + (['best in Texas'] if seed_unverified_claim else [])
                        if seed_unverified_claim:
                            post_final = post_text.rstrip() + ' best in Texas.'
                            email_final = email_text.rstrip() + '\nbest in Texas'
                        else:
                            post_final, email_final = post_text, email_text
                        v1 = {'post': post_final, 'email': email_final, 'claims': list(v1_claims),
                              'draft_origin': 'model_safe', 'model_written': True,
                              'maker_schema': 'structured_post_email',
                              'model_used': _sanitized_model_name(maker_model)}
            if v1 is None and safe:
                # Legacy claims-only path (or structured rejection with safe
                # claims): distinct post/email from safe claims only.
                # Single-claim drafts differ by trailing period vs bare line;
                # multi-claim drafts differ by order and separators.
                proposed_post, proposed_email = _distinct_post_email(safe)
                proposed = {'post': proposed_post, 'email': proposed_email, 'claims': list(safe)}
                if proposed_post != proposed_email and not check_pack(
                        proposed, facts, blocked_claims, checker_profile, effective)['blocked_count']:
                    v1_claims = safe + (['best in Texas'] if seed_unverified_claim else [])
                    final_post, final_email = _distinct_post_email(v1_claims)
                    v1 = {'post': final_post, 'email': final_email, 'claims': list(v1_claims),
                          'draft_origin': 'model_safe', 'model_written': True,
                          'maker_schema': 'legacy_claims_only' if not (raw_post or raw_email) else 'structured_post_email_fallback',
                          'model_used': _sanitized_model_name(maker_model)}
        if v1 is None:
            # Deterministic fallback: keyless or rejected model. Safe,
            # labelled, never model-written. v1_claims keeps original claims
            # plus seed; model-safe partial output is never half-trusted.
            v1_claims = list(claims) + (['best in Texas'] if seed_unverified_claim else [])
            v1 = make_draft(v1_claims)
        reached('maker_draft_v1', 'Maker', 'Prepared local post and email drafts', profiles['Maker']['name'],
                {'claims': len(v1_claims), 'draft_chars': len(v1['post'])})
        step = 'checker_v1'
        gate('checker_v1')
        note('checker_v1', 'started', profiles['Checker']['name'])
        checker_result = model_candidate('Checker', json.dumps({'draft': v1, 'approved_claims': claims}))
        suggestion = checker_result.get('raw_json') if checker_result else None
        if suggestion:
            # Candidate claims are checked but cannot change the actual draft verdict.
            raw_suggest = _clean_model_lines(suggestion.get('claims'))
            check_pack(make_draft(raw_suggest), facts, blocked_claims, checker_profile, effective)
        c1 = check_pack(v1, facts, blocked_claims, checker_profile, effective)
        reached('checker_v1', 'Checker', 'Checked explicit claims and draft text; blocked_count=' + str(c1['blocked_count']),
                profiles['Checker']['name'],
                {'blocked_count': c1.get('blocked_count'), 'verified_count': c1.get('verified_count')})
        # Rebuild from verified allowlist sentences, removing every blocked sentence.
        # Blocked and policy-blocked claims are excluded here, so the final draft
        # stays clean while v1 still records the verdict difference.
        step = 'maker_draft_v2'
        gate('maker_draft_v2')
        note('maker_draft_v2', 'started', profiles['Maker']['name'])
        v2_claims = [c for c in claims
                     if normalize(c) not in blocked_names
                     and _policy_block_for_claim(c, effective) is None]
        v2 = make_draft(v2_claims)
        reached('maker_draft_v2', 'Maker', 'Revised using approved facts file claims', profiles['Maker']['name'],
                {'claims': len(v2_claims), 'draft_chars': len(v2['post'])})
        step = 'checker_v2'
        gate('checker_v2')
        note('checker_v2', 'started', profiles['Checker']['name'])
        c2 = check_pack(v2, facts, blocked_claims, checker_profile, effective)
        reached('checker_v2', 'Checker', 'Rechecked revised drafts; blocked_count=' + str(c2['blocked_count']), profiles['Checker']['name'],
                {'blocked_count': c2.get('blocked_count'), 'verified_count': c2.get('verified_count')})
        if c2['blocked_count']:
            raise ValueError('Final draft has blocked claims')
        step = 'approval'
        if approve:
            event('approval', 'demo_human', 'Simulated approval for local export', 'demo_human')
        event('receipt', 'LaunchCrew', 'Prepared receipt for storage; no submission attempted', 'LaunchCrew')
        usage = model_usage(attempts)
        step = 'receipt'
        gate('receipt')
        note('receipt', 'started', 'LaunchCrew')
        receipt = create_receipt(Path(out).stem, idea, scout, v1, c1, v2, c2, events, usage, approve)
        receipt['checker_profile'] = checker_profile
        founder_note = parsed_product['founder_note'] if parsed_product else None
        receipt['product_facts'] = product_section(
            parsed_product, product_allowlist,
            founder_variant(founder_note, v2['post'], v2['email']))
        receipt['checker_policies'] = list(effective)
        receipt['checker_enforcement'] = enforcement
        receipt['stage_agents'] = {stage.lower(): _stage_snapshot(profiles[stage]) for stage in ('Scout', 'Maker', 'Checker')}
        receipt['stage_bindings'] = {stage.lower(): profiles[stage]['name'] for stage in ('Scout', 'Maker', 'Checker')}
        receipt['agents_used_detail'] = [profiles['Scout']['name'], profiles['Maker']['name'], profiles['Checker']['name'],
                                         profiles['Maker']['name'], profiles['Checker']['name']]
        receipt['memory_claims'] = list(memory_claims or [])
        receipt['blocked_claims'] = list(blocked_claims or [])
        receipt['seed_unverified_claim'] = _seed_marker(
            seed_unverified_claim, v1_claims, v1, v2_claims, v2)
        if brief is not None:
            receipt['campaign_brief'] = brief
        if campaign_day is not None:
            receipt['campaign_day'] = campaign_day
        if visual_verifier is not None:
            receipt['visual_verification'] = visual_verifier()
        receipt_writer(receipt, out)
        note('receipt', 'completed', 'LaunchCrew', {'blocked_count': c2.get('blocked_count')})
        return receipt
    except Exception as error:
        try:
            note(step, 'failed', 'LaunchCrew', {'error_type': type(error).__name__})
        except Exception:
            pass
        failure = failed_receipt(Path(out).stem,
                                 [e for e in events if e['step'] != 'receipt'], step, error)
        failure['model_usage'] = model_usage(attempts)
        failure['visual_verification'] = {'method': 'not_run', 'checked': False}
        if isinstance(profiles, dict) and set(profiles) == {'Scout', 'Maker', 'Checker'}:
            try:
                failure['stage_agents'] = {stage.lower(): _stage_snapshot(profiles[stage]) for stage in ('Scout', 'Maker', 'Checker')}
                failure['stage_bindings'] = {stage.lower(): profiles[stage]['name'] for stage in ('Scout', 'Maker', 'Checker')}
                failure['checker_enforcement'] = enforcement or parse_checker_agent(profiles['Checker'])
                failure['checker_policies'] = list(effective)
            except Exception:
                pass
        failure['checker_profile'] = checker_profile
        failure['seed_unverified_claim'] = _seed_marker(seed_unverified_claim)
        if product_facts is None or parsed_product is not None:
            try:
                failure['product_facts'] = product_section(parsed_product, product_allowlist)
            except Exception:
                pass
        receipt_writer(failure, out)
        raise


def main():
    parser = argparse.ArgumentParser(description='LaunchCrew: demo Idea to Launch Pack, local JSON only')
    parser.add_argument('--idea', required=True)
    parser.add_argument('--facts', default='facts/demo_facts.json')
    parser.add_argument('--agents', default='agents')
    parser.add_argument('--out', default='runs/demo_001.json')
    parser.add_argument('--approve', action='store_true', help='Simulate demo human approval for export')
    parser.add_argument('--seed-unverified-claim', action='store_true', help='Demo test seed only')
    args = parser.parse_args()
    try:
        receipt = run_pipeline(args.idea, args.facts, args.agents, args.out, args.approve, args.seed_unverified_claim)
    except Exception as error:
        # Error types only: never expose request headers or environment values.
        parser.exit(1, 'LaunchCrew stopped: ' + type(error).__name__ + '\n')
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
