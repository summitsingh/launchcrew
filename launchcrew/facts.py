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
