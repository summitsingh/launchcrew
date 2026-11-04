"""Offline rollout contract, preserving every proof binding except image."""
import copy
import json
from pathlib import Path

import pytest

from deploy.aws import sync_meta_proof_image as sync
from tests.test_meta_proof import ACCOUNT, REGION, EXEC_ROLE, TASK_ROLE, RUNTIME_ARN, META_ARN

IMAGE = ACCOUNT + '.dkr.ecr.' + REGION + '.amazonaws.com/launchcrew-api:fixture@sha256:' + 'a' * 64


def _fixture(monkeypatch, *, corrupt_after=False):
    params = {'ApiImageUri': 'old-image', 'RuntimeDbUrlSecretArn': RUNTIME_ARN, 'MetaSecretArn': META_ARN}
    stack = {'StackId': 'arn:aws:cloudformation:us-east-1:111122223333:stack/proof/fixture',
             'StackStatus': 'UPDATE_COMPLETE',
             'Tags': [{'Key': 'Project', 'Value': 'LaunchCrew'}, {'Key': 'Environment', 'Value': 'demo'}],
             'Parameters': [{'ParameterKey': key, 'ParameterValue': value} for key, value in params.items()]}
    definition = {'taskDefinitionArn': 'fixture:1', 'executionRoleArn': EXEC_ROLE,
                  'taskRoleArn': TASK_ROLE, 'cpu': '256', 'memory': '512',
                  'networkMode': 'awsvpc', 'requiresCompatibilities': ['FARGATE'],
                  'containerDefinitions': [{
                      'name': 'meta-proof', 'command': sync.EXPECTED_COMMAND, 'image': 'old-image',
                      'environment': [{'name': 'AUTH_ENABLED', 'value': 'false'}],
                      'secrets': [{'name': 'DATABASE_URL', 'valueFrom': RUNTIME_ARN + ':database-url::'},
                                  {'name': 'META_API_KEY', 'valueFrom': META_ARN + ':meta-api-key::'}],
                      'logConfiguration': {'logDriver': 'awslogs', 'options': {
                          'awslogs-group': '/launchcrew/demo/meta-proof',
                          'awslogs-stream-prefix': 'meta-proof', 'awslogs-region': REGION}}}]}
    original = copy.deepcopy(definition)
    calls = []

    def aws(command, region, **kwargs):
        calls.append(command)
        assert region == REGION
        if command[:2] == ['cloudformation', 'describe-stacks']:
            return {'Stacks': [copy.deepcopy(stack)]}
        if command[:2] == ['cloudformation', 'describe-stack-resource']:
            return {'StackResourceDetail': {'PhysicalResourceId': definition['taskDefinitionArn']}}
        if command[:2] == ['ecs', 'describe-task' '-definition']:
            return {'taskDefinition': copy.deepcopy(definition)}
        if command[:2] == ['cloudformation', 'update-stack']:
            passed = json.loads(command[command.index('--parameters') + 1])
            assert passed == [{'ParameterKey': 'ApiImageUri', 'ParameterValue': IMAGE},
                              {'ParameterKey': 'RuntimeDbUrlSecretArn', 'UsePreviousValue': True},
                              {'ParameterKey': 'MetaSecretArn', 'UsePreviousValue': True}]
            assert '--use-previous-template' in command
            assert json.loads(command[command.index('--tags') + 1]) == stack['Tags']
            policy = json.loads(command[command.index('--stack-policy-during-update-body') + 1])
            assert policy['Statement'][0]['Resource'] == 'LogicalResourceId/MetaProofTaskDefinition'
            definition['taskDefinitionArn'] = 'fixture:2'
            definition['containerDefinitions'][0]['image'] = IMAGE
            stack['Parameters'][0]['ParameterValue'] = IMAGE
            if corrupt_after:
                definition['taskRoleArn'] = EXEC_ROLE
            return {}
        assert command[:3] == ['cloudformation', 'wait', 'stack-update-complete']
        return {}

    monkeypatch.setattr(sync, '_aws', aws)
    return definition, original, calls


def test_rollout_sync_changes_only_image(monkeypatch):
    definition, original, calls = _fixture(monkeypatch)
    assert sync.sync_image(stack='proof', image=IMAGE, account=ACCOUNT, region=REGION) == 0
    expected = copy.deepcopy(original)
    expected['taskDefinitionArn'] = 'fixture:2'
    expected['containerDefinitions'][0]['image'] = IMAGE
    assert definition == expected
    assert sum(command[:2] == ['cloudformation', 'update-stack'] for command in calls) == 1
    assert not any(command[:2] == ['ecs', 'run-task'] for command in calls)
    calls.clear()
    assert sync.sync_image(stack='proof', image=IMAGE, account=ACCOUNT, region=REGION) == 0
    assert not any(command[:2] == ['cloudformation', 'update-stack'] for command in calls)


def test_rollout_sync_refuses_binding_drift(monkeypatch):
    _fixture(monkeypatch, corrupt_after=True)
    with pytest.raises(ValueError, match='readback mismatch'):
        sync.sync_image(stack='proof', image=IMAGE, account=ACCOUNT, region=REGION)


def test_rollout_sync_refuses_invalid_pin_before_aws(monkeypatch):
    _, _, calls = _fixture(monkeypatch)
    with pytest.raises(ValueError, match='API digest'):
        sync.sync_image(stack='proof', image='floating:latest', account=ACCOUNT, region=REGION)
    assert calls == []


def test_rollout_sync_dry_run_makes_no_aws_calls(monkeypatch):
    _, _, calls = _fixture(monkeypatch)
    assert sync.main(['--stack', 'proof', '--api-image', IMAGE, '--expected-account', ACCOUNT,
                      '--expected-region', REGION]) == 0
    assert calls == []


def test_bootstrap_images_wires_proof_sync_before_completion():
    script = Path('deploy/aws/bootstrap.sh').read_text()
    phase = script.split('if wants_phase images; then', 1)[1].split('\nfi', 1)[0]
    assert phase.index('verify_image "$API_IMAGE"') < phase.index('META_PROOF_API_IMAGE=')
    assert phase.index('META_PROOF_API_IMAGE=') < phase.index('verify_image "$WEB_IMAGE"')
    assert phase.index('sync_meta_proof_image.py') < phase.index('mark_done images')
    assert '--api-image "$META_PROOF_API_IMAGE"' in phase
