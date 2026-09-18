# k3s용 Argo CD 설치

Traefik Gateway API를 사용하는 단일 노드 k3s에 Argo CD와 이 저장소의
`addons` Application을 설치한다. cert-manager와 Let's Encrypt DNS-01로
`*.demo.opsp.dev` 와일드카드 인증서를 발급한다. AWS ACM, ALB, external-dns, GitHub OAuth에는
의존하지 않지만, 관리자 인증 정보와 cert-manager 권한 조회를 위해 AWS SSM과 Instance Profile을
사용한다.

## 사전 조건

- k3s가 설치되어 있어야 한다.
- `kubectl`이 대상 k3s 클러스터를 가리켜야 한다.
- `../terraform-env-demo/demo/9-agent-studio/bootstrap-k3s.sh`를 먼저 실행해야 한다.
- bootstrap이 설치한 `helm`, `aws`, `jq`, `argocd` CLI가 PATH에 있어야 한다.
- `argocd.demo.opsp.dev`가 k3s 인스턴스의 public IP를 가리켜야 한다.
- Route53 `demo.opsp.dev` Hosted Zone이 있어야 한다.
- EC2 Instance Profile에 cert-manager용 Route53 권한이 있어야 한다.

`helm`과 `argocd` CLI는 이 저장소에서 설치하지 않는다. k3s 인스턴스의
`terraform-env-demo/demo/9-agent-studio/bootstrap-k3s.sh`가 두 CLI와 k3s를 설치하고
`/home/ec2-user/.kube/config`를 설정한다.

## DNS

DNS에 다음 A 레코드를 먼저 등록한다. `<k3s-instance-public-ip>`에는 대상 인스턴스의
현재 public IP를 입력한다.

```text
argocd.demo.opsp.dev.  A  <k3s-instance-public-ip>
```

인증서 발급 전까지는 DNS 전파가 완료되어야 한다. `sre@opspresso.com`을 사용할 수
없으면 설치 전에 `install/k3s/cluster-issuer.yaml`의 ACME 이메일을 변경한다.

스크립트는 `/etc/rancher/k3s/k3s.yaml`을 자동으로 사용한다. 해당 파일이 root만 읽을 수
있으면 `kubectl`과 `helm`에 `sudo`를 사용한다. 다른 클러스터를 대상으로 설치할 때는
`KUBECONFIG` 환경 변수로 덮어쓴다.

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
4. Gateway API CRD를 설치한다.
5. `install/k3s/values.yaml`로 HTTPRoute 기반 Argo CD를 설치한다.
6. `*.demo.opsp.dev` 인증서를 `traefik-gateway-tls` Secret으로 발급 요청한다.
7. `addons`, `apps` AppProject를 생성한다.
8. 저장소 루트의 `addons-k3s.yaml`을 등록하고 SSM 관리자 계정으로 로그인한다.
9. 이전 설치에서 남은 `argocd-server` Ingress를 삭제한다.

Argo CD는 `Ingress`를 생성하지 않는다. `traefik-gateway` Gateway와
`argocd-server` HTTPRoute가 HTTPS를 종료하고 Argo CD Service의 HTTP 포트로 전달한다.

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
