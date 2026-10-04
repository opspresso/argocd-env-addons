"""Managed host CNI failures are collected and evaluated through Loki."""
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(chart):
    path = ROOT / 'charts' / chart
    result = subprocess.run(['helm', 'template', chart, str(path), '-f', str(path / 'values.yaml'),
                             '-f', str(path / 'eks/values-eks-demo.yaml')],
                            capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def test_host_log_collection_is_node_scoped_without_new_host_mounts():
    docs = render('alloy')
    daemon = next(doc for doc in docs if doc['kind'] == 'DaemonSet')
    alloy = next(c for c in daemon['spec']['template']['spec']['containers'] if c['name'] == 'alloy')
    assert '--disable-reporting' in alloy['args']
    host_paths = [v['hostPath']['path'] for v in daemon['spec']['template']['spec']['volumes'] if 'hostPath' in v]
    assert set(host_paths) == {'/var/log', '/var/lib/alloy'}
    config = next(doc for doc in docs if doc['kind'] == 'ConfigMap' and 'config.alloy' in doc.get('data', {}))['data']['config.alloy']
    assert 'network-policy-agent.log' in config
    assert 'ebpf-sdk.log' in config
    assert '"node" = sys.env("NODE_NAME")' in config
    assert 'action   = "drop"' in config


def test_grafana_cni_failure_rule_uses_loki_and_keeps_node_identity():
    docs = render('grafana')
    secret = next(doc for doc in docs if 'cni-health.yaml' in doc.get('stringData', {}))
    rules = yaml.safe_load(secret['stringData']['cni-health.yaml'])['groups'][0]['rules']
    query, threshold = rules[0]['data']
    assert query['datasourceUid'] == 'loki'
    assert query['model']['queryType'] == 'instant'
    assert 'sum by (cluster, node)' in query['model']['expr']
    assert 'Failed to Attach Egress TC probe' in query['model']['expr']
    assert threshold['model']['type'] == 'threshold'
    assert rules[0]['noDataState'] == 'OK'
    assert rules[0]['execErrState'] == 'Alerting'
    assert rules[0]['labels']['severity'] == 'critical'
    k3s = yaml.safe_load((ROOT / 'charts/grafana/k3s/values-k3s-demo.yaml').read_text())
    assert 'cni-health.yaml' not in k3s['grafana'].get('alerting', {})
