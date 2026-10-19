# RoomBook Kubernetes foundation

Status: Historical foundation; superseded for delivery by [ADR-012](https://github.com/UG-RoomBook/wiki/blob/main/decisions/ADR-012-restore-submitted-aws-pipeline.md) on 19 October 2026. The current baseline uses three EC2 roles, Docker Compose and self-hosted GitHub Actions runners. The installation and follow-up instructions below describe the earlier Contabo plan and are retained for traceability; new delivery work follows ADR-012. Merging this directory does not authorize a deployment or adopt the separate Proposed AWS/GitOps alternative.

RB-10 prepares the host and namespace boundaries from [ADR-010](https://github.com/UG-RoomBook/wiki/pull/12). This foundation does not deploy an application, database, public proxy or monitoring stack. Existing tickets retain their implementers and acceptance checks.

## Layout

`cluster/` pins K3s and its server settings. `foundation/` combines namespaces, priority classes and the four environment overlays. The shared base disables default service-account token mounts, supplies resource defaults and denies pod ingress/egress except cluster DNS.

| Namespace | Memory request ceiling | Memory limit ceiling | Owner |
| --- | --- | --- | --- |
| roombook-prod | 768 MiB | 1280 MiB | Bhathiya runtime; Saad initial setup |
| roombook-staging | 512 MiB | 1024 MiB | Bhathiya runtime; Prattay deployment |
| roombook-monitoring | 512 MiB | 896 MiB | Bhathiya |
| roombook-edge | 64 MiB | 128 MiB | Bhathiya runtime; Saad DNS/secrets |

Production/Staging enforce restricted pod security. Monitoring permits the host visibility required by exporters, with restricted-policy auditing; only trusted operators may install those workloads. Edge uses baseline policy for Caddy. Priority classes influence eviction order and do not provide dedicated host resources or high availability.

Networking is intentionally closed until the corresponding workload PR adds explicit proxy, app/database, provider, backup and scrape permissions. Namespace separation is not VM isolation. Do not weaken default-deny to make an incomplete deployment start.

Persistent services must use retained local PersistentVolumes with distinct directories under `/srv/roombook`. The default delete-on-claim-removal local provisioner is disabled. Each workload must explicitly disable API token automount, set requests/limits and select its priority class. Publish no NodePort services. Caddy is the only LoadBalancer Service and must set `allocateLoadBalancerNodePorts: false`.

## Install and verify

Saad performs privileged initial setup with `scripts/hosting/bootstrap-k3s.sh`; Bhathiya verifies the inventory and Prattay reviews RB-10. The script requires a reviewed Linux checkout/bundle, an operator key established separately and root privileges. The inspection key cannot execute it. It preserves Docker and does not disable existing SSH/password access automatically.

After bootstrap:

```sh
sudo kubectl get nodes
sudo kubectl get namespaces -l app.kubernetes.io/part-of=roombook
sudo kubectl get resourcequota,limitrange,networkpolicy -A
sudo k3s secrets-encrypt status
```

Use the local disposable-cluster verification in the implementation record before accepting configuration. A manifest build or server-side dry run is not network-isolation or Production qualification evidence.

### Local verification

The commands below create only a disposable local Docker cluster. ServiceLB is disabled in this test container because live port publishing is verified separately on the VPS.

```sh
docker run -d --name roombook-rb10-validation --privileged \
  -p 127.0.0.1:16443:6443 \
  rancher/k3s:v1.37.1-k3s1@sha256:ca7f37d993d82ef0dcdcfecb2e0e2618ea541dbaffc620c8cedebe01a82acd0d \
  server --disable=traefik --disable=servicelb --disable=local-storage \
  --secrets-encryption --node-name=roombook-rb10-validation
kubectl kustomize deploy/kubernetes/foundation > foundation.yaml
docker cp foundation.yaml roombook-rb10-validation:/tmp/foundation.yaml
docker exec roombook-rb10-validation kubectl wait nodes --all --for=condition=Ready --timeout=170s
docker exec roombook-rb10-validation kubectl apply -f /tmp/foundation.yaml
docker exec roombook-rb10-validation kubectl apply --dry-run=server -f /tmp/foundation.yaml
python scripts/hosting/verify-foundation.py
docker rm -f roombook-rb10-validation
```

Keep generated `foundation.yaml` outside Git. Results and limitations are in the [RB-10 verification record](../../docs/operations/RB-10-verification.md).

For initial verification on the installed host, use `sudo python3 scripts/hosting/verify-foundation.py --on-empty-host` from a reviewed source checkout. This mode requires root, the expected K3s node and four empty RoomBook namespaces. It creates temporary probes and narrowly scoped allow policies, then removes them. It refuses to run once runtime pods exist; use the assigned acceptance tests at that point.

## Follow-up work

- Prattay, RB-20/RB-21/RB-22/RB-23/RB-26: manifest checks, GitHub-hosted candidate tests, one image, restricted deployment commands and digest promotion.
- Bhathiya, RB-29/RB-30/RB-31/RB-32/RB-33/RB-34: persistent PostgreSQL, Caddy/TLS verification, monitoring, Worker alerts, R2/restic, deployment recovery and qualification.
- Saad, RB-48: initial named access, domain, Supabase/Resend and protected secrets. No credentials belong in this directory.
- Daniel: independent system, isolation, recovery and shared-host load verification.

Keep Production unqualified until the complete application, security, test and recovery gates pass. No runtime, provider account or alert is reported complete by this source configuration.
