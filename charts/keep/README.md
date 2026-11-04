# keep

[Keep](https://github.com/keephq/keep)은 여러 도구의 경보를 한곳에 모아 중복을 제거하고 상관관계를 보여주는 경보 관리 도구다.
관리 클러스터(`eks-demo`)에만 배포하며 주소는 `https://keep.demo.rovr.dev`이다.

## 구성

| 구성 요소 | 내용 |
| --- | --- |
| `keep-frontend` | Next.js UI. HTTPRoute `keep`이 `/` 전체를 이 Service로 보낸다. 브라우저의 API 호출은 UI의 `/backend` rewrite를 거쳐 `keep-backend`로 간다 |
| `keep-backend` | API·스케줄러. 시작할 때 DB migration과 provider·API key provisioning을 실행한다 |
| `keep-database` | PostgreSQL 18. gp3 PVC 10Gi. 업그레이드 시 `maxSurge: 0`으로 기존 Pod가 먼저 내려간다 |

- upstream chart `keephq/keep`을 dependency로 쓴다. 이미지는 OIDC 로그인 때문에 `0.55.0`으로 덮어쓴다. chart 기본 이미지(0.54.3)에는 `AUTH_TYPE=OIDC`가 없다.
- websocket 서버(Soketi)는 끈다(`PUSHER_DISABLED=true`). Soketi는 app secret을 평문 값으로만 받기 때문이다. UI는 실시간 push 대신 polling으로 갱신한다.
- upstream chart의 pre-delete hook `delete-keep-secrets`는 이름이 `keep-`로 시작하는 Secret을 모두 지운다. 그래서 이 chart가 만드는 Secret은 `addon-keep-*`로 이름을 짓는다. 이 hook은 리소스 값을 설정할 수 없어 `scripts/workload_policy.py`가 정책 검사에서 이 Job만 예외로 둔다.

## 로그인

Argo CD의 Dex(`https://argocd.demo.rovr.dev/api/dex`)로 GitHub 로그인한다. Dex client는 `charts/argo-cd`의 `keep-sso`다.

- `opspresso:dev` 팀은 `admin` 역할을 받는다.
- 그 밖의 사용자는 매핑된 group이 없어 403을 받는다. Keep OIDC에는 기본 역할이 없다.

## 연동

| 대상 | 방향 | 방식 | 결과 |
| --- | --- | --- | --- |
| Grafana | Grafana → Keep | contact point `keep`(webhook, `/alerts/event/grafana`). 알림 정책의 첫 route가 모든 경보를 Keep에 보내고 `continue`로 Slack route를 계속 평가한다 | Grafana 경보가 firing·resolved로 들어온다 |
| Argo CD | Argo CD → Keep | notifications `service.webhook.keep`(`/alerts/event`), trigger `on-keep-health`·`on-keep-sync` | 앱별 health·sync 경보. 문제와 회복을 같은 fingerprint로 보내므로 회복하면 resolved가 된다 |
| Argo CD | Keep → Argo CD | provider `argocd`(계정 `keep`, 읽기 전용) | Application·리소스 트리로 topology를 만든다 |
| Prometheus | Keep → Prometheus | provider `prometheus`(`/api/v1/alerts` pull) | Prometheus 규칙의 firing 경보가 들어온다. Alertmanager는 꺼져 있으므로 이 경로가 유일하다 |
| Loki | Keep → Loki | provider `loki`(`grafana_loki`) | workflow에서 로그를 조회한다. Loki는 경보를 보내지 않는다 |

- provider는 `KEEP_PROVIDERS`로 provisioning한다. backend가 시작할 때마다 목록과 맞추며, 목록에 없는 provisioned provider는 삭제한다. UI에서 바꾼 provider 설정은 다음 시작 때 덮어써진다.
- 모든 provider는 `install_webhook: false`다. Keep이 Grafana 알림 정책이나 Argo CD 설정을 직접 고치지 않게 하기 위해서다.
- Argo CD trigger는 조건이 거짓에서 참으로 바뀔 때마다 보낸다. 그래서 처음 배포할 때와 앱이 Progressing에서 Healthy로 돌아올 때마다 resolved 이벤트가 같은 경보에 기록된다.

## SSM 파라미터

ExternalSecret은 파라미터가 하나라도 없으면 Secret 전체를 만들지 않는다. 처음 배포하기 전에 아래를 모두 등록한다.

| 파라미터 | 읽는 곳 |
| --- | --- |
| `/k8s/common/keep/database-password` | `addon-keep-database`(PostgreSQL), `addon-keep-backend`(접속 문자열) |
| `/k8s/common/keep/nextauth-secret` | `addon-keep-frontend` |
| `/k8s/common/keep/oidc-client-secret` | `addon-keep-frontend`, `argocd-secret`(Dex `keep-sso`) |
| `/k8s/common/keep/grafana-api-key` | `addon-keep-backend`(`KEEP_DEFAULT_API_KEYS`의 `grafana`), `grafana-secret` |
| `/k8s/common/keep/argocd-api-key` | `addon-keep-backend`(`KEEP_DEFAULT_API_KEYS`의 `argocd`), `argocd-notifications-secret` |
| `/k8s/common/keep/argocd-api-token` | `addon-keep-backend`(provider `argocd`). `install/eks/token.sh --account keep`이 만든다 |
| `/k8s/common/argocd-keep-tokens` | `argocd-secret`의 `accounts.keep.tokens`. 위와 같은 스크립트가 만든다 |

```bash
# URL에 들어가므로 hex 값을 쓴다. 이미 있으면 덮어쓰지 않는다.
for name in database-password nextauth-secret oidc-client-secret grafana-api-key argocd-api-key; do
  aws ssm put-parameter --name "/k8s/common/keep/${name}" --value "$(openssl rand -hex 32)" --type SecureString | jq .Version
done

# Argo CD keep 계정의 토큰. install/eks/install.sh도 매번 실행한다.
(cd install/eks && ./token.sh --account keep)
```

### 값 교체

- `database-password`: PostgreSQL은 처음 초기화할 때만 비밀번호를 읽는다. 바꾸려면 DB에서 `ALTER USER postgres PASSWORD ...`를 먼저 실행한 뒤 파라미터를 바꾼다.
- `grafana-api-key`, `argocd-api-key`: Keep은 같은 이름의 API key가 있으면 새 값으로 바꾸지 않는다. Keep UI(Settings → API Keys)에서 기존 key를 삭제한 뒤 파라미터를 바꾸고 `keep-backend`를 재시작한다.
- `oidc-client-secret`: 바꾼 뒤 `argocd-dex-server`와 `keep-frontend`를 재시작한다.

## 검증

```bash
./scripts/gen_values.py -p eks -r keep
./scripts/validate.py -r keep
python3 -m pytest -q tests/test_keep.py
```
