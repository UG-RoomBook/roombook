# RB-10 hosting foundation

Prepared on 18 October 2026. Hosting decisions are in [wiki PR 12](https://github.com/UG-RoomBook/wiki/pull/12). See [deployment instructions](../../deploy/kubernetes/README.md) for boundaries and follow-up work.

## Observed VPS

Read-only inspection found Ubuntu 24.04.5 LTS, four visible logical CPUs, 5.8 GiB RAM, approximately 384G free disk, Docker 29.9.1 and Compose 5.6.0. Docker/containerd were running. No Kubernetes, application workload or public web listener was detected. UFW was inactive. These are inspection observations, not post-installation results.

## Local verification

The foundation was rendered with Kustomize and applied to a disposable Docker K3s cluster. Server-side dry run and real apply passed. The test node reached Ready.

| Component | Pinned reference |
| --- | --- |
| K3s | v1.37.1+k3s1 |
| Local K3s image | `rancher/k3s:v1.37.1-k3s1@sha256:ca7f37d993d82ef0dcdcfecb2e0e2618ea541dbaffc620c8cedebe01a82acd0d` |
| Probe image | `busybox:1.37.0@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e` |

Run `python scripts/hosting/verify-foundation.py` against the named disposable cluster after applying the foundation. It verifies:

- Default service-account token automount disabled in all four namespaces; the test pod has no API token.
- DNS resolution works under default-deny.
- Staging cannot reach a Production HTTP test pod. Explicit permissions at both ends allow the control request.
- Production rejects a privileged pod; Staging rejects a pod exceeding its memory quota.
- K3s reports secrets encryption enabled.

Probe pods and temporary allow policies are removed after the check. The default target is a Docker container name starting with `roombook-rb10-validation`. The explicit `--on-empty-host` mode uses the host's root-only K3s configuration, requires the expected node and refuses to run when any RoomBook namespace contains pods. Use it only before runtime workloads are installed.

Both shell scripts pass `bash -n`. Release binary and installer checksums were obtained from the official K3s release/source and are checked again by bootstrap before installation. Bootstrap refuses a differing existing K3s binary or configuration.

## VPS verification

Saad's named administrator access and sudo were verified. The pinned foundation was installed on 18 October 2026 from application commit `6b18cd0c7347fb7156cccf1161415adb26d0bfc1`. The exported archive SHA-256 was `3850fdad7825d8eeaf95fcb1d2b022ef42d93d73444787864b25082ae7e15277`; bootstrap verified the K3s binary and installer checksums before installation.

| Check | Observed result |
| --- | --- |
| Server | `roombook-vps` Ready; K3s v1.37.1+k3s1, bundled containerd 2.3.4-k3s1; service enabled |
| Boundaries | Four active namespaces, expected quotas/default-deny policies, root-only separate storage directories |
| Live probe | All eleven checks passed on the empty host foundation, including DNS, isolation, token absence, pod security, quotas and encryption status |
| Public access | SSH connected over IPv4 and IPv6. TCP 80/443 connected with temporary static listeners, which were then removed |
| Private ports | External probes to 6443, 10250, 5432, 9090, 3000 and representative NodePort 30080 timed out on both address families; no NodePort Services exist |
| Credentials | Kubeconfig root-owned mode 0600; no API tokens in test pods; inspection key remains restricted |
| Existing services | Docker 29.9.1 still active, with no Docker containers listed; SSH login settings unchanged |
| Idle capacity | About 1.1 GiB RAM used, 4.7 GiB available and 383G root disk free after verification; no load-capacity claim |

Captured evidence: [bootstrap](evidence/RB-10-bootstrap.txt), [host checks](evidence/RB-10-host-checks.txt), [external TCP probes](evidence/RB-10-external-ports.json), [final runtime inventory](evidence/RB-10-runtime.txt). Text logs use LF line endings with trailing whitespace removed.

The temporary listeners proved TCP reachability only. No TLS certificate or Caddy workload was used. Test pods, their allow policies and the temporary listeners were removed; all RoomBook namespaces are empty after verification.

## Remaining verification

RB-10 is ready for Bhathiya's inventory verification and Prattay's independent review. Provider region, console recovery and remaining account/secret/alert inventory still need owner confirmation. Root/password SSH stays enabled until recovery access is verified. Deployment credentials and namespace-scoped operator access belong to the subsequent access/runtime tickets.

Application/database workloads, TLS and Staging authentication, the candidate pipeline, monitoring, encrypted backup jobs, restore exercises and shared-host load qualification remain in their assigned tickets. The application is not deployed and Production is not qualified.

No application API, business schema, approved design archive, GitHub subscription or repository permission changes are included.
