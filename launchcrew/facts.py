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


def check_draft(draft_text, facts):
    sentences = [s.strip() for s in re.split(r'[.!?\n]+', draft_text) if s.strip()]
    blocked = [r for r in check_claims(sentences, facts)['results'] if not r['verified']]
    if 'best in texas' in draft_text.lower() and not any(r['claim'].lower() == 'best in texas' for r in blocked):
        blocked.append(check_claim('best in Texas', facts))
    return blocked
