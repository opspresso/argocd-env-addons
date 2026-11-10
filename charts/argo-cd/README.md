# argo-cd

## Keep 알림

Argo CD notifications는 Slack으로 직접 보내지 않는다. `service.webhook.keep`으로 Keep에만 보내고,
Slack 메시지는 Keep이 만든다(`charts/keep/README.md`).

| trigger | firing | resolved |
| --- | --- | --- |
| `on-keep-sync` | sync 작업이 `Error`·`Failed` | sync 작업이 `Succeeded` |

- 구독은 `values-template.yaml.j2`의 `subscriptions`에 있으며 `env/<cluster>.yaml`에 `keep`이 있을 때만 만든다.
- `X-API-KEY`는 `argocd-notifications-secret`의 `keep-api-key`(`/k8s/common/keep/argocd-api-key`)다.
- 템플릿은 앱별 fingerprint로 문제와 회복을 보내므로, 회복하면 Keep에서 같은 경보가 resolved가 된다.
- health `Degraded`와 sync status `Unknown`은 보내지 않는다. 설치·배포·삭제 중에 잠깐 나타나고, notifications는 지속 시간을
  기다릴 수 없으며, 삭제된 앱은 회복을 보내지 않아 경보가 닫히지 않기 때문이다. 대신 Grafana 규칙이 controller metric
  `argocd_app_info`로 10분 넘게 `Degraded`이거나 15분 넘게 `Unknown`인 앱을 알린다(`charts/grafana/README.md`).

키를 바꾼 뒤 ExternalSecret을 즉시 갱신하려면 다음 명령을 실행한다.

```bash
kubectl --context eks-demo -n argocd annotate externalsecret argocd-notifications-secret \
  force-sync="$(date +%s)" --overwrite
```

## mcp account

`accounts.mcp` 는 mcp-argocd (argocd-env-apps) 가 쓰는 API 토큰 전용 계정 입니다.
`apiKey` 만 주고 `login` 은 주지 않으므로 비밀번호가 없고, 권한은 `role:mcp` 가
정합니다 — `values-template.yaml.j2` 를 보세요.

현재 역할은 모든 Application의 생성·변경·삭제·동기화를 허용한다. Argo CD 자체도
대상이므로 Helm 값 변경을 통해 RBAC나 클러스터 리소스를 바꿀 수 있다. 이 토큰은
관리자 자격 증명으로 취급해야 한다. [Argo CD의 프로젝트 보안 계약](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#projects)을 따른다.

조회 전용으로 운영하려면 이 템플릿과 `install/eks/values.yaml`에서
create/update/delete/sync/action 권한을 함께 제거한다. `MCP_READ_ONLY`는 도구 노출 설정일 뿐
서버 권한을 제한하지 않는다. `policy.default`로 받은 권한은 deny로 제거할 수 없으므로
읽기 범위를 좁히려면 기본 역할부터 조정한다. [RBAC 기본 권한 설명](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/#default-policy-for-authenticated-users).

## 로그인과 token

- 로그인은 플랫폼 Dex(`charts/dex`)의 client `argo-cd`다(`oidc.config`). 내장 Dex는 끈다(`argocd.dex.enabled: false`).
  client secret은 `/k8s/common/argocd/oidc-client-secret`이며 `argocd-secret`의 `oidc.lldap.clientSecret`으로 읽는다.
  `argocd login <host> --sso`는 public client `argo-cd-cli`를 쓴다.
- 로컬 `admin`(`/k8s/common/argocd-password`, `admin-password`의 bcrypt)은 비상용이다.
- `server.secretkey`와 `mcp`·`keep` 계정 토큰은 `install/eks/token.sh`가 SSM에 고정한다. 동작과 파라미터는
  [install/eks README](../../install/eks/README.md#server-secret-and-api-tokens)에 있다.
- ExternalSecret `argocd-secret`은 파라미터가 하나라도 없으면 통째로 실패한다. 새 클러스터에서는 `install/eks/install.sh`가
  먼저 모든 값을 만든다.
