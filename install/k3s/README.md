# k3s용 Argo CD 설치

Traefik이 기본 Ingress Controller인 단일 노드 k3s에 Argo CD와 이 저장소의
`addons` Application을 설치한다. cert-manager와 Let's Encrypt DNS-01로
`*.demo.opsp.dev` 와일드카드 인증서를 발급한다. AWS ACM, ALB, external-dns, SSM, GitHub OAuth에는
의존하지 않는다.

## 사전 조건

- k3s가 설치되어 있어야 한다.
- `kubectl`이 대상 k3s 클러스터를 가리켜야 한다.
- `helm`이 설치되어 있어야 한다.
- `aws`, `jq`, `argocd` CLI가 설치되어 있어야 한다.
- `argocd.demo.opsp.dev`가 `13.124.244.200`을 가리켜야 한다.
- Route53 `demo.opsp.dev` Hosted Zone이 있어야 한다.
- EC2 Instance Profile에 cert-manager용 Route53 권한이 있어야 한다.

## DNS

DNS에 다음 A 레코드를 먼저 등록한다.

```text
argocd.demo.opsp.dev.  A  13.124.244.200
```

인증서 발급 전까지는 DNS 전파가 완료되어야 한다. `sre@opspresso.com`을 사용할 수
없으면 설치 전에 `install/k3s/cluster-issuer.yaml`의 ACME 이메일을 변경한다.

스크립트는 `/etc/rancher/k3s/k3s.yaml`을 자동으로 사용한다. 다른 클러스터를 대상으로
설치할 때는 `KUBECONFIG` 환경 변수로 덮어쓴다.

cert-manager가 사용하는 EC2 Instance Profile에는 최소한 다음 권한이 필요하다.

- `route53:GetChange`
- `route53:ChangeResourceRecordSets`
- `route53:ListResourceRecordSets`
- `route53:ListHostedZonesByName`

## 설치

저장소 루트에서 실행한다.

```bash
./install/k3s/install.sh
```

스크립트는 다음을 수행한다.

1. Argo와 cert-manager Helm repository를 등록하고 갱신한다.
2. AWS SSM에서 Argo CD 관리자 계정과 bcrypt 비밀번호를 조회한다.
3. cert-manager와 Route53 DNS-01 방식의 `letsencrypt-prod` ClusterIssuer를 설치한다.
4. `install/k3s/values.yaml`로 HTTPS Argo CD를 설치한다.
5. `*.demo.opsp.dev` 인증서를 `traefik-gateway-tls` Secret으로 발급 요청한다.
6. `addons`, `apps` AppProject를 생성한다.
7. 저장소 루트의 `addons-k3s.yaml`을 등록하고 SSM 관리자 계정으로 로그인한다.

## 접속

주소는 `https://argocd.demo.opsp.dev`이다. 관리자 계정은 AWS SSM Parameter Store의
다음 파라미터를 사용한다.

```bash
export ADMIN_USERNAME=$(aws ssm get-parameter --name /k8s/common/admin-user --with-decryption | jq .Parameter.Value -r)
export ADMIN_PASSWORD=$(aws ssm get-parameter --name /k8s/common/admin-password --with-decryption | jq .Parameter.Value -r)

argocd login argocd.demo.opsp.dev \
  --grpc-web --skip-test-tls \
  --username "$ADMIN_USERNAME" --password "$ADMIN_PASSWORD"
```

인증서 발급 상태는 다음 명령으로 확인한다.

```bash
kubectl get certificate -n traefik-gateway
kubectl describe certificate -n traefik-gateway traefik-gateway-tls
```
