# oauth2-proxy

자체 로그인이 없는 서비스(Atlantis 등) 앞에서 Argo CD Dex(client `oauth2-proxy-sso`)로 로그인을 요구한다.
namespace는 `addon-oauth2-proxy`, callback 주소는 `https://auth.demo.opsp.dev/oauth2/callback`이다.

- Istio의 extension provider `oauth2-proxy`(`charts/istio`)가 이 Service로 인증을 묻는다. 서비스는
  `istio-system`에 `action: CUSTOM`, `provider: oauth2-proxy`인 AuthorizationPolicy를 둔다(예: `charts/atlantis`).
- Dex는 `sso` 그룹 구성원만 받는다. 허용된 요청에는 `x-auth-request-user`, `x-auth-request-email`,
  `x-auth-request-preferred-username`, `x-auth-request-groups` header가 붙는다.
- cookie는 `.demo.opsp.dev` 전체에 쓴다. 한 번 로그인하면 보호된 모든 host에 적용된다.

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/oauth2-proxy-client-secret` | Dex client `oauth2-proxy-sso`의 secret. Argo CD `argocd-secret`도 읽는다 |
| `/k8s/common/cookie-secret` | cookie 암호화 키(16·24·32 byte) |
