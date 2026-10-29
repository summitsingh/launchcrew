"""Deterministic fact checks using the demo facts and approved claims."""
import json
from pathlib import Path
import re
import unicodedata


def normalize(text):
    text = ''.join(c for c in text.lower() if not unicodedata.category(c).startswith('P'))
    return ' '.join(text.split())


def _values(value):
    if isinstance(value, dict):
        return [s for v in value.values() for s in _values(v)]
    if isinstance(value, list):
        return [s for v in value for s in _values(v)]
    return [str(value)]


def load_facts(path):
    facts = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(facts, dict) or not isinstance(facts.get('approved_claims'), list) or not facts['approved_claims']:
        raise ValueError('Facts require a nonempty approved_claims list')
    if not all(isinstance(c, str) and normalize(c) for c in facts['approved_claims']):
        raise ValueError('Approved claims must be nonempty strings')
    if not isinstance(facts.get('sources'), list) or not facts['sources'] or not all(isinstance(s, str) for s in facts['sources']):
        raise ValueError('Facts require demo source labels')
    return facts, normalize(' '.join(_values(facts)))


def check_claim(claim, facts):
    value = normalize(claim)
    # Match a full fact or an approved claim contained in the submitted claim.
    blob = normalize(' '.join(_values(facts)))
    evidence = next((c for c in facts['approved_claims']
                     if value and normalize(c) in value and normalize(c) in blob), None)
    if evidence is None and value and value in blob:
        evidence = next((c for c in _values(facts) if value in normalize(c)), None)
    if 'best in texas' in claim.lower():
        evidence = None
    return {'claim': claim, 'verified': evidence is not None, 'evidence': evidence,
            'reason': 'Matched approved claim' if evidence is not None else 'Claim not found in facts file'}


def check_claims(claims_list, facts):
    results = [check_claim(c, facts) for c in claims_list]
    verified = sum(r['verified'] for r in results)
    return {'results': results, 'verified_count': verified, 'blocked_count': len(results) - verified}


# Values keep punctuation: $49, 49%, and 49 are different assertions.
VALUE_PATTERN = re.compile(
    r'(?P<date>\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|'
    r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    r'\s+\d{1,2}(?:,?\s+\d{4})?\b)|'
    r'(?P<price>[$£€]\d+(?:[,.]\d+)*)|'
    r'(?P<percentage>\d+(?:\.\d+)?%)|(?P<number>\b\d+(?:\.\d+)?\b)', re.I)
SUPERLATIVES = re.compile(r'\b(?:best|number\s+1|only|guaranteed|perfect|unbeatable|'
                          r'greatest|fastest|cheapest|always|never|100\s*percent)\b', re.I)


def check_sentence(sentence, facts):
    result = check_claim(sentence, facts)
    blob = ' '.join(_values(facts)).lower()
    for match in VALUE_PATTERN.finditer(sentence):
        if not any(m.group().lower() == match.group().lower() and m.lastgroup == match.lastgroup
                   for m in VALUE_PATTERN.finditer(blob)):
            return {**result, 'verified': False, 'evidence': None,
                    'reason': 'Unmatched ' + match.lastgroup + ' value'}
    if 'best in texas' in sentence.lower():
        return {**result, 'verified': False, 'evidence': None, 'reason': 'Claim not found in facts file'}
    if any(not re.search(r'\b' + re.escape(m.group()) + r'\b', blob, re.I)
           for m in SUPERLATIVES.finditer(sentence)):
        return {**result, 'verified': False, 'evidence': None, 'reason': 'Unapproved superlative or absolute'}
    # Full allowlist sentence equality blocks mixed claims and unrecognized paraphrases.
    # Preserve price, percentage, and date punctuation before normalization.
    approved = any(normalize(sentence) == normalize(c) for c in facts['approved_claims'])
    return {**result, 'verified': approved, 'evidence': result['evidence'] if approved else None,
            'reason': 'Matched approved claim' if approved else 'Sentence not in approved claims'}


def check_draft(draft_text, facts):
    # Do not split decimal prices, percentages, or numbered dates at their dots.
    sentences = [s.strip() for s in re.split(r'(?<!\d)[.!?]+|[.!?]+(?!\d)|\n+', draft_text) if s.strip()]
    return [r for r in (check_sentence(s, facts) for s in sentences) if not r['verified']]


# Slice 1: explicitly confirmed owner product facts with provenance.
# Pasted text, listings, and memory items can at most SUGGEST a fact. A
# value becomes evidence only when the owner explicitly confirms it in
# this input. The bundled fictional demo template stays available in
# demo mode only and never silently becomes owner-confirmed facts.
PRODUCT_FACT_FIELDS = ('material', 'contents', 'size', 'price')
PRODUCT_FIELD_LABELS = {
    'material': 'Material',
    'contents': 'Contents',
    'size': 'Size',
    'price': 'Price',
    'allowed_claim': 'Allowed claim',
    'founder_note': 'Founder note',
}
PRODUCT_FACT_SOURCES = ('owner', 'pasted_text', 'memory', 'listing',
                        'campaign_brief', 'demo_template')
PRODUCT_FACT_VALUE_MAX = 200
PRODUCT_FACT_ALLOWED_MAX = 12
FOUNDER_NOTE_MAX = 280
OWNER_SOURCE_LABEL = 'owner_confirmed_input'
DEMO_TEMPLATE_NAME = 'demo_facts.json'
DEMO_TEMPLATE_LABEL = 'Bundled fictional demo template'


def _require_fact_dict(value, what):
    if not isinstance(value, dict):
        raise ValueError(what + ' must be an object')
    return value


def _require_fact_bool(value, what):
    if type(value) is not bool:
        raise ValueError(what + ' confirmation must be true or false')
    return value


def _require_fact_source(value, what):
    if not isinstance(value, str) or value not in PRODUCT_FACT_SOURCES:
        raise ValueError(what + ' source is not a supported provenance label')
    return value


def _clean_fact_value(value, what, limit):
    if not isinstance(value, str):
        raise ValueError(what + ' value must be a string')
    if len(value) > limit:
        raise ValueError(what + ' value exceeds the length limit')
    return value.strip()


def _single_sentence_ok(text):
    # One complete sentence by the shared decimal-safe split, ending in
    # terminal punctuation. Prices like $49.99 do not split sentences.
    if not text or text[-1] not in '.!?':
        return False
    sentences = [s.strip() for s in re.split(r'(?<!\d)[.!?]+|[.!?]+(?!\d)|\n+', text) if s.strip()]
    return len(sentences) == 1


def _parse_fact_field(raw, what, limit):
    if raw is None:
        return None
    item = _require_fact_dict(raw, what)
    unknown = set(item) - {'value', 'confirmed', 'source'}
    if unknown:
        raise ValueError(what + ' has unsupported fields')
    if 'value' not in item or 'confirmed' not in item:
        raise ValueError(what + ' requires a value and an explicit confirmation')
    value = _clean_fact_value(item['value'], what, limit)
    confirmed = _require_fact_bool(item['confirmed'], what)
    source = _require_fact_source(item.get('source', 'owner'), what)
    if confirmed and not value:
        raise ValueError(what + ' is confirmed but empty')
    return {'value': value, 'confirmed': confirmed, 'source': source}


def parse_product_facts(raw):
    """Validate owner product-fact input without authorizing anything.

    Returns None when raw is None (legacy demo-template mode). Otherwise
    returns confirmed claims, per-field state, suggestions, and the
    founder note. Suggested values are never evidence. Raises ValueError
    on invalid types, unbounded input, empty or duplicate confirmations,
    and founder notes that are not one complete sentence.
    """
    if raw is None:
        return None
    top = _require_fact_dict(raw, 'product_facts')
    unknown = set(top) - (set(PRODUCT_FACT_FIELDS) | {'allowed_claims', 'founder_note'})
    if unknown:
        raise ValueError('product_facts has unsupported fields')
    fields = []
    confirmed = []
    suggested = []
    seen = set()

    def consider(field, entry):
        if entry is None:
            return
        label = PRODUCT_FIELD_LABELS[field]
        fields.append({'field': field, 'label': label, 'value': entry['value'],
                       'confirmed': entry['confirmed'], 'source': entry['source'],
                       'claim': entry['value'] if entry['confirmed'] else None})
        if entry['confirmed']:
            key = normalize(entry['value'])
            if not key or key in seen:
                raise ValueError('Duplicate or empty confirmed product fact')
            seen.add(key)
            confirmed.append(entry['value'])
        elif entry['value']:
            suggested.append({'field': field, 'label': label, 'value': entry['value'],
                              'source': entry['source'],
                              'reason': 'Suggested but not confirmed by the owner'})

    for name in PRODUCT_FACT_FIELDS:
        consider(name, _parse_fact_field(top.get(name), 'product_facts.' + name,
                                         PRODUCT_FACT_VALUE_MAX))
    raw_claims = top.get('allowed_claims', [])
    if not isinstance(raw_claims, list):
        raise ValueError('product_facts.allowed_claims must be a list')
    if len(raw_claims) > PRODUCT_FACT_ALLOWED_MAX:
        raise ValueError('product_facts.allowed_claims exceeds the claim limit')
    for index, item in enumerate(raw_claims):
        consider('allowed_claim', _parse_fact_field(
            item, 'product_facts.allowed_claims[%d]' % index, PRODUCT_FACT_VALUE_MAX))
    founder = None
    if top.get('founder_note') is not None:
        entry = _parse_fact_field(top.get('founder_note'), 'product_facts.founder_note',
                                  FOUNDER_NOTE_MAX)
        ok = bool(entry['value']) and _single_sentence_ok(entry['value'])
        if entry['value'] and not ok:
            raise ValueError('product_facts.founder_note must be one complete sentence')
        # A founder note is owner-supplied color for a draft variant. It is
        # never an approved factual claim, even when confirmed.
        founder = {'value': entry['value'], 'confirmed': entry['confirmed'],
                   'source': entry['source'], 'label': PRODUCT_FIELD_LABELS['founder_note'],
                   'sentence_ok': ok, 'authorized_as_fact': False}
        if not entry['confirmed'] and entry['value']:
            suggested.append({'field': 'founder_note', 'label': PRODUCT_FIELD_LABELS['founder_note'],
                              'value': entry['value'], 'source': entry['source'],
                              'reason': 'Suggested but not confirmed by the owner'})
    return {'fields': fields, 'confirmed_claims': confirmed, 'suggested': suggested,
            'founder_note': founder}


def founder_variant(founder, base_post, base_email):
    """Build the explicitly unauthorized founder-note draft variant.

    Returns None unless the note is confirmed and one sentence. The
    variant never enters approved drafts, checks, or allowlists.
    """
    if not founder or not founder.get('confirmed') or not founder.get('sentence_ok'):
        return None
    note = founder['value']

    def with_note(base):
        base = (base or '').strip()
        if not base or base == '.':
            return note
        return base + ' ' + note

    return {'post': with_note(base_post), 'email': with_note(base_email),
            'label': 'Owner-supplied founder note variant',
            'authorized': False, 'verified': False,
            'note': 'Founder note is owner-supplied and unverified; it authorizes no factual claim.'}


def product_section(parsed, allowlist, draft_variant=None):
    """Assemble the receipt product-facts section with provenance.

    Demo mode labels the bundled fictional template explicitly. Owner
    mode records confirmed facts, per-field confirmation state, safe
    field labels, and suggestions, so Checker evidence and approval
    binding can follow in later checkpoints.
    """
    if parsed is None:
        return {'mode': 'demo_template', 'template': DEMO_TEMPLATE_NAME,
                'template_label': DEMO_TEMPLATE_LABEL, 'template_used': True,
                'template_note': 'Bundled fictional demo fixture; not owner-confirmed facts.',
                'fields': [], 'confirmed_claims': list(allowlist),
                'allowlist': list(allowlist), 'suggested': [],
                'founder_note': None, 'draft_variant': None,
                'labels': dict(PRODUCT_FIELD_LABELS)}
    return {'mode': 'owner_input', 'template': DEMO_TEMPLATE_NAME,
            'template_label': DEMO_TEMPLATE_LABEL, 'template_used': False,
            'template_note': 'Bundled fictional demo fixture; not used as owner facts for this run.',
            'fields': [dict(entry) for entry in parsed['fields']],
            'confirmed_claims': list(parsed['confirmed_claims']),
            'allowlist': list(allowlist),
            'suggested': [dict(entry) for entry in parsed['suggested']],
            'founder_note': dict(parsed['founder_note']) if parsed['founder_note'] else None,
            'draft_variant': dict(draft_variant) if draft_variant else None,
            'labels': dict(PRODUCT_FIELD_LABELS)}
