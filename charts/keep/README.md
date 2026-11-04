# keep

[Keep](https://github.com/keephq/keep)은 여러 도구의 경보를 한곳에 모아 중복을 제거하고 상관관계를 보여주는 경보 관리 도구다.
관리 클러스터(`eks-demo`)에만 배포하며 주소는 `https://keep.demo.opsp.dev`이다.

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

Argo CD의 Dex(`https://argocd.demo.opsp.dev/api/dex`)로 GitHub 로그인한다. Dex client는 `charts/argo-cd`의 `keep-sso`다.

- `opspresso:dev` 팀은 `admin` 역할을 받는다.
- 그 밖의 사용자는 매핑된 group이 없어 403을 받는다. Keep OIDC에는 기본 역할이 없다.

## 연동

Keep은 Slack 경보의 유일한 발신처다. Grafana·Alertmanager·Argo CD는 경보를 Keep으로만 보낸다.

| 대상 | 방향 | 방식 | 결과 |
| --- | --- | --- | --- |
| Grafana | Grafana → Keep | contact point `keep`(webhook, `/alerts/event/grafana`). 경보마다 따로 보낸다(`group_by: ['...']`) | Grafana 규칙 경보가 firing·resolved로 들어온다 |
| Prometheus | Prometheus → Keep | Alertmanager webhook(`/alerts/event/prometheus`, `send_resolved`). `env/<cluster>.yaml`에 `keep`이 있는 클러스터에서만 Alertmanager를 켠다. `Watchdog`은 보내지 않는다 | PrometheusRule 경보가 firing·resolved로 들어온다 |
| Argo CD | Argo CD → Keep | notifications `service.webhook.keep`(`/alerts/event`), trigger `on-keep-health`·`on-keep-sync`·`on-keep-sync-status` | 앱별 health·sync·sync status 경보. 문제와 회복을 같은 fingerprint로 보내므로 회복하면 resolved가 된다 |
| Argo CD | Keep → Argo CD | provider `argocd`(계정 `keep`, 읽기 전용) | Application·리소스 트리로 topology를 만든다 |
| Loki | Keep → Loki | provider `loki`(`grafana_loki`) | workflow에서 로그를 조회한다. Loki 로그 경보는 Grafana 규칙(`config/cni-health-alerts.yaml`)으로 들어온다 |
| Slack | Keep → Slack | provider `slack`: nalbam workspace의 Slack 앱 `Keep`(App ID `A0CEH0R5CBV`)의 bot token(`chat:write`, `chat:write.public`) → `#noti-eks-demo`(`C0BPEEU2B8S`) | 아래 workflow가 보낸다 |

- provider는 `KEEP_PROVIDERS`로 provisioning한다. backend가 시작할 때마다 목록과 맞추며, 목록에 없는 provisioned provider는 삭제한다. UI에서 바꾼 provider 설정은 다음 시작 때 덮어써진다.
- 모든 provider는 `install_webhook: false`다. Keep이 Grafana 알림 정책이나 Argo CD 설정을 직접 고치지 않게 하기 위해서다.
- Prometheus pull provider는 쓰지 않는다. `/api/v1/alerts`는 firing 경보만 보이므로 해소를 알 수 없고, fingerprint가 webhook 경보와 달라 경보가 중복된다.

## Slack 메시지

workflow는 `values-template.yaml.j2`에 있다. 소스마다 workflow를 따로 둔다. Keep은 action이 참조한 필드가 경보에 없으면 그 action을 실패시키기 때문이다.

| workflow | 보내는 경보 | 메시지 내용 |
| --- | --- | --- |
| `grafana-alert-to-slack` | Grafana 경보 전부 | 규칙 이름, summary(대상과 측정값), description(영향과 첫 조치), 심각도·시각, 대시보드·규칙·알림 끄기·Keep 링크 |
| `prometheus-alert-to-slack` | `critical`이거나 `service`가 `agent-studio`·`agent-forge`·`agent-knowledge`인 경보 | 경보 이름, description, 심각도·시각, Keep 링크 |
| `argocd-alert-to-slack` | Argo CD 경보 전부 | 앱 상태, 설명, 프로젝트·시각, Argo CD·Keep 링크 |
| `incident-to-slack` | Keep이 만든 incident | incident 이름, 경보 수, 심각도, Keep 링크 |

경보 하나의 Slack 수명:

1. firing: 채널에 🔴 메시지를 올리고 그 메시지의 `ts`를 경보의 `slack_timestamp`로 저장한다.
2. resolved: 원래 메시지를 ✅ 형태로 고치고(`chat.update`), 그 메시지의 스레드에 해소 답글을 단다.
   저장된 `ts`가 없는 경보(스레드 방식 전에 보낸 경보)는 채널에 해소 메시지를 따로 올린다.
3. 다시 firing: 새 메시지를 올리고 `slack_timestamp`를 새 `ts`로 바꾼다.

- status가 바뀔 때만 보낸다(`only_on_change: [status]`). 같은 상태의 반복 전송은 Slack에 보내지 않는다.
- 해소는 `firingCounter > 1`인 경보만 처리한다. 처음 들어온 이벤트가 resolved인 경보(예: 새 Argo CD 앱의 Healthy)는 보내지 않는다.
- 시각은 Slack date token이라 보는 사람의 시간대로 표시된다.
- 메시지를 고치려면 채널 ID가 필요하다(`env/eks-demo.yaml`의 `keep.slack.channel`).

### kube-sre 호출

문제 메시지(firing, incident)는 끝에 kube-sre agent(Agent Studio)를 멘션하고 원인 조사를 요청한다. 해소 수정·답글에는 멘션과 키워드가 없다. Studio는 메시지 수정과 다른 앱의 스레드 답글도 실행하지 않는다.

- 멘션 대상과 키워드는 `env/eks-demo.yaml`의 `keep.slack.responder`(`U0C3UAFR7SM`), `keep.slack.keyword`(`원인 조사 요청`)다.
- Agent Studio는 다른 앱의 메시지를 그 Agent의 채널 키워드가 있을 때만 실행한다. 멘션만으로는 실행하지 않는다.
  그래서 kube-sre의 연동 → Slack 봇 → **채널 키워드**에 `keep.slack.keyword`와 같은 값을 저장해야 한다.
  키워드로 시작한 실행은 그 설정을 저장한 Studio 계정의 권한과 예산을 쓴다.

## Slack 앱

nalbam workspace의 Slack 앱 `Keep`(App ID `A0CEH0R5CBV`)의 설정을 이 디렉터리에 백업한다.

| 파일 | 내용 |
| --- | --- |
| `slack-app-manifest.json` | App Manifest. 이름·설명·배경색·bot 사용자·권한(scope) |
| `slack-app-icon.png` | 앱 아이콘. Keep 저장소의 `assets/keep.png`를 1024px 정사각형으로 맞춘 것 |

bot 권한:

| scope | 용도 |
| --- | --- |
| `chat:write`, `chat:write.public` | 메시지 작성·수정, 스레드 답글. 봇이 참여하지 않은 공개 채널에도 쓴다 |
| `chat:write.customize` | 메시지마다 표시 이름·아이콘을 바꾼다 |
| `reactions:write`, `reactions:read` | 메시지에 이모지를 달고 읽는다 |
| `channels:read`, `groups:read` | 채널 정보를 조회한다 |
| `channels:history`, `groups:history` | 채널·스레드 메시지를 읽는다 |
| `users:read` | 사용자 정보를 조회한다 |
| `files:write` | 파일을 올린다 |

설정을 바꾸면 Slack의 App Manifest → Copy to Clipboard 결과로 `slack-app-manifest.json`을 갱신한다.
앱을 다시 만들 때는 api.slack.com/apps → Create New App → From a manifest에 이 파일을 넣고,
Basic Information에서 `slack-app-icon.png`를 올린 뒤 workspace에 설치한다.
권한을 바꾸면 Install App → Reinstall to nalbam으로 다시 설치해야 적용된다.

## SSM 파라미터

ExternalSecret은 파라미터가 하나라도 없으면 Secret 전체를 만들지 않는다. 처음 배포하기 전에 아래를 모두 등록한다.

| 파라미터 | 읽는 곳 |
| --- | --- |
| `/k8s/common/keep/database-password` | `addon-keep-database`(PostgreSQL), `addon-keep-backend`(접속 문자열) |
| `/k8s/common/keep/nextauth-secret` | `addon-keep-frontend` |
| `/k8s/common/keep/oidc-client-secret` | `addon-keep-frontend`, `argocd-secret`(Dex `keep-sso`) |
| `/k8s/common/keep/grafana-api-key` | `addon-keep-backend`(`KEEP_DEFAULT_API_KEYS`의 `grafana`), `grafana-secret` |
| `/k8s/common/keep/alertmanager-api-key` | `addon-keep-backend`(`KEEP_DEFAULT_API_KEYS`의 `alertmanager`), `prometheus-alertmanager-secret` |
| `/k8s/common/keep/argocd-api-key` | `addon-keep-backend`(`KEEP_DEFAULT_API_KEYS`의 `argocd`), `argocd-notifications-secret` |
| `/k8s/common/keep/argocd-api-token` | `addon-keep-backend`(provider `argocd`). `install/eks/token.sh --account keep`이 만든다 |
| `/k8s/common/keep/slack-bot-token` | `addon-keep-backend`(provider `slack`). Slack 앱 `Keep`(api.slack.com/apps, nalbam workspace)의 Install App → Bot User OAuth Token |
| `/k8s/common/argocd-keep-tokens` | `argocd-secret`의 `accounts.keep.tokens`. 위와 같은 스크립트가 만든다 |

```bash
# URL에 들어가므로 hex 값을 쓴다. 이미 있으면 덮어쓰지 않는다.
for name in database-password nextauth-secret oidc-client-secret grafana-api-key argocd-api-key alertmanager-api-key; do
  aws ssm put-parameter --name "/k8s/common/keep/${name}" --value "$(openssl rand -hex 32)" --type SecureString | jq .Version
done

# Argo CD keep 계정의 토큰. install/eks/install.sh도 매번 실행한다.
(cd install/eks && ./token.sh --account keep)
```

### 값 교체

- `database-password`: PostgreSQL은 처음 초기화할 때만 비밀번호를 읽는다. 바꾸려면 DB에서 `ALTER USER postgres PASSWORD ...`를 먼저 실행한 뒤 파라미터를 바꾼다.
- `grafana-api-key`, `argocd-api-key`, `alertmanager-api-key`: Keep은 같은 이름의 API key가 있으면 새 값으로 바꾸지 않는다. Keep UI(Settings → API Keys)에서 기존 key를 삭제한 뒤 파라미터를 바꾸고 `keep-backend`를 재시작한다.
- `oidc-client-secret`: 바꾼 뒤 `argocd-dex-server`와 `keep-frontend`를 재시작한다.

## 검증

```bash
./scripts/gen_values.py -p eks -r keep
./scripts/validate.py -r keep
python3 -m pytest -q tests/test_keep.py
```
