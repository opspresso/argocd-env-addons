# oauth2-proxy

관리 도구 앞에서 플랫폼 Dex(`charts/dex`, client `oauth2-proxy-sso`)의 관리자 로그인을 요구한다.
namespace는 `addon-oauth2-proxy`, callback 주소는 `https://auth.demo.opsp.dev/oauth2/callback`이다.
배포된 보호 대상은 LLDAP 웹 UI(`id.demo.opsp.dev`)다. Atlantis UI, Nexus, Argo Rollouts dashboard는 `backup/`에 있다.

- Istio의 extension provider `oauth2-proxy`(`charts/istio`)가 이 Service로 인증을 묻는다. 서비스는
  `istio-system`에 `action: CUSTOM`, `provider: oauth2-proxy`인 AuthorizationPolicy를 둔다(예: `charts/atlantis`).
- `sso.admin_groups`(`sre`) 구성원만 통과한다(`allowed_groups`). 다른 사용자는 403을 받는다.
  모든 구성원이 쓰는 서비스를 보호하려면 별도 oauth2-proxy를 둔다. 허용된 요청에는 `x-auth-request-user`, `x-auth-request-email`,
  `x-auth-request-preferred-username`, `x-auth-request-groups` header가 붙는다.
- cookie는 `.demo.opsp.dev` 전체에 쓴다. 한 번 로그인하면 보호된 모든 host에 적용된다.

| 파라미터 | 용도 |
| --- | --- |
| `/k8s/common/oauth2-proxy-client-secret` | Dex client `oauth2-proxy-sso`의 secret. 플랫폼 Dex의 `dex-secret`도 읽는다 |
| `/k8s/common/cookie-secret` | cookie 암호화 키(16·24·32 byte) |

두 값은 `install/eks/secrets.sh`가 없을 때만 만든다.
