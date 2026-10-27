"""LaunchCrew demo pipeline. Local drafts and receipts only."""
import argparse
import json
from pathlib import Path

from . import agents
from .facts import check_claim, check_claims, check_draft, load_facts
from .receipts import create_receipt, save_receipt, timestamp
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


def run_pipeline(idea, facts_path, agents_path, out, approve=False, seed_unverified_claim=False):
    agents.AGENTS_DIR = Path(agents_path)
    profiles = {name: agents.load_agent(name) for name in ('Scout', 'Maker', 'Checker')}
    facts, _ = load_facts(facts_path)
    claims = list(facts['approved_claims'])
    # Deterministic checks run before any model call.
    initial = check_claims(claims, facts)
    if initial['blocked_count']:
        raise ValueError('Approved facts failed deterministic checks')
    events = []

    def event(step, agent, action):
        events.append({'step': step, 'agent': agent, 'action': action, 'timestamp': timestamp()})

    event('deterministic_checks', 'Scout', 'Checked facts file before optional synthesis')
    task = json.dumps({'idea': idea, 'approved_claims': claims, 'sources': facts['sources']})
    wonder = wonder_synthesize_for_scout(task, lambda: spark_for_agent(profiles['Scout'], task))
    model = wonder if wonder is not None else spark_for_agent(profiles['Scout'], task)
    scout = {'facts_used': [{'claim': c, 'verified': True, 'evidence': c, 'sources': facts['sources']} for c in claims],
             'risks': ['Demo risk: unsupported product claims require revision.',
                       'Demo risk: channel suitability is unverified by this facts file.'],
             'sources': facts['sources'], 'model_mode': model['mode'],
             'model_note': model.get('note', model.get('error_type', 'Optional Scout synthesis received.'))}
    if model['mode'] == 'spark':
        raw = model['raw_json']
        candidates = raw.get('facts_used', [])
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, str) and candidate not in claims:
                    result = check_claim(candidate, facts)
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
    v1 = make_draft(v1_claims)
    event('maker_draft_v1', 'Maker', 'Prepared local post and email drafts')
    c1 = check_pack(v1, facts)
    event('checker_v1', 'Checker', 'Checked explicit claims and draft text; blocked_count=' + str(c1['blocked_count']))
    # Rebuild from verified allowlist sentences, removing every blocked sentence.
    v2 = make_draft(claims)
    event('maker_draft_v2', 'Maker', 'Revised using approved facts file claims')
    c2 = check_pack(v2, facts)
    event('checker_v2', 'Checker', 'Rechecked revised drafts; blocked_count=' + str(c2['blocked_count']))
    if approve:
        event('approval', 'demo_human', 'Simulated approval for local export')
    event('receipt', 'LaunchCrew', 'Stored local JSON pack; no submission attempted')
    usage = {'spark_calls': int(wonder is None and model.get('attempted', False)),
             'spark_mode': model['mode'], 'wonder_used': wonder is not None,
             'data_mode': 'standard_no_train',
             'data_mode_note': 'Stated intent for user data, not a verified API setting.'}
    receipt = create_receipt(Path(out).stem, idea, scout, v1, c1, v2, c2, events, usage, approve)
    save_receipt(receipt, out)
    return receipt


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
