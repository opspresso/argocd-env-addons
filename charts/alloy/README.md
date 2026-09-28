# Alloy

k3s의 메트릭을 Grafana Cloud로 전송합니다. `addons/k3s/alloy.yaml`이
`addon-alloy` namespace에 배포하며, 연결 정보는 `env/k3s-demo.yaml`의
`grafana_cloud`에서 읽습니다. 수집 설정은 `values-template.yaml.j2`에서 관리합니다.

## 수집 대상

| 대상 | job | 주기 |
| --- | --- | --- |
| 호스트 | `integrations/node_exporter` | 15초 |
| kubelet | `kubelet` | 30초 |
| 컨테이너 | `integrations/cadvisor` | 15초 |
| Agent Studio | `agent-studio` | 15초 |
| Agent Memory | `agent-memory` | 15초 |

호스트와 앱의 `instance`는 클러스터 이름입니다. cAdvisor의 `service`는 workload
이름으로 맞춰 `../dockpad/grafana`의 Agent Platform 대시보드에서 조회할 수 있습니다.
앱 메트릭은 `/api/metrics`에서 수집하며 Agent Memory는 Bearer token을 사용합니다.
kubelet은 노드·실행 수·볼륨·runtime 상태를, cAdvisor는 대시보드의
CPU·메모리·네트워크·디스크 I/O·OOM 메트릭을 전송해 Cloud 시리즈 사용량을 제한합니다.
호스트와 앱 메트릭은 전체를 전송합니다.

## 인증

External Secrets가 `parameter-store` ClusterSecretStore를 통해 다음 SSM SecureString을
읽어 `alloy-grafana-cloud` Secret을 생성합니다. 토큰 값은 Git에 저장하지 않습니다.

- `/k8s/common/grafana-cloud/remote-write-api-key`: Grafana Cloud metrics write token
- `/k8s/<cluster>/agent-memory/metrics-bearer-token`: Agent Memory metrics token

`<cluster>`는 `env/<cluster>.yaml`의 `cluster`입니다. 기존 파라미터를 재사용하며,
노드 IAM 역할에는 해당 SSM 파라미터 읽기·복호화 권한이 필요합니다.
Secret을 환경변수로 읽으므로 토큰 교체 후 Alloy Pod를 재시작합니다.

## 적용과 확인

저장소 루트에서 실행합니다. 생성된 values는 직접 수정하지 않습니다.

```bash
./scripts/gen_values.py -p k3s -r alloy
./scripts/validate.py -r alloy
```

Git에 반영하면 `addons-k3s`가 Application을 자동 동기화합니다.
Alloy의 WAL은 노드의 `/var/lib/alloy`에 유지됩니다.

```bash
kubectl get application alloy-k3s -n argocd
kubectl get pods,externalsecret -n addon-alloy
kubectl logs -n addon-alloy daemonset/alloy -c alloy --tail=50
```

Grafana 대시보드에서 `instance=k3s-demo`를 선택합니다.
