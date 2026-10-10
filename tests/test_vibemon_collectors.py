from pathlib import Path
import re

from jinja2 import Environment, FileSystemLoader
import pytest
import yaml

from gen_values import to_yaml

ROOT = Path(__file__).resolve().parents[1]


def values(cluster, **changes):
    context = yaml.safe_load((ROOT / 'env' / f'{cluster}.yaml').read_text())
    context['vibemon'].update(changes)
    environment = Environment(loader=FileSystemLoader(ROOT / 'charts/alloy'))
    environment.filters['to_yaml'] = to_yaml
    return yaml.safe_load(environment.get_template('values-template.yaml.j2').render(context))


@pytest.mark.parametrize('cluster,limited', [('eks-demo', True), ('k3s-demo', False)])
def test_collector_has_scoped_credentials_permissions_and_delivery_readiness(cluster, limited):
    resources = values(cluster)['raw']['resources']
    deployment = next(x for x in resources if x['kind'] == 'Deployment' and x['metadata']['name'] == 'vibemon-collector')
    spec = deployment['spec']['template']['spec']
    container = spec['containers'][0]
    assert deployment['spec']['replicas'] == 1
    assert deployment['spec']['strategy']['type'] == 'Recreate'
    assert re.fullmatch(r'.+@sha256:[a-f0-9]{64}', container['image'])
    assert container['args'][container['args'].index('--source-id') + 1] == cluster
    assert container['args'][container['args'].index('--cluster-backend') + 1] == 'metrics-api'
    assert container['env'] == [{'name': 'VIBEMON_WRITE_TOKEN', 'valueFrom': {'secretKeyRef': {'name': 'vibemon-collector', 'key': 'VIBEMON_WRITE_TOKEN'}}}]
    assert container['securityContext']['readOnlyRootFilesystem']
    assert container['readinessProbe']['exec']['command'][2] == 'vibemon_collector.health'
    assert 'livenessProbe' not in container  # A Web outage must not cause restart churn.
    assert ('resources' in container) is limited
    assert not spec.get('hostNetwork', False)
    role = next(x for x in resources if x['kind'] == 'ClusterRole' and x['metadata']['name'].startswith('vibemon-collector-'))
    assert role['rules'] == [
        {'apiGroups': [''], 'resources': ['nodes', 'pods'], 'verbs': ['list']},
        {'apiGroups': ['metrics.k8s.io'], 'resources': ['nodes'], 'verbs': ['get', 'list']},
    ]
    secret = next(x for x in resources if x['kind'] == 'ExternalSecret' and x['metadata']['name'] == 'vibemon-collector')
    assert secret['spec']['data'][0]['remoteRef']['key'] == f'/k8s/{cluster}/vibemon/write-token'


def test_eks_egress_follows_the_configured_origin_without_selecting_alloy():
    resources = values('eks-demo', hostname='telemetry.example.com')['raw']['resources']
    policy = next(x for x in resources if x['metadata']['name'] == 'vibemon-collector-network')
    assert policy['spec']['podSelector']['matchLabels'] == {'app.kubernetes.io/name': 'vibemon-collector'}
    assert policy['spec']['egress'][-1]['to'] == [{'domainNames': ['telemetry.example.com']}]
    deployment = next(x for x in resources if x['kind'] == 'Deployment')
    assert 'https://telemetry.example.com' in deployment['spec']['template']['spec']['containers'][0]['args']


def test_disabling_vibemon_preserves_the_existing_alloy_configuration():
    enabled = values('eks-demo')
    disabled = values('eks-demo', enabled=False)
    assert enabled['alloy'] == disabled['alloy']
    assert disabled['raw']['resources'] == [x for x in enabled['raw']['resources'] if not x['metadata']['name'].startswith('vibemon-collector')]
