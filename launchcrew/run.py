"""LaunchCrew demo pipeline. Local drafts and receipts only."""
import argparse
import json
import os
from pathlib import Path

from . import agents
from .facts import check_sentence, check_claims, check_draft, load_facts
from .receipts import create_receipt, save_receipt, timestamp, failed_receipt
from .spark import spark_for_agent
from .wonder import wonder_synthesize_for_scout


def check_pack(draft, facts):
    results = check_claims(draft['claims'], facts)
    blocked = [r for r in results['results'] if not r['verified']]
    for result in check_draft(draft['post'] + '\n' + draft['email'], facts):
        if result['claim'] not in [r['claim'] for r in blocked]:
            blocked.append(result)
    return {'verified_count': results['verified_count'], 'blocked_count': len(blocked),
            'blocked_claims': [{'claim': r['claim'], 'reason': r['reason']} for r in blocked],
            'revision_instructions': ['Remove ' + r['claim'] + '; replace with an approved facts file claim.' for r in blocked]}


def make_draft(claims):
    # Separate sentences keep the draft and explicit claims auditable together.
    text = '. '.join(claims) + '.'
    return {'post': text, 'email': text, 'claims': list(claims)}


def model_usage(attempts):
    """Only allowlisted metadata can reach persistent receipts."""
    successful = [r for _, r in attempts if r['mode'] == 'spark']
    attempted = [r for _, r in attempts if r.get('attempted', False)]
    errors = [r['error_type'] for _, r in attempts if r.get('error_type')]
    return {'spark_calls': sum(int(r.get('attempted', False)) for kind, r in attempts if kind == 'spark'),
             'spark_mode': 'spark' if successful else 'deterministic_fallback',
             'mode': 'spark' if successful else (errors[0] if errors else 'deterministic_fallback'),
             'model_used': successful[0]['model_used'] if successful else 'none',
             'models_used': sorted({r['model_used'] for r in successful}),
             'error_types': errors, 'wonder_used': any(kind == 'wonder' and r['mode'] == 'spark' for kind, r in attempts),
             'wonder_attempts': sum(int(r.get('attempted', False)) for kind, r in attempts if kind == 'wonder'),
             'token_counts': {name: sum(r.get('usage', {}).get(name, 0) for _, r in attempts)
                              for name in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
             'tokens_known': bool(attempted) and all('total_tokens' in r.get('usage', {}) for r in attempted),
             'data_mode': 'standard_no_train',
             'data_mode_note': 'Stated intent for user data, not a verified API setting.'}


def run_pipeline(idea, facts_path, agents_path, out, approve=False, seed_unverified_claim=False, receipt_writer=save_receipt, model_enabled=True, visual_verifier=None):
    model_enabled = model_enabled and bool(os.environ.get('META_API_KEY', '').strip())
    events = []
    attempts = []
    step = 'load_agents'
    try:
        profiles = {name: agents.load_agent(name, agents_path) for name in ('Scout', 'Maker', 'Checker')}
        step = 'load_facts'
        facts, _ = load_facts(facts_path)
        claims = list(facts['approved_claims'])
        # Deterministic checks run before any model call.
        step = 'deterministic_checks'
        initial = check_claims(claims, facts)
        if initial['blocked_count']:
            raise ValueError('Approved facts failed deterministic checks')

        def event(step, agent, action):
            events.append({'step': step, 'agent': agent, 'action': action, 'timestamp': timestamp()})

        event('deterministic_checks', 'Scout', 'Checked facts file before optional synthesis')
        task = json.dumps({'idea': idea, 'approved_claims': claims, 'sources': facts['sources']})
        step = 'scout'
        wonder = wonder_synthesize_for_scout(task, None) if model_enabled else None
        if wonder is not None:
            attempts.append(('wonder', wonder))
        wonder_used = wonder is not None and wonder['mode'] == 'spark'
        model = wonder if wonder_used else (spark_for_agent(profiles['Scout'], task) if model_enabled else {
            'mode': 'deterministic_fallback', 'model_used': 'none', 'attempted': False})
        if not wonder_used:
            attempts.append(('spark', model))

        def model_candidate(name, text):
            if not model_enabled:
                return None
            result = spark_for_agent(profiles[name], text)
            attempts.append(('spark', result))
            return result.get('raw_json') if result['mode'] == 'spark' else None

        scout = {'facts_used': [{'claim': c, 'verified': True, 'evidence': c, 'sources': facts['sources']} for c in claims],
                 'risks': ['Demo risk: unsupported product claims require revision.',
                           'Demo risk: channel suitability is unverified by this facts file.'],
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
        event('scout', 'Scout', 'Produced sourced facts and demo risks; filtered optional model facts')
        v1_claims = list(claims)
        if seed_unverified_claim:
            # Demo test seed only, not normal Maker behavior.
            v1_claims.append('best in Texas')
        step = 'maker_draft_v1'
        maker = model_candidate('Maker', task)
        if maker:
            # Only exact, independently verified sentences can reach Maker.
            safe = [c for c in maker['claims'] if check_sentence(c, facts)['verified']]
            proposed = make_draft(safe) if safe else None
            if proposed and not check_pack(proposed, facts)['blocked_count']:
                v1_claims = safe + (['best in Texas'] if seed_unverified_claim else [])
        v1 = make_draft(v1_claims)
        event('maker_draft_v1', 'Maker', 'Prepared local post and email drafts')
        step = 'checker_v1'
        suggestion = model_candidate('Checker', json.dumps({'draft': v1, 'approved_claims': claims}))
        if suggestion:
            # Candidate claims are checked but cannot change the actual draft verdict.
            check_pack(make_draft(suggestion['claims']), facts)
        c1 = check_pack(v1, facts)
        event('checker_v1', 'Checker', 'Checked explicit claims and draft text; blocked_count=' + str(c1['blocked_count']))
        # Rebuild from verified allowlist sentences, removing every blocked sentence.
        step = 'maker_draft_v2'
        v2 = make_draft(claims)
        event('maker_draft_v2', 'Maker', 'Revised using approved facts file claims')
        step = 'checker_v2'
        c2 = check_pack(v2, facts)
        event('checker_v2', 'Checker', 'Rechecked revised drafts; blocked_count=' + str(c2['blocked_count']))
        if c2['blocked_count']:
            raise ValueError('Final draft has blocked claims')
        step = 'approval'
        if approve:
            event('approval', 'demo_human', 'Simulated approval for local export')
        event('receipt', 'LaunchCrew', 'Prepared receipt for storage; no submission attempted')
        usage = model_usage(attempts)
        step = 'receipt'
        receipt = create_receipt(Path(out).stem, idea, scout, v1, c1, v2, c2, events, usage, approve)
        if visual_verifier is not None:
            receipt['visual_verification'] = visual_verifier()
        receipt_writer(receipt, out)
        return receipt
    except Exception as error:
        failure = failed_receipt(Path(out).stem,
                                 [e for e in events if e['step'] != 'receipt'], step, error)
        failure['model_usage'] = model_usage(attempts)
        failure['visual_verification'] = {'method': 'not_run', 'checked': False}
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
