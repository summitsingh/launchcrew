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


# Deterministic claim verdicts: supported means the text matches confirmed
# facts, conflicts means it contradicts a confirmed fact on a checked value
# or type, unsupported means no match and no proven contradiction. Verdicts
# are deterministic keyword and value checks only, not model proof. They
# never weaken the Checker veto: verified stays False unless the legacy
# allowlist rule also passes. Conservative false blocks are expected.
SUPPORTED = 'supported'
UNSUPPORTED = 'unsupported'
CONFLICTS = 'conflicts'


def _approved_claims(facts):
    raw = facts.get('approved_claims') if isinstance(facts, dict) else []
    return [c for c in (raw or []) if isinstance(c, str)]


def _approved_blob(facts):
    return normalize(' '.join(_approved_claims(facts)))


def _approved_blob_raw(facts):
    return ' '.join(_approved_claims(facts)).lower()


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
    # Safety: verdicts derive only from explicitly confirmed approved_claims,
    # never from demo template fields, memory suggestions, briefs, idea text,
    # or founder notes that may share the facts object. Owner mode strips the
    # base object in run.py, and this check ignores every non-allowlist value.
    # Explicit claims require exact confirmed sentences. Substring containment
    # never supports: a composite containing one approved fragment plus extra
    # content stays unsupported (blocked), even when the fragment matches.
    approved = _approved_claims(facts)
    value = normalize(claim) if isinstance(claim, str) else ''
    # Exact allowlist equality is supported without conflict screening: the
    # text cannot contradict the fact it equals.
    exact = next((c for c in approved if value and value == normalize(c)), None)
    if exact is not None and 'best in texas' not in (claim or '').lower():
        return {'claim': claim, 'verified': True, 'verdict': SUPPORTED,
                'evidence': exact, 'reason': 'Matched approved claim'}
    conflict = _find_conflict(claim, approved)
    if conflict is not None:
        evidence, reason = conflict
        return {'claim': claim, 'verified': False, 'verdict': CONFLICTS,
                'evidence': evidence, 'reason': reason}
    return {'claim': claim, 'verified': False, 'verdict': UNSUPPORTED,
            'evidence': None, 'reason': 'Claim not found in facts file'}


def check_claims(claims_list, facts):
    results = [check_claim(c, facts) for c in claims_list]
    verified = sum(r['verified'] for r in results)
    supported = sum(1 for r in results if r.get('verdict') == SUPPORTED)
    unsupported = sum(1 for r in results if r.get('verdict') == UNSUPPORTED)
    conflicts = sum(1 for r in results if r.get('verdict') == CONFLICTS)
    return {'results': results, 'verified_count': verified, 'blocked_count': len(results) - verified,
            'supported_count': supported, 'unsupported_count': unsupported, 'conflicts_count': conflicts}


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

# Deterministic conflict vocabularies. Small fixed word lists only; they
# catch clear swaps like wallet vs tote or leather vs canvas, but miss
# synonyms and paraphrases. That incompleteness is honest: unknown wording
# stays unsupported (blocked), never silently supported. Never treat these
# lists as proof of meaning.
PRODUCT_TYPE_WORDS = frozenset({
    'wallet', 'wallets', 'tote', 'totes', 'backpack', 'backpacks', 'bag',
    'bags', 'purse', 'purses', 'cardholder', 'cardholders', 'briefcase',
    'briefcases', 'clutch', 'satchel',
})
MATERIAL_WORDS = frozenset({
    'leather', 'vegan', 'canvas', 'nylon', 'cotton', 'polyester', 'suede',
    'pu', 'faux', 'full', 'grain',
})
_WORD_RE = re.compile(r'[a-z0-9]+')


def _word_tokens(text):
    return set(_WORD_RE.findall((text or '').lower()))


# Conservative deterministic grammar for model-authored channel copy. A
# draft-text sentence is supported only when it consists solely of exact
# confirmed fact spans plus wrapper words plus punctuation and whitespace,
# with at least one fact span. Wrapper words are narrowly nonfactual
# (salutation, intro, CTA, neutral glue). Any other alphanumeric word,
# including qualifiers, materials, product types, or extra claim fragments
# outside confirmed spans, rejects the line. Values, superlatives, and
# negations are checked separately and also reject.
WRAPPER_WORDS = frozenset({
    'hello', 'hi', 'hey', 'welcome', 'thanks', 'thank', 'you',
    'meet', 'say',
    'shop', 'now', 'learn', 'more', 'see', 'details', 'below', 'here',
    'link', 'bio', 'tap', 'click',
    'and', 'the', 'a', 'an',
})

NEGATION_WORDS = frozenset({
    'not', 'no', 'never', 'none', 'without', 'cannot',
    'neither', 'nor', 'nothing', 'nowhere', 'hardly', 'scarcely', 'barely',
    'isnt', 'arent', 'wasnt', 'werent', 'hasnt', 'havent', 'hadnt',
    'couldnt', 'shouldnt', 'wouldnt', 'mustnt', 'wont', 'dont', 'cant',
})


def _has_negation(text):
    cleaned = (text or '').lower().replace("'", '').replace('’', '')
    return bool(set(_WORD_RE.findall(cleaned)) & NEGATION_WORDS)


def _find_fact_spans(text, approved):
    if not isinstance(text, str) or not text or not approved:
        return []
    lower = text.lower()
    ordered = sorted([c for c in approved if isinstance(c, str) and c.strip()],
                     key=len, reverse=True)
    used = [False] * len(lower)
    spans = []
    for fact in ordered:
        needle = fact.lower()
        if not needle.strip():
            continue
        start = 0
        while start < len(lower):
            idx = lower.find(needle, start)
            if idx < 0:
                break
            end = idx + len(needle)
            before_ok = idx == 0 or not lower[idx - 1].isalnum()
            after_ok = end >= len(lower) or not lower[end].isalnum()
            if before_ok and after_ok and not any(used[idx:end]):
                for i in range(idx, end):
                    used[i] = True
                spans.append((idx, end, fact))
            start = idx + 1
    spans.sort(key=lambda item: item[0])
    return spans


def _grammar_wrapper_ok(text, spans):
    if not spans:
        return False, []
    chars = list(text)
    for begin, end, _ in spans:
        for i in range(begin, end):
            chars[i] = ' '
    tokens = _WORD_RE.findall(''.join(chars).lower())
    bad = [t for t in tokens if t not in WRAPPER_WORDS]
    if bad:
        return False, bad
    return True, []


def _values_by_type(text):
    found = []
    for match in VALUE_PATTERN.finditer(text or ''):
        found.append((match.lastgroup, match.group().lower()))
    return found


def _find_value_conflict(text, approved):
    # A value conflicts when the same type (price, percentage, date, number)
    # appears in confirmed facts with a different exact string. Types differ
    # by punctuation: $49 vs 49 vs 49% are different types, not conflicts.
    claim_values = _values_by_type(text)
    if not claim_values:
        return None
    approved_values = {}
    approved_example = {}
    for fact in approved:
        for group, val in _values_by_type(fact):
            approved_values.setdefault(group, set()).add(val)
            approved_example.setdefault(group, fact)
    for group, val in claim_values:
        if group in approved_values and val not in approved_values[group]:
            return (approved_example[group], 'Conflicting ' + group + ' value')
    return None


def _find_word_conflict(text, approved, vocabulary, reason):
    claim_words = _word_tokens(text) & vocabulary
    if not claim_words:
        return None
    approved_words = set()
    for fact in approved:
        approved_words |= (_word_tokens(fact) & vocabulary)
    if not approved_words:
        return None
    # Conflict only when both sides name a checked word and neither side
    # contains the other's word. Shared words (leather in both) do not
    # conflict by themselves; the differing words (vegan vs full/grain) do.
    if claim_words & approved_words:
        # If every claim word is already confirmed, no type conflict.
        if claim_words <= approved_words:
            return None
        # If confirmed words are a subset of claim words, the claim adds new
        # words but does not contradict the confirmed type; leave unsupported.
        # Only flag when confirmed has a word the claim lacks and the claim
        # has a word confirmed lacks.
        if not (approved_words - claim_words and claim_words - approved_words):
            return None
    else:
        # Disjoint checked words with both sides nonempty is a swap.
        pass
    for fact in approved:
        fact_words = _word_tokens(fact) & vocabulary
        if fact_words and fact_words.isdisjoint(claim_words):
            return (fact, reason)
    # Fallback to first fact carrying any checked word.
    for fact in approved:
        if _word_tokens(fact) & vocabulary:
            return (fact, reason)
    return None


def _find_conflict(text, approved):
    if not isinstance(text, str) or not text.strip() or not approved:
        return None
    # Exact matches never conflict; check_claim handles them first, but
    # check_sentence also calls here, so guard again.
    if any(normalize(text) == normalize(c) for c in approved):
        return None
    hit = _find_value_conflict(text, approved)
    if hit is not None:
        return hit
    hit = _find_word_conflict(text, approved, PRODUCT_TYPE_WORDS, 'Conflicting product type')
    if hit is not None:
        return hit
    return _find_word_conflict(text, approved, MATERIAL_WORDS, 'Conflicting material')


def split_sentences(draft_text):
    # Shared decimal-safe split: prices, percentages, and numbered dates do
    # not split at their dots. Newlines always split.
    return [s.strip() for s in re.split(r'(?<!\d)[.!?]+|[.!?]+(?!\d)|\n+', draft_text or '') if s.strip()]


def check_sentence(sentence, facts):
    # Safety: only confirmed approved_claims are evidence. Demo fields,
    # memory, briefs, idea text, and founder notes never authorize.
    approved = _approved_claims(facts)
    text = sentence if isinstance(sentence, str) else ''
    # Exact allowlist equality is supported. It implies value and
    # superlative checks already pass, since the blob is built from the
    # same allowlist. Grammar-supported wrapper lines are also supported
    # below; everything else stays unsupported.
    exact = next((c for c in approved if text and normalize(text) == normalize(c)), None)
    if exact is not None and 'best in texas' not in text.lower():
        return {'claim': sentence, 'verified': True, 'verdict': SUPPORTED,
                'evidence': exact, 'reason': 'Matched approved claim'}
    conflict = _find_conflict(text, approved)
    if conflict is not None:
        evidence, reason = conflict
        return {'claim': sentence, 'verified': False, 'verdict': CONFLICTS,
                'evidence': evidence, 'reason': reason}
    blob = _approved_blob_raw(facts)
    for match in VALUE_PATTERN.finditer(text):
        if not any(m.group().lower() == match.group().lower() and m.lastgroup == match.lastgroup
                   for m in VALUE_PATTERN.finditer(blob)):
            return {'claim': sentence, 'verified': False, 'verdict': UNSUPPORTED,
                    'evidence': None, 'reason': 'Unmatched ' + match.lastgroup + ' value'}
    if 'best in texas' in text.lower():
        return {'claim': sentence, 'verified': False, 'verdict': UNSUPPORTED,
                'evidence': None, 'reason': 'Claim not found in facts file'}
    if _has_negation(text):
        return {'claim': sentence, 'verified': False, 'verdict': UNSUPPORTED,
                'evidence': None, 'reason': 'Unapproved negation'}
    if any(not re.search(r'\b' + re.escape(m.group()) + r'\b', blob, re.I)
           for m in SUPERLATIVES.finditer(text)):
        return {'claim': sentence, 'verified': False, 'verdict': UNSUPPORTED,
                'evidence': None, 'reason': 'Unapproved superlative or absolute'}
    spans = _find_fact_spans(text, approved)
    if spans:
        ok, _ = _grammar_wrapper_ok(text, spans)
        if ok:
            matched = [fact for _, _, fact in spans]
            return {'claim': sentence, 'verified': True, 'verdict': SUPPORTED,
                    'evidence': matched[0], 'evidence_claims': list(matched),
                    'reason': 'Matched approved fact span with wrapper only'}
        return {'claim': sentence, 'verified': False, 'verdict': UNSUPPORTED,
                'evidence': None, 'reason': 'Unsupported wording outside confirmed facts'}
    return {'claim': sentence, 'verified': False, 'verdict': UNSUPPORTED,
            'evidence': None, 'reason': 'Sentence not in approved claims'}


def check_draft(draft_text, facts):
    return [r for r in (check_sentence(s, facts) for s in split_sentences(draft_text)) if not r['verified']]


# Slice 1: explicitly confirmed owner product facts with provenance.
# Pasted text, listings, memory items, and Drive file selections can at
# most SUGGEST a fact. A
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
                        'campaign_brief', 'demo_template', 'drive_file')
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
