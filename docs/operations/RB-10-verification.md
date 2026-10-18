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

Probe pods and temporary allow policies are removed after the check. The check intentionally accepts only a Docker container name starting with `roombook-rb10-validation`; it does not target the VPS.

Both shell scripts pass `bash -n`. Release binary and installer checksums were obtained from the official K3s release/source and are checked again by bootstrap before installation. Bootstrap refuses a differing existing K3s binary or configuration.

## Remaining verification

The local cluster uses Docker Desktop on Windows. It does not prove Ubuntu systemd/UFW behaviour, public IPv4/IPv6 filtering, VPS capacity, certificates, provider access, off-server backups or Production readiness. The VPS inspection key cannot execute administrative commands.

After named administrator access is established, bootstrap can install the pinned server and namespace foundation. RB-10 remains In Progress until host access, actual installation and independent inventory/review evidence are recorded. Runtime workloads, TLS, deployment restrictions, monitoring and recovery remain in their assigned tickets.

No application API, business schema, approved design archive, GitHub subscription or repository permission changes are included.
