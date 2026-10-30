"""Deterministic human revision recheck against the SAME run snapshot.

No model calls, no network, no trust in client claims. Rechecking uses only
the verified facts, blocked rules, Checker policies, and voice banned terms
recorded on the receipt, so later profile or memory edits cannot rewrite
past proof.

Semantics: an edit that fails rechecking is rejected with HTTP 422 and is
not stored. Only text that passes every deterministic claim check is saved
as a new human revision, and any saved change resets export approval.

Approval binding: approval stores a versioned SHA-256 digest over the exact
checked artifact (confirmed facts plus provenance, current post/email/claims,
deterministic Checker result, effective Checker profile/policies/blocked
rules, voice source/version/banned terms, normalized photo state, shared
revision). Export recomputes and compares that digest every time, including
revision zero. Historical approvals without a binding are not exportable and
require a new approval. A voice edit or delete marks dependent receipts stale
until a new human revision check passes.
"""
import copy
import hashlib
import json
import re

from .receipts import timestamp


APPROVAL_BINDING_VERSION = 'approval-binding/v1'


REVISION_EXPLAINER = (
    'Rechecking compares your edited post and email against the same '
    'verified facts, blocked rules, Checker policies, and voice banned terms '
    'saved on this run. Unsupported text is rejected and not saved. Saved '
    'text clears the prior export approval until you approve the latest revision.'
)


class NeedsRevision(ValueError):
    def __init__(self, check):
        super().__init__('Edited text needs revision before it can be saved')
        self.check = check

_SENTENCE_SPLIT = re.compile(r'(?<!\d)[.!?]+|[.!?]+(?!\d)|\n+')


def _sentences(post, email):
    combined = (post or '') + '\n' + (email or '')
    return [s.strip() for s in _SENTENCE_SPLIT.split(combined) if s.strip()]


def current_revision(receipt):
    try:
        raw = receipt.get('revision', 0)
        if isinstance(raw, bool):
            return 0
        value = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return value if value >= 0 else 0


def _entry_sourced(entry):
    sources = entry.get('sources')
    if isinstance(sources, list) and any(isinstance(s, str) and s.strip() for s in sources):
        return True
    evidence = entry.get('evidence')
    if isinstance(evidence, str) and evidence.strip():
        return True
    if isinstance(evidence, list) and any(isinstance(s, str) and s.strip() for s in evidence):
        return True
    return False


def snapshot_allowlist(receipt):
    scout = receipt.get('scout') or {}
    facts_used = scout.get('facts_used') if isinstance(scout, dict) else None
    if isinstance(facts_used, list) and facts_used:
        allowlist = [entry.get('claim') for entry in facts_used
                     if isinstance(entry, dict) and entry.get('verified') is True
                     and isinstance(entry.get('claim'), str) and entry['claim'].strip()
                     and _entry_sourced(entry)]
        if allowlist:
            return allowlist
    return None


def snapshot_sources(receipt):
    scout = receipt.get('scout') or {}
    sources = scout.get('sources') if isinstance(scout, dict) else None
    if isinstance(sources, list) and sources:
        cleaned = [s for s in sources if isinstance(s, str) and s.strip()]
        if cleaned and len(cleaned) == len(sources):
            return list(cleaned)
    return None


def snapshot_blocked(receipt):
    raw = receipt.get('blocked_claims')
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, str) and c.strip()]
    return []


def snapshot_policies(receipt):
    raw = receipt.get('checker_policies')
    if isinstance(raw, list):
        return sorted({str(p) for p in raw if isinstance(p, str)})
    profile = receipt.get('checker_profile', 'standard')
    return ['superlatives'] if profile == 'strict' else []


def snapshot_profile_name(receipt, stage):
    bindings = receipt.get('stage_bindings') or {}
    if isinstance(bindings, dict) and isinstance(bindings.get(stage), str):
        return bindings.get(stage)
    detail = (receipt.get('stage_agents') or {}).get(stage) or {}
    if isinstance(detail, dict) and isinstance(detail.get('name'), str):
        return detail.get('name')
    return None


def snapshot_voice(receipt):
    if not isinstance(receipt, dict):
        return None, None
    raw = receipt.get('voice_profile')
    if raw is None:
        return None, None
    binding = snapshot_voice_binding(receipt)
    if binding is None:
        return None, None
    terms = binding.get('banned_terms') or []
    if not terms:
        return None, None
    for term in terms:
        if not isinstance(term, str) or not term.strip():
            raise ValueError('Voice banned term must be a non-empty string')
    snapshot = {'banned_terms': list(terms)}
    ref = {'id': binding.get('id'), 'title': binding.get('title'),
           'version': binding.get('version')}
    return snapshot, ref


def snapshot_voice_binding(receipt):
    raw = receipt.get('voice_profile') if isinstance(receipt, dict) else None
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError('Voice profile binding must be an object or null')
    voice_id = raw.get('id')
    if voice_id is not None and not isinstance(voice_id, str):
        raise ValueError('Voice profile id must be a string or null')
    title = raw.get('title')
    if title is not None and not isinstance(title, str):
        raise ValueError('Voice profile title must be a string or null')
    version = raw.get('version')
    if version is not None and not isinstance(version, str):
        raise ValueError('Voice profile version must be a string or null')
    digest = raw.get('digest')
    if digest is not None and not isinstance(digest, str):
        raise ValueError('Voice profile digest must be a string or null')
    terms_raw = raw.get('banned_terms', [])
    if not isinstance(terms_raw, list):
        raise ValueError('Voice banned_terms must be a list')
    for term in terms_raw:
        if not isinstance(term, str):
            raise ValueError('Voice banned_terms must be strings')
    example_count = raw.get('example_count', 0)
    if isinstance(example_count, bool) or not isinstance(example_count, int):
        raise ValueError('Voice example_count must be an integer')
    banned_count = raw.get('banned_term_count', len(terms_raw))
    if isinstance(banned_count, bool) or not isinstance(banned_count, int):
        raise ValueError('Voice banned_term_count must be an integer')
    return {'id': voice_id, 'title': title, 'version': version,
            'digest': digest, 'banned_terms': list(terms_raw),
            'example_count': example_count,
            'banned_term_count': banned_count}


def voice_stale_reason(receipt):
    if not isinstance(receipt, dict):
        return None
    if receipt.get('voice_stale') is True:
        return ('Voice profile is stale; it changed since approval, '
                'a new human revision check is required before export')
    return None


def _canonical_binding_bytes(payload):
    # Fixed canonical JSON: sorted keys, compact separators, UTF-8.
    # Any non-serializable input raises and the caller fails closed.
    return json.dumps(payload, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False).encode('utf-8')


def _binding_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(what + ' must be an integer')
    return value


def _binding_nonneg_int(value, what):
    value = _binding_int(value, what)
    if value < 0:
        raise ValueError(what + ' must be non-negative')
    return value


def _binding_str(value, what):
    if not isinstance(value, str):
        raise ValueError(what + ' must be a string')
    return value


def _binding_str_list(value, what):
    if not isinstance(value, list):
        raise ValueError(what + ' must be a list')
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(what + ' must be a list of strings')
    return list(value)


def _binding_fact_entries(receipt):
    # Normalized verified sourced Scout entries: claim plus per-fact
    # provenance. Only entries that already pass the allowlist filter
    # (verified True plus sourced) are bound. Unverified entries are not
    # evidence and stay out. Types are strict so type confusion fails
    # closed; value changes alter the digest.
    scout = receipt.get('scout')
    if not isinstance(scout, dict):
        raise ValueError('Approval binding requires a Scout snapshot')
    raw = scout.get('facts_used')
    if not isinstance(raw, list):
        raise ValueError('Approval binding requires Scout facts')
    bound = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get('verified') is not True:
            continue
        claim = entry.get('claim')
        if not isinstance(claim, str) or not claim.strip():
            continue
        if not _entry_sourced(entry):
            continue
        sources_raw = entry.get('sources', [])
        if not isinstance(sources_raw, list):
            raise ValueError('Approval binding requires Scout fact sources to be a list')
        for source in sources_raw:
            if not isinstance(source, str):
                raise ValueError('Approval binding requires Scout fact sources to be strings')
        evidence = entry.get('evidence')
        if evidence is not None and not isinstance(evidence, str) and not isinstance(evidence, list):
            raise ValueError('Approval binding requires Scout fact evidence to be a string, list, or null')
        if isinstance(evidence, list):
            for item in evidence:
                if not isinstance(item, str):
                    raise ValueError('Approval binding requires Scout fact evidence to be strings')
            evidence = list(evidence)
        bound.append({'claim': claim, 'sources': list(sources_raw), 'evidence': evidence})
    return bound


def approval_binding_payload(receipt):
    """Build the canonical artifact payload bound at approval time.

    Covers owner-confirmed facts plus provenance (or the labelled
    demo-template snapshot), current post/email/claims, the deterministic
    Checker result, effective Checker profile/policies/blocked rules,
    voice source/version/banned terms, normalized photo state, and the
    shared revision. Approval and export event fields plus timestamps are
    excluded so post-approval audit appends do not invalidate the digest.
    Photo bytes, digests, file IDs, provider IDs, DB URLs, credentials,
    operator data, and voice style samples are never included. Raises
    ValueError on malformed inputs; callers fail closed.
    """
    if not isinstance(receipt, dict):
        raise ValueError('Receipt unavailable for approval binding')
    if 'revision' not in receipt:
        revision = 0
    else:
        revision = _binding_nonneg_int(receipt.get('revision'), 'Revision')
    product = receipt.get('product_facts')
    if not isinstance(product, dict):
        raise ValueError('Approval binding requires product-facts provenance')
    mode = _binding_str(product.get('mode'), 'Product-facts mode')
    template = _binding_str(product.get('template'), 'Product-facts template')
    template_label = _binding_str(product.get('template_label'), 'Product-facts template label')
    template_used = product.get('template_used')
    if type(template_used) is not bool:
        raise ValueError('Product-facts template_used must be true or false')
    confirmed_claims = _binding_str_list(product.get('confirmed_claims'), 'Confirmed claims')
    allowlist = _binding_str_list(product.get('allowlist'), 'Product-facts allowlist')
    fields_raw = product.get('fields')
    if not isinstance(fields_raw, list):
        raise ValueError('Product-facts fields must be a list')
    fields = []
    for entry in fields_raw:
        if not isinstance(entry, dict):
            raise ValueError('Product-facts field must be an object')
        field = _binding_str(entry.get('field'), 'Product-facts field name')
        value = _binding_str(entry.get('value'), 'Product-facts field value')
        confirmed = entry.get('confirmed')
        if type(confirmed) is not bool:
            raise ValueError('Product-facts field confirmation must be true or false')
        source = _binding_str(entry.get('source'), 'Product-facts field source')
        fields.append({'field': field, 'value': value,
                       'confirmed': confirmed, 'source': source})
    scout_claims = snapshot_allowlist(receipt)
    if scout_claims is None:
        raise ValueError('Approval binding requires a verified fact snapshot')
    scout_sources = snapshot_sources(receipt)
    if scout_sources is None:
        raise ValueError('Approval binding requires verified fact sources')
    draft = current_draft(receipt)
    post = _binding_str(draft.get('post'), 'Draft post')
    email = _binding_str(draft.get('email'), 'Draft email')
    claims = _binding_str_list(draft.get('claims'), 'Draft claims')
    check = current_check(receipt)
    if not isinstance(check, dict):
        raise ValueError('Approval binding requires a Checker result')
    verified_count = _binding_nonneg_int(check.get('verified_count'), 'Checker verified_count')
    blocked_count = _binding_nonneg_int(check.get('blocked_count'), 'Checker blocked_count')
    blocked_raw = check.get('blocked_claims')
    if not isinstance(blocked_raw, list):
        raise ValueError('Checker blocked_claims must be a list')
    blocked_claims = []
    for entry in blocked_raw:
        if not isinstance(entry, dict):
            raise ValueError('Checker blocked claim must be an object')
        blocked_claims.append({'claim': _binding_str(entry.get('claim'), 'Blocked claim'),
                               'reason': _binding_str(entry.get('reason'), 'Blocked reason')})
    revision_instructions = _binding_str_list(check.get('revision_instructions'),
                                              'Checker revision_instructions')
    results_raw = check.get('claim_results')
    if not isinstance(results_raw, list):
        raise ValueError('Checker claim_results must be a list')
    claim_results = []
    for entry in results_raw:
        if not isinstance(entry, dict):
            raise ValueError('Checker claim result must be an object')
        verified = entry.get('verified')
        blocked = entry.get('blocked')
        if type(verified) is not bool or type(blocked) is not bool:
            raise ValueError('Checker claim result flags must be true or false')
        evidence = entry.get('evidence')
        if evidence is not None and not isinstance(evidence, str):
            raise ValueError('Checker claim evidence must be a string or null')
        claim_results.append({'claim': _binding_str(entry.get('claim'), 'Claim result'),
                              'verified': verified,
                              'verdict': _binding_str(entry.get('verdict'), 'Claim verdict'),
                              'evidence': evidence,
                              'reason': _binding_str(entry.get('reason'), 'Claim reason'),
                              'blocked': blocked,
                              'source': _binding_str(entry.get('source'), 'Claim source')})
    supported_count = _binding_nonneg_int(check.get('supported_count'), 'Checker supported_count')
    unsupported_count = _binding_nonneg_int(check.get('unsupported_count'), 'Checker unsupported_count')
    conflicts_count = _binding_nonneg_int(check.get('conflicts_count'), 'Checker conflicts_count')
    if 'checker_profile' in receipt and receipt.get('checker_profile') is not None:
        checker_profile = _binding_str(receipt.get('checker_profile'), 'Checker profile')
    else:
        checker_profile = 'standard'
    checker_policies = list(snapshot_policies(receipt))
    blocked_rules = list(snapshot_blocked(receipt))
    checker_stage = snapshot_profile_name(receipt, 'checker')
    if checker_stage is not None and not isinstance(checker_stage, str):
        raise ValueError('Checker stage binding must be a string or null')
    from backend.photo_review import photo_status_of
    photo = photo_status_of(receipt)
    photo_state = _binding_str(photo.get('state'), 'Photo state')
    label = photo.get('label')
    if label is not None and not isinstance(label, str):
        raise ValueError('Photo label must be a string or null')
    photo_reason = _binding_str(photo.get('reason'), 'Photo reason')
    policy_version = _binding_str(photo.get('policy_version'), 'Photo policy version')
    photo_revision = _binding_nonneg_int(photo.get('revision'), 'Photo revision')
    voice_binding = snapshot_voice_binding(receipt)
    return {'version': APPROVAL_BINDING_VERSION,
            'revision': revision,
            'facts': {'mode': mode, 'template': template,
                      'template_label': template_label,
                      'template_used': template_used,
                      'confirmed_claims': confirmed_claims,
                      'allowlist': allowlist, 'fields': fields,
                      'scout_claims': list(scout_claims),
                      'scout_sources': list(scout_sources),
                      'scout_facts': _binding_fact_entries(receipt)},
            'draft': {'post': post, 'email': email, 'claims': claims},
            'check': {'verified_count': verified_count,
                      'blocked_count': blocked_count,
                      'blocked_claims': blocked_claims,
                      'revision_instructions': revision_instructions,
                      'claim_results': claim_results,
                      'supported_count': supported_count,
                      'unsupported_count': unsupported_count,
                      'conflicts_count': conflicts_count},
            'policy': {'checker_profile': checker_profile,
                       'checker_policies': checker_policies,
                       'blocked_claims': blocked_rules,
                       'checker_stage': checker_stage},
            'voice': voice_binding,
            'photo': {'state': photo_state, 'label': label,
                      'reason': photo_reason,
                      'policy_version': policy_version,
                      'revision': photo_revision}}


def compute_approval_digest(receipt):
    """Deterministic SHA-256 hex over the canonical binding payload."""
    payload = approval_binding_payload(receipt)
    return hashlib.sha256(_canonical_binding_bytes(payload)).hexdigest()


def approval_binding(receipt):
    """Versioned binding for the current checked artifact."""
    return {'version': APPROVAL_BINDING_VERSION,
            'digest': compute_approval_digest(receipt)}


def binding_status(receipt):
    """Check stored binding against a fresh recomputation.

    Returns (True, '') only when the receipt binding plus the latest
    approval entry both match the recomputed digest for the current
    artifact. Any missing, malformed, or mismatched binding returns
    (False, reason). Never raises; malformed inputs fail closed as not
    bound. Historical approvals without a binding require a new approval.
    """
    try:
        if not isinstance(receipt, dict):
            return False, 'Receipt unavailable'
        stored = receipt.get('approval_binding')
        if stored is None:
            return False, 'Approval binding missing; historical approvals require a new approval'
        if not isinstance(stored, dict):
            return False, 'Approval binding malformed; historical approvals require a new approval'
        if stored.get('version') != APPROVAL_BINDING_VERSION:
            return False, 'Approval binding version mismatch; historical approvals require a new approval'
        digest = stored.get('digest')
        if not isinstance(digest, str) or len(digest) != 64:
            return False, 'Approval binding digest malformed'
        if any(c not in '0123456789abcdef' for c in digest):
            return False, 'Approval binding digest malformed'
        try:
            expected = compute_approval_digest(receipt)
        except ValueError as error:
            return False, 'Approval binding cannot be recomputed: ' + str(error)
        if digest != expected:
            return False, ('Approval binding mismatch; facts, copy, policy, voice, photo, '
                           'or check changed since approval')
        approvals = receipt.get('approvals')
        if not isinstance(approvals, list) or not approvals:
            return False, 'Approval entry missing'
        latest = approvals[-1]
        if not isinstance(latest, dict):
            return False, 'Approval entry malformed'
        if latest.get('binding_version') != APPROVAL_BINDING_VERSION:
            return False, 'Approval entry binding version mismatch'
        if latest.get('binding_digest') != expected:
            return False, 'Approval entry binding mismatch'
        if latest.get('revision') != current_revision(receipt):
            return False, 'Approval entry revision mismatch'
        return True, ''
    except Exception:
        return False, 'Approval binding check failed'


def valid_revision_context(receipt):
    if not isinstance(receipt, dict):
        return False, 'Receipt unavailable'
    if receipt.get('status') == 'failed':
        return False, 'Failed runs cannot be edited into approved packs'
    if receipt.get('status') != 'completed':
        return False, 'Run has no complete draft context to revise'
    maker = receipt.get('maker_draft_v2')
    checker = receipt.get('checker_v2')
    if not isinstance(maker, dict) or not isinstance(maker.get('post'), str) or not isinstance(maker.get('email'), str):
        return False, 'Run has no complete draft context to revise'
    if not isinstance(checker, dict) or isinstance(checker.get('blocked_count'), bool) or not isinstance(checker.get('blocked_count'), int):
        return False, 'Run has no complete draft context to revise'
    if snapshot_allowlist(receipt) is None:
        return False, 'Run has no verified fact snapshot to recheck against'
    if snapshot_sources(receipt) is None:
        return False, 'Run has no verified fact snapshot to recheck against'
    return True, ''


def _explicit_claims(sentences, facts):
    # Explicit claims stay exact confirmed facts. Only sentences that
    # exactly match the allowlist pass as explicit; wrapper sentences are
    # checked separately through draft text grammar plus veto below.
    from .facts import check_claim
    return [s for s in sentences if check_claim(s, facts)['verified']]


def recheck_text(post, email, receipt):
    """Deterministically recheck post/email against the run snapshot."""
    from .run import check_pack
    from .checker_policies import policy_blocks, policy_reason
    from .facts import normalize
    from .voice_profile import voice_single_block_for_text
    ok, reason = valid_revision_context(receipt)
    if not ok:
        raise ValueError(reason)
    if not isinstance(post, str) or not post.strip() or len(post) > 2000:
        raise ValueError('Post must be 1 to 2000 characters')
    if not isinstance(email, str) or not email.strip() or len(email) > 2000:
        raise ValueError('Email must be 1 to 2000 characters')
    facts = {'approved_claims': snapshot_allowlist(receipt),
             'sources': snapshot_sources(receipt)}
    sentences = _sentences(post, email)
    if not sentences:
        raise ValueError('Edited text has no sentences to check')
    explicit = _explicit_claims(sentences, facts)
    draft = {'claims': list(explicit), 'post': post, 'email': email}
    blocked = snapshot_blocked(receipt)
    policies = snapshot_policies(receipt)
    voice_snapshot, voice_ref = snapshot_voice(receipt)
    check = check_pack(draft, facts, blocked,
                       checker_profile=receipt.get('checker_profile', 'standard'),
                       checker_policies=policies,
                       voice_snapshot=voice_snapshot, voice_ref=voice_ref)
    # Every sentence still faces veto. Grammar-verified wrapper sentences
    # are recorded in claim_results but do not reach blocked_count through
    # the draft-text path, so enforce blocked rules, policies, and voice
    # banned terms here explicitly. Factuality is not weakened: unsupported
    # sentences are already blocked through draft text, and this only adds
    # blocks.
    blocked_names = {normalize(c) for c in blocked
                     if isinstance(c, str) and normalize(c)}
    seen_blocked = {b['claim'] for b in check.get('blocked_claims', [])
                    if isinstance(b, dict) and isinstance(b.get('claim'), str)}
    originally_blocked = set(seen_blocked)
    extra = []

    def _has_voice_reason(claim_text):
        for prior in list(check.get('blocked_claims', [])) + extra:
            if not isinstance(prior, dict):
                continue
            if prior.get('claim') != claim_text:
                continue
            reason = prior.get('reason')
            if isinstance(reason, str) and 'Blocked by voice profile' in reason:
                return True
        return False

    def _voice_hit_for(sentence_text):
        if voice_snapshot is None:
            return None
        return voice_single_block_for_text(voice_snapshot, sentence_text, voice_ref)

    for sentence in sentences:
        if sentence in seen_blocked:
            # Voice veto stays explicit even when factual, memory, or policy
            # logic already blocks this sentence. Add a second block entry
            # with the voice reason instead of skipping.
            voice_hit = _voice_hit_for(sentence)
            if voice_hit is not None and not _has_voice_reason(sentence):
                extra.append(voice_hit)
            continue
        if normalize(sentence) in blocked_names:
            extra.append({'claim': sentence,
                          'reason': 'Blocked by selected memory rule'})
            seen_blocked.add(sentence)
            # Memory rule blocks, but a voice hit must still appear.
            voice_hit = _voice_hit_for(sentence)
            if voice_hit is not None and not _has_voice_reason(sentence):
                extra.append(voice_hit)
            continue
        voice_hit = _voice_hit_for(sentence)
        if voice_hit is not None:
            extra.append(voice_hit)
            seen_blocked.add(sentence)
            continue
        for policy in policies:
            if policy_blocks(policy, sentence):
                extra.append({'claim': sentence,
                              'reason': policy_reason(policy)})
                seen_blocked.add(sentence)
                break
    for full in (post.strip(), email.strip()):
        if not full or full in sentences:
            continue
        voice_hit = _voice_hit_for(full)
        if voice_hit is None:
            continue
        if full in seen_blocked:
            if not _has_voice_reason(full):
                extra.append(voice_hit)
            continue
        extra.append(voice_hit)
        seen_blocked.add(full)
    if not extra:
        return check
    blocked_claims = list(check.get('blocked_claims', [])) + extra
    revision_instructions = list(check.get('revision_instructions', [])) + [
        'Remove ' + entry['claim'] + '; replace with an approved facts file claim.'
        for entry in extra]
    claim_results = copy.deepcopy(check.get('claim_results', []))
    by_claim = {}
    for index, entry in enumerate(claim_results):
        if isinstance(entry, dict) and isinstance(entry.get('claim'), str):
            if entry['claim'] not in by_claim:
                by_claim[entry['claim']] = index
    reason_set_for = set()
    appended_index = {}
    for entry in extra:
        index = by_claim.get(entry['claim'])
        if index is not None:
            claim_results[index]['verified'] = False
            claim_results[index]['blocked'] = True
            existing = claim_results[index].get('reason')
            incoming = entry.get('reason')
            if entry['claim'] in originally_blocked:
                # Keep the original factual or policy reason and append the
                # additional voice veto so both stay visible.
                if (isinstance(existing, str) and isinstance(incoming, str)
                        and incoming not in existing):
                    claim_results[index]['reason'] = existing + '; ' + incoming
            else:
                if entry['claim'] not in reason_set_for:
                    claim_results[index]['reason'] = entry['reason']
                    reason_set_for.add(entry['claim'])
                elif (isinstance(existing, str) and isinstance(incoming, str)
                        and incoming not in existing):
                    claim_results[index]['reason'] = existing + '; ' + incoming
        else:
            if entry['claim'] in appended_index:
                pos = appended_index[entry['claim']]
                existing = claim_results[pos].get('reason')
                incoming = entry.get('reason')
                if (isinstance(existing, str) and isinstance(incoming, str)
                        and incoming not in existing):
                    claim_results[pos]['reason'] = existing + '; ' + incoming
            else:
                claim_results.append({'claim': entry['claim'], 'verified': False,
                                      'verdict': 'unsupported', 'evidence': None,
                                      'reason': entry['reason'], 'blocked': True,
                                      'source': 'draft_text'})
                appended_index[entry['claim']] = len(claim_results) - 1
    all_blocked = {b['claim'] for b in blocked_claims
                   if isinstance(b, dict) and isinstance(b.get('claim'), str)}
    merged = dict(check)
    merged['blocked_count'] = len(blocked_claims)
    merged['blocked_claims'] = blocked_claims
    merged['revision_instructions'] = revision_instructions
    merged['claim_results'] = claim_results
    merged['verified_count'] = sum(1 for c in explicit if c not in all_blocked)
    merged['supported_count'] = sum(1 for r in claim_results
                                    if isinstance(r, dict) and r.get('verdict') == 'supported')
    merged['unsupported_count'] = sum(1 for r in claim_results
                                      if isinstance(r, dict) and r.get('verdict') == 'unsupported')
    merged['conflicts_count'] = sum(1 for r in claim_results
                                    if isinstance(r, dict) and r.get('verdict') == 'conflicts')
    return merged


def current_draft(receipt):
    if current_revision(receipt) > 0 and isinstance(receipt.get('human_draft'), dict):
        human = receipt['human_draft']
        if isinstance(human.get('post'), str) and isinstance(human.get('email'), str):
            return {'post': human['post'], 'email': human['email'],
                    'claims': list(human.get('claims') or [])}
    maker = receipt.get('maker_draft_v2') or {}
    return {'post': maker.get('post'), 'email': maker.get('email'),
            'claims': list(maker.get('claims') or [])}


def current_check(receipt):
    if current_revision(receipt) > 0 and isinstance(receipt.get('human_check'), dict):
        return receipt['human_check']
    return receipt.get('checker_v2')


def _specificity_floor_refusal(receipt):
    try:
        from .checker_policies import specificity_hits, specificity_reason
        draft = current_draft(receipt)
        if not isinstance(draft, dict):
            return specificity_reason(matched=[])
        texts = []
        for key in ('post', 'email'):
            value = draft.get(key)
            if isinstance(value, str):
                if value.strip():
                    texts.append(value)
            elif value is not None:
                return specificity_reason(matched=[])
        claims = draft.get('claims')
        if claims is None:
            claims = []
        if not isinstance(claims, list):
            return specificity_reason(matched=[])
        for claim in claims:
            if isinstance(claim, str):
                if claim.strip():
                    texts.append(claim)
            elif claim is not None:
                return specificity_reason(matched=[])
        matched_all = []
        for text in texts:
            try:
                hits = specificity_hits(text)
            except Exception:
                return specificity_reason(matched=[])
            for hit in hits:
                if hit not in matched_all:
                    matched_all.append(hit)
        if matched_all:
            return specificity_reason(matched=matched_all)
        return None
    except Exception:
        try:
            from .checker_policies import specificity_reason
            return specificity_reason(matched=[])
        except Exception:
            return 'Blocked by specificity floor: vague quality wording.'


def exportable(receipt):
    if not isinstance(receipt, dict):
        return False
    if receipt.get('status') == 'failed':
        return False
    if receipt.get('approval_state') != 'approved_for_export':
        return False
    if voice_stale_reason(receipt) is not None:
        return False
    from backend.photo_review import photo_block_reason
    if photo_block_reason(receipt) is not None:
        return False
    check = current_check(receipt)
    if not isinstance(check, dict) or isinstance(check.get('blocked_count'), bool) or check.get('blocked_count', 1) != 0:
        return False
    if _specificity_floor_refusal(receipt) is not None:
        return False
    approved = receipt.get('approved_revision')
    if isinstance(approved, bool) or not isinstance(approved, int):
        return False
    if approved != current_revision(receipt):
        return False
    # Binding is required for every revision including zero. A clean
    # blocked_count plus a matching approved_revision is not enough when
    # facts, copy, policy, voice, photo, or check changed after approval.
    # Historical approvals without a binding stay non-exportable.
    bound, _ = binding_status(receipt)
    return bound


def _history_entry(receipt, previous, actor, now):
    return {'revision': previous,
            'draft': current_draft(receipt),
            'check': copy.deepcopy(current_check(receipt)),
            'approval_state': receipt.get('approval_state'),
            'approvals': copy.deepcopy(list(receipt.get('approvals') or [])),
            'approved_revision': receipt.get('approved_revision'),
            'approval_binding': copy.deepcopy(receipt.get('approval_binding')),
            'checker_profile': receipt.get('checker_profile'),
            'checker_policies': copy.deepcopy(receipt.get('checker_policies')),
            'blocked_claims': copy.deepcopy(receipt.get('blocked_claims')),
            'stage_bindings': copy.deepcopy(receipt.get('stage_bindings')),
            'memory_used': copy.deepcopy(receipt.get('memory_used')),
            'voice_profile': copy.deepcopy(receipt.get('voice_profile')),
            'voice_stale': bool(receipt.get('voice_stale')),
            'revised_by': actor,
            'revised_at': now,
            'superseded_by': previous + 1, 'outcome': 'superseded_by_human_edit'}


def apply_revision(receipt, post, email, actor, base_revision):
    """Save a clean human revision; raise ValueError when rejected."""
    ok, reason = valid_revision_context(receipt)
    if not ok:
        raise ValueError(reason)
    if isinstance(base_revision, bool) or not isinstance(base_revision, int):
        raise ValueError('base_revision must be an integer')
    if base_revision != current_revision(receipt):
        raise ValueError('Revision is stale; reload the latest draft before saving')
    check = recheck_text(post, email, receipt)
    if check['blocked_count']:
        raise NeedsRevision(check)
    revised = copy.deepcopy(receipt)
    previous = current_revision(revised)
    now = timestamp()
    history = list(revised.get('revision_history') or [])
    history.append(_history_entry(revised, previous, actor, now))
    sentences = _sentences(post, email)
    explicit = _explicit_claims(sentences, {'approved_claims': snapshot_allowlist(receipt),
                                            'sources': snapshot_sources(receipt)})
    revised['revision'] = previous + 1
    revised['human_draft'] = {'post': post, 'email': email, 'claims': explicit,
                              'revised_by': actor, 'revised_at': now, 'revision': previous + 1}
    revised['human_check'] = check
    revised['revision_history'] = history
    revised['approvals'] = []
    revised['approved_revision'] = None
    revised['approval_binding'] = None
    revised['approval_state'] = 'pending_approval'
    if 'voice_stale' in revised:
        revised.pop('voice_stale', None)
    events = list((revised.get('audit') or {}).get('event_log') or [])
    events.append({'step': 'human_revision', 'agent': 'human',
                   'profile': actor or 'human',
                   'action': 'Saved human revision %d; recheck blocked_count=%d' % (previous + 1, check['blocked_count']),
                   'timestamp': now, 'revision': previous + 1, 'revised_by': actor})
    revised.setdefault('audit', {})['event_log'] = events
    return revised


def approve_current(receipt, actor, expected_revision=None):
    if receipt.get('status') == 'failed':
        raise ValueError('Approval requires a completed run')
    if receipt.get('status') != 'completed':
        raise ValueError('Approval requires a completed run')
    stale = voice_stale_reason(receipt)
    if stale is not None:
        raise ValueError(stale)
    if receipt.get('approval_state') != 'pending_approval':
        raise ValueError('Run is not pending approval')
    current = current_revision(receipt)
    if current > 0 and expected_revision is None:
        raise ValueError('Approval is stale; expected_revision is required for edited revisions')
    if expected_revision is not None:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError('expected_revision must be an integer')
        if int(expected_revision) != current:
            raise ValueError('Approval is stale; the draft changed')
    ok, reason = valid_revision_context(receipt)
    if not ok:
        raise ValueError('Approval requires a completed run with draft context')
    check = current_check(receipt)
    if not isinstance(check, dict) or isinstance(check.get('blocked_count'), bool) or check.get('blocked_count', 1) != 0:
        raise ValueError('Approval requires a clean final check')
    from backend.photo_review import photo_block_reason
    photo_reason = photo_block_reason(receipt)
    if photo_reason is not None:
        raise ValueError(photo_reason)
    try:
        binding = approval_binding(receipt)
    except ValueError as error:
        raise ValueError('Approval binding failed: ' + str(error))
    specificity_refusal = _specificity_floor_refusal(receipt)
    if specificity_refusal is not None:
        raise ValueError(specificity_refusal)
    revised = copy.deepcopy(receipt)
    now = timestamp()
    revised['approvals'] = list(revised.get('approvals') or [])
    revised['approvals'].append({'approved_by': actor, 'action': 'approved_for_export',
                                 'timestamp': now, 'revision': current_revision(revised),
                                 'binding_version': binding['version'],
                                 'binding_digest': binding['digest']})
    revised['approval_state'] = 'approved_for_export'
    revised['approved_revision'] = current_revision(revised)
    revised['approval_binding'] = dict(binding)
    events = list((revised.get('audit') or {}).get('event_log') or [])
    events.append({'step': 'approval', 'agent': 'human', 'profile': actor or 'human',
                   'action': 'Approved revision %d for export' % current_revision(revised),
                   'timestamp': now, 'revision': current_revision(revised), 'approved_by': actor})
    revised.setdefault('audit', {})['event_log'] = events
    return revised


def record_export(receipt, actor):
    """Persist actual export revision/actor/time onto a receipt copy."""
    if not exportable(receipt):
        stale = voice_stale_reason(receipt)
        if stale is not None:
            raise ValueError('Export refused: ' + stale)
        bound, reason = binding_status(receipt)
        if not bound and 'binding' in reason.lower():
            raise ValueError('Export refused: ' + reason)
        specificity_refusal = _specificity_floor_refusal(receipt)
        if specificity_refusal is not None:
            raise ValueError('Export refused: ' + specificity_refusal)
        raise ValueError('Export requires approval of the latest revision and a clean final check')
    revised = copy.deepcopy(receipt)
    now = timestamp()
    rev = current_revision(revised)
    draft = current_draft(revised)
    revised['exported_draft'] = draft
    revised['exported_revision'] = rev
    history = list(revised.get('export_history') or [])
    history.append({'revision': rev, 'exported_by': actor, 'timestamp': now})
    revised['export_history'] = history
    revised['last_exported_by'] = actor
    revised['last_exported_at'] = now
    events = list((revised.get('audit') or {}).get('event_log') or [])
    events.append({'step': 'export', 'agent': 'human', 'profile': actor or 'human',
                   'action': 'Exported revision %d for offline use' % rev,
                   'timestamp': now, 'revision': rev, 'exported_by': actor})
    revised.setdefault('audit', {})['event_log'] = events
    return revised


def export_view(receipt):
    if not exportable(receipt):
        stale = voice_stale_reason(receipt)
        if stale is not None:
            raise ValueError('Export refused: ' + stale)
        bound, reason = binding_status(receipt)
        if not bound and 'binding' in reason.lower():
            raise ValueError('Export refused: ' + reason)
        specificity_refusal = _specificity_floor_refusal(receipt)
        if specificity_refusal is not None:
            raise ValueError('Export refused: ' + specificity_refusal)
        raise ValueError('Export requires approval of the latest revision and a clean final check')
    draft = current_draft(receipt)
    view = copy.deepcopy(receipt)
    view['exported_draft'] = draft
    view['exported_revision'] = current_revision(receipt)
    return view
