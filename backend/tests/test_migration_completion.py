"""Recovery attestations cannot substitute for current-image task execution."""
from copy import deepcopy
import pytest
from scripts.migration_completion import verify


def evidence():
    journal = {'outcome': 'complete', 'release_generation': 'release', 'task_arn': 'task', 'taskdef_arn': 'definition'}
    definition = {'taskDefinition': {'taskDefinitionArn': 'definition', 'containerDefinitions': [{'name': 'migration', 'image': 'current'}]}}
    described = {'tasks': [{'taskArn': 'task', 'taskDefinitionArn': 'definition', 'clusterArn': 'cluster', 'lastStatus': 'STOPPED', 'containers': [{'name': 'migration', 'image': 'current', 'lastStatus': 'STOPPED', 'exitCode': 0, 'imageDigest': 'digest'}]}]}
    return journal, definition, described


def test_current_migration_stopped_zero_proves_completion():
    assert verify(*evidence(), 'current', 'release', 'cluster')


@pytest.mark.parametrize('change', ['missing', 'failed', 'running', 'image', 'definition', 'release', 'attestation'])
def test_incomplete_or_unbound_execution_refused(change):
    journal, definition, described = deepcopy(evidence())
    if change == 'missing':
        described = {'tasks': [], 'failures': [{'reason': 'MISSING'}]}
    elif change == 'failed':
        described['tasks'][0]['containers'][0]['exitCode'] = 1
    elif change == 'running':
        described['tasks'][0]['lastStatus'] = 'RUNNING'
    elif change == 'image':
        described['tasks'][0]['containers'][0]['image'] = 'old'
    elif change == 'definition':
        described['tasks'][0]['taskDefinitionArn'] = 'old'
    elif change == 'release':
        journal['release_generation'] = 'old'
    else:
        journal = {'kind': 'migration-recovery-attestation', 'outcome': 'complete', 'observed_head': '008'}
    assert not verify(journal, definition, described, 'current', 'release', 'cluster')
