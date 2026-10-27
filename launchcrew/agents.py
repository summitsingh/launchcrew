"""Validated demo agent profiles, stored as individual JSON files."""
import copy
import json
import math
from pathlib import Path
import re

AGENTS_DIR = Path('agents')
REQUIRED_FIELDS = {
    'name': str, 'role': str, 'department': str, 'personality': str,
    'expertise': str, 'decision_rules': list, 'veto_scope': list,
    'tools_allowed': list, 'spend_limit': (int, float),
    'approval_level': str, 'examples': list,
}
ALLOWED_TOOLS = {'facts_file', 'spark_strict_json', 'receipt_log', 'claim_check'}


def validate(profile):
    for field, kind in REQUIRED_FIELDS.items():
        if field not in profile or not isinstance(profile[field], kind):
            raise ValueError('Missing or invalid field: ' + field)
    for field, kind in REQUIRED_FIELDS.items():
        if kind is str and not profile[field].strip():
            raise ValueError('Empty required field: ' + field)
    if not profile['decision_rules'] or not profile['tools_allowed']:
        raise ValueError('Decision rules and tools are required')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', profile['name']):
        raise ValueError('Name must be a simple agent name')
    for field in ('decision_rules', 'veto_scope', 'tools_allowed'):
        if not all(isinstance(item, str) and item.strip() for item in profile[field]):
            raise ValueError('Expected strings in ' + field)
    if not set(profile['tools_allowed']) <= ALLOWED_TOOLS:
        raise ValueError('Unsupported tool')
    if isinstance(profile['spend_limit'], bool) or not math.isfinite(profile['spend_limit']) or profile['spend_limit'] != 0:
        raise ValueError('V1 spend limit must be zero')
    if profile['approval_level'] != 'approve_each':
        raise ValueError('Invalid approval level')
    for example in profile['examples']:
        if not isinstance(example, dict) or not all(isinstance(example.get(k), str) for k in ('input', 'approved_output')):
            raise ValueError('Examples require input and approved_output strings')
    return profile


def _path(name, directory=None):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', name):
        raise ValueError('Invalid agent name')
    return Path(directory if directory is not None else AGENTS_DIR) / (name.lower() + '.json')


def save_agent(profile, directory=None):
    validate(profile)
    path = _path(profile['name'], directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return copy.deepcopy(profile)


def create_agent(profile_dict, directory=None):
    validate(profile_dict)
    if _path(profile_dict['name'], directory).exists():
        raise ValueError('Agent already exists')
    return save_agent(profile_dict, directory)


def load_agent(name, directory=None):
    return validate(json.loads(_path(name, directory).read_text(encoding='utf-8')))


def list_agents(directory=None):
    return [validate(json.loads(p.read_text(encoding='utf-8'))) for p in sorted(Path(directory if directory is not None else AGENTS_DIR).glob('*.json'))]


def edit_agent(name, updates_dict, directory=None):
    if 'name' in updates_dict and updates_dict['name'] != load_agent(name, directory)['name']:
        raise ValueError('Use clone_agent to create a new name')
    profile = load_agent(name, directory)
    profile.update(updates_dict)
    return save_agent(profile, directory)


def clone_agent(source_name, new_name, directory=None):
    profile = load_agent(source_name, directory)
    profile['name'] = new_name
    return create_agent(profile, directory)


def test_agent(name, sample_idea, directory=None):
    profile = load_agent(name, directory)
    return {'dry_run': True, 'profile': profile, 'sample_idea': sample_idea,
            'first_action': 'Read facts_file, apply decision_rules, and prepare a draft for approval.',
            'model_called': False, 'side_effects': False}
