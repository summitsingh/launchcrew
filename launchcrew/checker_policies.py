"""Supported Checker policy subset with exact matching only.

Only exact case-insensitive matches are enforced. Free-text rules that do
not exactly match a supported token are recorded as advisory only and are
never enforced. Deterministic claim safety is always enforced and cannot
be relaxed by any profile.
"""
import re

STRICT_HYPE = ('amazing', 'incredible', 'revolutionary', 'unbeatable', 'perfect',
               'best', 'greatest', 'fastest', 'cheapest', 'only', 'guaranteed')

PRICE_RE = re.compile(r'[$\u00a3\u20ac]\s*\d')

# Slice 1 specificity floor: bounded vague quality wording that is always
# blocked and requires revision with concrete approved facts. Whole-word
# matching only, case-insensitive. Tokens split on any non-alphanumeric
# so punctuation without spaces still separates words (premium,leather
# matches premium; high,quality matches high quality). Hyphen, underscore,
# and slash are separators. Substrings never match. Single words plus
# adjacent bigrams only, with bigrams matched only within the same
# sentence segment. Period, exclamation, question, and newline break
# bigram adjacency to avoid cross-sentence false positives.
VAGUE_QUALITY_WORDS = frozenset({
    'premium',
    'luxury',
    'luxurious',
    'superior',
    'exquisite',
    'exceptional',
    'outstanding',
    'excellent',
    'flawless',
    'deluxe',
})

VAGUE_QUALITY_PHRASES = (
    ('high', 'quality'),
    ('top', 'quality'),
    ('world', 'class'),
    ('first', 'class'),
)

_VAGUE_QUALITY_PHRASE_SET = frozenset(VAGUE_QUALITY_PHRASES)

SPECIFICITY_FLOOR_VETO_TOKENS = {'specificity', 'vague_quality'}

SPECIFICITY_FLOOR_RULE_LINES = {
    'block vague quality wording',
    'require concrete facts for quality claims',
}

SUPPORTED_CHECKER_POLICIES = {
    'superlatives': {
        'policy': 'superlatives',
        'veto_token': 'superlatives',
        'rule_line': 'Block superlatives',
        'description': 'Block claims containing hype or superlative words from the strict word list.',
    },
    'price_claims': {
        'policy': 'price_claims',
        'veto_token': 'price_claims',
        'rule_line': 'Block price claims',
        'description': 'Block claims containing price values such as $49.',
    },
}

SUPPORTED_VETO_EXACT = {
    'superlatives': 'superlatives',
    'price_claims': 'price_claims',
}

SUPPORTED_RULE_EXACT = {
    'block superlatives': 'superlatives',
    'block price claims': 'price_claims',
}

FLOOR_VETO_TOKENS = {'unverified_claims'} | SPECIFICITY_FLOOR_VETO_TOKENS
FLOOR_RULE_LINES = {
    'block any claim not found in facts file',
    'require revision for every blocked claim',
} | SPECIFICITY_FLOOR_RULE_LINES

FLOOR_NOTE = ('Deterministic claim safety is always enforced and cannot be relaxed: '
              'unverified claims are blocked and every blocked claim requires revision. '
              'Vague quality wording is also always blocked by the specificity floor '
              'and requires revision with concrete approved facts. '
              'Supported policies only add blocks.')

MATCHING_NOTE = ('Exact match only. veto_scope must be exactly superlatives or price_claims. '
                 'decision_rules must be exactly Block superlatives or Block price claims '
                 '(case-insensitive). All other free-text rules are advisory only and never enforced.')


def describe_supported():
    return [dict(SUPPORTED_CHECKER_POLICIES[key]) for key in sorted(SUPPORTED_CHECKER_POLICIES)]


def _normalize_rule(line):
    return ' '.join(line.strip().lower().split())


def parse_checker_agent(agent):
    enforced = set()
    evidence = []
    advisory = []
    items_veto = []
    items_rules = []
    if isinstance(agent, dict):
        items_veto = agent.get('veto_scope', []) or []
        items_rules = agent.get('decision_rules', []) or []
    for entry in items_veto:
        if not isinstance(entry, str):
            continue
        key = entry.strip().lower()
        if key in SUPPORTED_VETO_EXACT:
            policy = SUPPORTED_VETO_EXACT[key]
            enforced.add(policy)
            evidence.append({'source': 'veto_scope', 'entry': entry, 'policy': policy})
        elif key in FLOOR_VETO_TOKENS:
            if key in SPECIFICITY_FLOOR_VETO_TOKENS:
                floor_policy = 'floor_specificity'
            else:
                floor_policy = 'floor_unverified_claims'
            evidence.append({'source': 'veto_scope', 'entry': entry, 'policy': floor_policy})
        else:
            advisory.append({'source': 'veto_scope', 'entry': entry,
                             'note': 'Advisory only. Not enforced. See supported policies.'})
    for entry in items_rules:
        if not isinstance(entry, str):
            continue
        key = _normalize_rule(entry)
        if key in SUPPORTED_RULE_EXACT:
            policy = SUPPORTED_RULE_EXACT[key]
            enforced.add(policy)
            evidence.append({'source': 'decision_rules', 'entry': entry, 'policy': policy})
        elif key in FLOOR_RULE_LINES:
            if key in SPECIFICITY_FLOOR_RULE_LINES:
                floor_policy = 'floor_specificity'
            else:
                floor_policy = 'floor_claim_safety'
            evidence.append({'source': 'decision_rules', 'entry': entry, 'policy': floor_policy})
        else:
            advisory.append({'source': 'decision_rules', 'entry': entry,
                             'note': 'Advisory only. Not enforced. See supported policies.'})
    return {'enforced_policies': sorted(enforced), 'supported_evidence': evidence,
            'advisory_only': advisory, 'floor_enforced': True, 'floor_note': FLOOR_NOTE}


def effective_policies(checker_profile='standard', checker_agent=None):
    policies = set()
    if checker_profile == 'strict':
        policies.add('superlatives')
    if isinstance(checker_agent, dict):
        policies.update(parse_checker_agent(checker_agent)['enforced_policies'])
    return sorted(policies)


def policy_blocks(policy, claim):
    if not isinstance(claim, str):
        return False
    if policy == 'superlatives':
        words = claim.lower().replace('-', ' ').split()
        cleaned = []
        for word in words:
            cleaned.append(''.join(c for c in word if c.isalnum()))
        return any(word in STRICT_HYPE for word in cleaned if word)
    if policy == 'price_claims':
        return bool(PRICE_RE.search(claim))
    return False


def policy_reason(policy):
    if policy == 'superlatives':
        return "Blocked by Checker policy 'superlatives': superlative or hype"
    if policy == 'price_claims':
        return "Blocked by Checker policy 'price_claims': price value"
    return 'Blocked by Checker policy'


_SPECIFICITY_SENTENCE_BREAK = re.compile(r'(?<!\d)[.!?]+|[.!?]+(?!\d)|\n+')
_SPECIFICITY_TOKEN = re.compile(r'[a-z0-9]+')


def _specificity_tokens(text):
    if not isinstance(text, str):
        return []
    return _SPECIFICITY_TOKEN.findall(text.lower())


def _specificity_segments(text):
    if not isinstance(text, str):
        return []
    segments = []
    for part in _SPECIFICITY_SENTENCE_BREAK.split(text.lower()):
        tokens = _SPECIFICITY_TOKEN.findall(part)
        if tokens:
            segments.append(tokens)
    return segments


def specificity_hits(text):
    segments = _specificity_segments(text)
    if not segments:
        return []
    hits = set()
    for tokens in segments:
        for token in tokens:
            if token in VAGUE_QUALITY_WORDS:
                hits.add(token)
        for index in range(len(tokens) - 1):
            pair = (tokens[index], tokens[index + 1])
            if pair in _VAGUE_QUALITY_PHRASE_SET:
                hits.add(pair[0] + ' ' + pair[1])
    return sorted(hits)


def specificity_blocks(text):
    return bool(specificity_hits(text))


def specificity_reason(text=None, matched=None):
    if matched is None:
        if isinstance(text, str):
            matched = specificity_hits(text)
        else:
            matched = []
    terms = sorted({str(m) for m in (matched or []) if isinstance(m, str) and m})
    if terms:
        quoted = ', '.join("'" + term + "'" for term in terms)
        return ("Blocked by specificity floor: vague quality wording (" + quoted + "). "
                "Remove vague quality wording; replace with an approved facts file claim "
                "that states concrete material, contents, size, or price.")
    return ("Blocked by specificity floor: vague quality wording. "
            "Remove vague quality wording; replace with an approved facts file claim "
            "that states concrete material, contents, size, or price.")
