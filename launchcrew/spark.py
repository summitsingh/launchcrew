"""Optional Meta Model API transport. Caller checks facts before and after use."""
import json
import os
from urllib.request import Request, urlopen


def _call(system_prompt, user_prompt, schema_hint, model):
    key = os.environ.get('META_API_KEY', '').strip()
    if not key:
        return {'mode': 'deterministic_fallback', 'model_used': 'none', 'attempted': False,
                'note': 'Spark was not called because no key was present.'}
    try:
        payload = {'model': model, 'messages': [
            {'role': 'system', 'content': system_prompt + '\nReturn only a JSON object. Schema: ' + json.dumps(schema_hint)},
            {'role': 'user', 'content': user_prompt}], 'response_format': {'type': 'json_object'}}
        request = Request(os.environ.get('META_API_BASE_URL', 'https://api.meta.ai/v1').rstrip('/') + '/chat/completions',
                          data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
        with urlopen(request, timeout=30) as response:
            body = json.load(response)
        raw = json.loads(body['choices'][0]['message']['content'])
        if not isinstance(raw, dict):
            raise ValueError('Expected JSON object')
        return {'mode': 'spark', 'model_used': model, 'attempted': True, 'raw_json': raw}
    except Exception as error:
        # Never include exception text, response bodies, or authorization headers.
        return {'mode': 'deterministic_fallback', 'model_used': 'none', 'attempted': True,
                'error_type': type(error).__name__}


def call_spark_strict_json(system_prompt, user_prompt, schema_hint):
    return _call(system_prompt, user_prompt, schema_hint, os.environ.get('META_MODEL', 'muse-spark-1.3'))


def spark_for_agent(agent, task_text):
    prompt = '\n'.join([agent['name'], agent['role'], agent['personality'],
                        *agent['decision_rules'], agent['expertise']])
    return call_spark_strict_json(prompt, task_text, {'facts_used': ['approved claim'], 'risks': ['demo risk, no statistics']})
