"""Optional server-side Meta transport with schema validation and safe telemetry."""
import json
import os
from urllib.request import Request, urlopen

TOKEN_FIELDS = ('prompt_tokens', 'completion_tokens', 'total_tokens')


def _call(system_prompt, user_prompt, schema_hint, model):
    key = os.environ.get('META_API_KEY', '').strip()
    if not key:
        return {'mode': 'deterministic_fallback', 'model_used': 'none', 'attempted': False}
    usage = {}
    try:
        # All current candidates are objects whose required values are string arrays.
        schema = {'type': 'object', 'properties': {
            name: {'type': 'array', 'items': {'type': 'string'}} for name in schema_hint},
            'required': list(schema_hint), 'additionalProperties': False}
        payload = {'model': model, 'messages': [
            {'role': 'system', 'content': system_prompt + '\nReturn only JSON matching the supplied schema.'},
            {'role': 'user', 'content': user_prompt}],
            'response_format': {'type': 'json_schema', 'json_schema': {
                'name': 'launchcrew_candidate', 'strict': True, 'schema': schema}}}
        request = Request(os.environ.get('META_API_BASE_URL', 'https://api.meta.ai/v1').rstrip('/') + '/chat/completions',
                          data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
        with urlopen(request, timeout=30) as response:
            body = json.load(response)
        usage = body.get('usage', {})
        usage = {name: usage[name] for name in TOKEN_FIELDS
                 if isinstance(usage, dict) and type(usage.get(name)) is int and usage[name] >= 0}
        raw = json.loads(body['choices'][0]['message']['content'])
        if (not isinstance(raw, dict) or set(raw) != set(schema_hint)
                or any(not isinstance(value, list) or any(not isinstance(item, str) for item in value)
                       for value in raw.values())):
            raise ValueError('Invalid candidate schema')
        return {'mode': 'spark', 'model_used': model, 'attempted': True, 'raw_json': raw, 'usage': usage}
    except Exception as error:
        # Never include exception text, response bodies, or authorization headers.
        return {'mode': 'deterministic_fallback', 'model_used': 'none', 'attempted': True,
                'error_type': type(error).__name__, 'usage': usage}


def call_spark_strict_json(system_prompt, user_prompt, schema_hint):
    return _call(system_prompt, user_prompt, schema_hint, os.environ.get('META_MODEL', 'muse-spark-1.3'))


def spark_for_agent(agent, task_text):
    prompt = '\n'.join([agent['name'], agent['role'], agent['personality'],
                        *agent['decision_rules'], agent['expertise']])
    schema = ({'facts_used': ['approved claim'], 'risks': ['demo risk, no statistics']}
              if agent['name'] == 'Scout' else {'claims': ['copy approved claims exactly']})
    return call_spark_strict_json(prompt, task_text, schema)
