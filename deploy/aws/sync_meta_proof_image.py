"""Rollout hook: replace only the owned proof task's API image parameter.

Called by bootstrap's confirmed images phase after ECR and API task readback.
Reuse the deployed CloudFormation template and every other parameter. A
transient stack policy prevents updates to roles, logs, or any other resource.
No task is launched. This module's tests use AWS metadata fixtures only.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.verify_live_meta import EXPECTED_COMMAND, _run_aws


def _aws(command, region, *, timeout=60):
    result = _run_aws([*command, '--region', region, '--output', 'json'], timeout=timeout)
    if result.returncode:
        raise RuntimeError('proof image sync AWS operation failed: ' + command[1])
    return json.loads(result.stdout) if result.stdout.strip() else {}


def _stack(stack, account, region):
    doc = _aws(['cloudformation', 'describe-stacks', '--stack-name', stack], region)
    stacks = doc.get('Stacks', [])
    if len(stacks) != 1:
        raise ValueError('proof stack identity unavailable')
    current = stacks[0]
    if (not current.get('StackId', '').startswith('arn:aws:cloudformation:%s:%s:stack/' % (region, account))
            or current.get('StackStatus') not in ('CREATE_COMPLETE', 'UPDATE_COMPLETE')
            or {tag['Key']: tag['Value'] for tag in current.get('Tags', [])}.get('Project') != 'LaunchCrew'
            or {tag['Key']: tag['Value'] for tag in current.get('Tags', [])}.get('Environment') != 'demo'):
        raise ValueError('proof stack ownership or status mismatch')
    return current


def _definition(stack, region):
    resource = _aws(['cloudformation', 'describe-stack-resource', '--stack-name', stack,
                     '--logical-resource-id', 'MetaProofTaskDefinition'], region)
    arn = resource['StackResourceDetail']['PhysicalResourceId']
    return _aws(['ecs', 'describe-task' '-definition', '--task' '-definition', arn], region)['taskDefinition']


def _bindings(definition):
    comparable = copy.deepcopy(definition)
    for field in ('taskDefinitionArn', 'revision', 'status', 'registeredAt', 'registeredBy',
                  'deregisteredAt', 'requiresAttributes', 'compatibilities'):
        comparable.pop(field, None)
    for container in comparable.get('containerDefinitions', []):
        container.pop('image', None)
    return comparable


def sync_image(*, stack, image, account, region):
    if not re.fullmatch(re.escape(account + '.dkr.ecr.' + region + '.amazonaws.com/launchcrew-api')
                        + r'(?::[A-Za-z0-9_.-]+)?@sha256:[0-9a-f]{64}', image):
        raise ValueError('proof image needs the verified owned API digest')
    current = _stack(stack, account, region)
    stack_id = current['StackId']
    params = {entry['ParameterKey']: entry['ParameterValue'] for entry in current['Parameters']}
    if set(params) != {'ApiImageUri', 'RuntimeDbUrlSecretArn', 'MetaSecretArn'}:
        raise ValueError('proof stack parameters differ from the approved template')
    before = _definition(stack_id, region)
    containers = before.get('containerDefinitions', [])
    if len(containers) != 1:
        raise ValueError('proof needs one container')
    container = containers[0]
    expected_secrets = {'DATABASE_URL': params['RuntimeDbUrlSecretArn'] + ':database-url::',
                        'META_API_KEY': params['MetaSecretArn'] + ':meta-api-key::'}
    secrets = container.get('secrets', [])
    roles = [before.get('executionRoleArn', ''), before.get('taskRoleArn', '')]
    if (container.get('name') != 'meta-proof' or container.get('command') != EXPECTED_COMMAND
            or len(secrets) != 2 or {item['name']: item['valueFrom'] for item in secrets} != expected_secrets
            or roles[0] == roles[1] or any(not role.startswith('arn:aws:iam::' + account + ':role/') for role in roles)
            or container.get('logConfiguration', {}).get('logDriver') != 'awslogs'
            or container.get('logConfiguration', {}).get('options', {}).get('awslogs-group') != '/launchcrew/demo/meta-proof'):
        raise ValueError('proof task bindings differ from the approved contract')
    if params['ApiImageUri'] == image and container.get('image') == image:
        print('meta-proof image already matches verified API digest')
        return 0
    parameters = [{'ParameterKey': key, 'ParameterValue': image} if key == 'ApiImageUri'
                  else {'ParameterKey': key, 'UsePreviousValue': True} for key in params]
    policy = {'Statement': [
        {'Effect': 'Allow', 'Action': 'Update:*', 'Principal': '*',
         'Resource': 'LogicalResourceId/MetaProofTaskDefinition'}]}
    # A failed update is never automatically repeated. Existing bindings remain
    # CloudFormation-owned, and implicit deny protects every other resource.
    _aws(['cloudformation', 'update-stack', '--stack-name', stack_id,
          '--use-previous-template', '--parameters', json.dumps(parameters),
          '--tags', json.dumps(current['Tags']), '--capabilities', 'CAPABILITY_IAM',
          '--stack-policy-during-update-body', json.dumps(policy)], region)
    _aws(['cloudformation', 'wait', 'stack-update-complete', '--stack-name', stack_id],
         region, timeout=600)
    after_stack = _stack(stack_id, account, region)
    after = _definition(stack_id, region)
    after_params = {entry['ParameterKey']: entry['ParameterValue'] for entry in after_stack['Parameters']}
    if (after_params != {**params, 'ApiImageUri': image}
            or {tag['Key']: tag['Value'] for tag in after_stack.get('Tags', [])}
            != {tag['Key']: tag['Value'] for tag in current.get('Tags', [])}
            or _bindings(before) != _bindings(after)
            or after['containerDefinitions'][0]['image'] != image):
        raise ValueError('proof image update readback mismatch; rollout refused')
    print('meta-proof task revision matches verified API digest; all other bindings preserved')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stack', required=True)
    parser.add_argument('--api-image', required=True)
    parser.add_argument('--expected-account', required=True)
    parser.add_argument('--expected-region', required=True)
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm:
        print('Dry run: update proof ApiImageUri only, reuse deployed template and other parameters. No AWS calls.')
        return 0
    try:
        return sync_image(stack=args.stack, image=args.api_image,
                          account=args.expected_account, region=args.expected_region)
    except Exception as error:
        # AWS bodies can contain parameter data. Print only bounded stage text.
        print('meta-proof image sync refused: ' + type(error).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
