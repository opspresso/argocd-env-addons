# argo-cd

## mcp account

`accounts.mcp` 는 mcp-argocd (argocd-env-demo) 가 쓰는 API 토큰 전용 계정 입니다.
`apiKey` 만 주고 `login` 은 주지 않으므로 비밀번호가 없고, 권한은 `role:mcp` 가
정합니다 — `values-template.yaml.j2` 를 보세요.

## token

토큰은 `install/token.sh` 가 만들어 SSM 에 고정 합니다. 여기서 할 일은 없습니다.
같은 스크립트가 `server.secretkey` 도 **없을 때만** 만듭니다 — 토큰이 그 키로
서명되기 때문에 둘은 같이 움직입니다.

```bash
cd ../../install && ./token.sh
```

Argo CD 가 토큰을 받을 때 보는 것은 세 가지 입니다
(argoproj/argo-cd `util/session/sessionmanager.go`).

1. `server.secretkey` 로 서명한 HS256 JWT
2. `sub` 가 `mcp:apiKey` 이고 그 계정에 `apiKey` capability 가 있을 것
3. `jti` 가 `accounts.mcp.tokens` 목록에 있을 것

셋 다 SSM 에 고정되어 있으므로 클러스터를 다시 만들어도 같은 토큰이 그대로
통합니다. `argocd account generate-token` 을 쓰지 않는 이유가 이것 입니다 —
그 명령은 3 번 목록을 클러스터 안 `argocd-secret` 에만 남기고, 이 chart 의
ExternalSecret 이 그 Secret 을 소유하므로 다음 refresh 에 지워집니다.

| 파라미터 | 읽는 곳 |
|---|---|
| `/k8s/common/argocd-server-secret` | 이 chart 의 `argocd-secret` ExternalSecret (`server.secretkey`), 그리고 `install/values.yaml` |
| `/k8s/common/argocd-mcp-tokens` | 이 chart 의 `argocd-secret` ExternalSecret (`accounts.mcp.tokens`), 그리고 `install/values.yaml` |
| `/k8s/common/mcp-argocd/argocd-api-token` | mcp-argocd 파드의 `ARGOCD_API_TOKEN` (argocd-env-demo) |

`/k8s/common/argocd-mcp-tokens` 는 이 chart 를 sync 하기 **전에** 있어야 합니다.
없으면 ExternalSecret 이 통째로 실패해서, 새 클러스터에서는 `argocd-secret` 자체가
생기지 않습니다. `install/token.sh` 가 그것까지 처리 합니다.

토큰을 폐기 하려면 `./token.sh --rotate` 로 갈아 끼우거나, 파라미터를 `[]` 로
되돌려 계정의 모든 토큰을 무효화 합니다.
