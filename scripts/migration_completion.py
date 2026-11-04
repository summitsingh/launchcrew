"""Read-only proof required before claiming a current-image migration complete."""
import json
import subprocess
import sys


def verify(journal, definition, described, image, release, cluster, digest):
    taskdef = definition.get('taskDefinition', {})
    tasks = described.get('tasks', [])
    if journal.get('outcome') != 'complete' or journal.get('release_generation') != release:
        return False
    if described.get('failures') or len(tasks) != 1:
        return False
    task = tasks[0]
    defined = taskdef.get('containerDefinitions', [])
    containers = task.get('containers', [])
    return (len(defined) == len(containers) == 1
            and defined[0].get('name') == containers[0].get('name') == 'migration'
            and defined[0].get('image') == containers[0].get('image') == image
            and task.get('taskArn') == journal.get('task_arn')
            and bool(task.get('taskArn'))
            and task.get('taskDefinitionArn') == journal.get('taskdef_arn') == taskdef.get('taskDefinitionArn')
            and bool(taskdef.get('taskDefinitionArn'))
            and task.get('clusterArn') == cluster
            and task.get('lastStatus') == containers[0].get('lastStatus') == 'STOPPED'
            and containers[0].get('exitCode') == 0
            and containers[0].get('imageDigest') == digest and bool(digest))


def main():
    aws, region, cluster, journal_path, taskdef, image, release, account = sys.argv[1:]
    try:
        journal = json.load(open(journal_path))
        def read(*args):
            return json.loads(subprocess.check_output([aws, *args, '--region', region, '--output', 'json'], stderr=subprocess.DEVNULL))
        definition = read('ecs', 'describe-task' + '-definition', '--task' + '-definition', taskdef)
        described = read('ecs', 'describe-tasks', '--cluster', cluster, '--tasks', journal['task_arn'])
        cluster_arn = 'arn:aws:ecs:%s:%s:cluster/%s' % (region, account, cluster)
        repository_image = image.split('/', 1)[1]
        if '@sha256:' in repository_image:
            digest = repository_image.split('@', 1)[1]
        else:
            repository, tag = repository_image.rsplit(':', 1)
            metadata = read('ecr', 'describe-images', '--repository-name', repository, '--image-ids', 'imageTag=' + tag)
            digest = metadata['imageDetails'][0]['imageDigest']
        valid = verify(journal, definition, described, image, release, cluster_arn, digest)
    except Exception:
        valid = False
    if not valid:
        raise SystemExit('refused: current migration image needs its own STOPPED exit 0 task proof; recovery attestation is insufficient')
    print('Migration current-image task proof: STOPPED exit 0')


if __name__ == '__main__':
    main()
