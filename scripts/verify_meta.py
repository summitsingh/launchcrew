"""Configuration report by default, one Spark call only with explicit --live."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launchcrew.facts import check_sentence, load_facts
from launchcrew.spark import call_spark_strict_json

KEY_ROUTE = ('Summit provides a Meta Model API key through the environment at runtime only, '
             'never in a file, repo, chat, or log, for a single live test run, or Summit '
             'approves a separate key creation in the Meta developer console for LaunchCrew testing.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args(argv)
    has_key = bool(os.environ.get('META_API_KEY', '').strip())
    # Only configured identifiers are attempted; the default is a documented placeholder.
    model = os.environ.get('META_MODEL', 'muse-spark-1.3')
    # Do not print arbitrary environment values, including model or endpoint overrides.
    print('Key present' if has_key else 'Key missing')
    print('Model identifier placeholder muse-spark-1.3 not verified; configured override present: ' + str('META_MODEL' in os.environ))
    print('Endpoint default https://api.meta.ai/v1 not verified; configured override present: ' + str('META_API_BASE_URL' in os.environ))
    print('json_object is a live-test risk: secondary docs describe json_schema structured output.')
    print(KEY_ROUTE)
    if not args.live or not has_key:
        print('No network call made. Explicit --live and a runtime key are required.')
        return 0
    try:
        facts, _ = load_facts(Path(__file__).resolve().parents[1] / 'facts/demo_facts.json')
        result = call_spark_strict_json('Return strict JSON. Copy approved claims exactly, no additions.',
                                        json.dumps(facts['approved_claims']), {'facts_used': ['approved claim']})
        if result['mode'] != 'spark':
            print(result.get('error_type', 'RuntimeError'))
            return 1
        claims = result['raw_json'].get('facts_used')
        if not isinstance(claims, list) or not claims or not all(isinstance(c, str) for c in claims):
            raise ValueError()
        if any(not check_sentence(c, facts)['verified'] for c in claims):
            raise ValueError()
        # Report identifiers as labels, never echo arbitrary runtime strings.
        print('Model: ' + ('muse-spark-1.3' if model == 'muse-spark-1.3' else 'configured override'))
        print('Mode: spark')
        for name, value in result.get('usage', {}).items():
            if name in ('prompt_tokens', 'completion_tokens', 'total_tokens') and type(value) is int:
                print(name + ': ' + str(value))
        return 0
    except Exception as error:
        print(type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
