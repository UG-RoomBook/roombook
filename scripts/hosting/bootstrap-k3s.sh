#!/usr/bin/env bash
set -euo pipefail

fail() { printf '%s\n' "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail 'Run this reviewed bootstrap as root.'
[[ ${1:-} == --apply && $# -eq 1 ]] || fail 'Usage: bootstrap-k3s.sh --apply'
root_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cluster_dir="${root_dir}/deploy/kubernetes/cluster"
# This checked-in file contains release identifiers and checksums only.
source "${cluster_dir}/versions.env"
[[ $(uname -m) == x86_64 ]] || fail 'This release lock is for linux/amd64.'
source /etc/os-release
[[ ${ID} == ubuntu && ${VERSION_ID} == 24.04 ]] || fail 'This bootstrap targets the inspected Ubuntu 24.04 host.'
for tool in curl sha256sum systemctl ufw install cmp; do
  command -v "$tool" >/dev/null || fail "Missing prerequisite: ${tool}"
done
grep -Eq '^IPV6=yes$' /etc/default/ufw || fail 'Enable and verify UFW IPv6 support before bootstrap.'
[[ ${K3S_VERSION} =~ ^v[0-9]+\.[0-9]+\.[0-9]+\+k3s[0-9]+$ ]] || fail 'Invalid release lock.'
[[ ${K3S_SOURCE_COMMIT} =~ ^[0-9a-f]{40}$ ]] || fail 'Invalid source commit.'
[[ ${K3S_BINARY_SHA256} =~ ^[0-9a-f]{64}$ && ${K3S_INSTALLER_SHA256} =~ ^[0-9a-f]{64}$ ]] || fail 'Invalid release checksums.'

if [[ -e /etc/rancher/k3s/config.yaml ]]; then
  cmp -s "${cluster_dir}/config.yaml" /etc/rancher/k3s/config.yaml || fail 'An existing K3s configuration differs; review it instead of overwriting it.'
fi
if [[ -e /usr/local/bin/k3s ]]; then
  printf '%s  %s\n' "${K3S_BINARY_SHA256}" /usr/local/bin/k3s | sha256sum --check --status || fail 'An existing K3s binary differs; this script does not upgrade it.'
fi

work_dir=$(mktemp -d /tmp/roombook-rb10.XXXXXX)
cleanup() {
  rm -f -- "${work_dir}/k3s" "${work_dir}/install.sh"
  rmdir -- "${work_dir}"
}
trap cleanup EXIT
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
  "https://github.com/k3s-io/k3s/releases/download/${K3S_VERSION/+/%2B}/k3s" -o "${work_dir}/k3s"
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
  "https://raw.githubusercontent.com/k3s-io/k3s/${K3S_SOURCE_COMMIT}/install.sh" -o "${work_dir}/install.sh"
printf '%s  %s\n' "${K3S_BINARY_SHA256}" "${work_dir}/k3s" | sha256sum --check --status || fail 'K3s binary checksum mismatch.'
printf '%s  %s\n' "${K3S_INSTALLER_SHA256}" "${work_dir}/install.sh" | sha256sum --check --status || fail 'K3s installer checksum mismatch.'

# Close host ingress before starting the API. Preserve existing SSH access.
ufw default deny incoming
ufw default allow outgoing
ufw default deny routed
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow from 10.42.0.0/16
ufw allow from 10.43.0.0/16
ufw route allow from 10.42.0.0/16
ufw route allow proto tcp from any to any port 80
ufw route allow proto tcp from any to any port 443
ufw --force enable

install -d -m 0700 /etc/rancher/k3s
install -m 0600 "${cluster_dir}/config.yaml" /etc/rancher/k3s/config.yaml
install -m 0755 "${work_dir}/k3s" /usr/local/bin/k3s
INSTALL_K3S_SKIP_DOWNLOAD=true INSTALL_K3S_SKIP_START=true INSTALL_K3S_VERSION="${K3S_VERSION}" \
  sh "${work_dir}/install.sh" server
systemctl start k3s
timeout 180 bash -c 'until /usr/local/bin/kubectl get node/roombook-vps >/dev/null 2>&1; do sleep 2; done; exec /usr/local/bin/kubectl wait node/roombook-vps --for=condition=Ready --timeout=170s'

install -d -m 0700 /srv/roombook /srv/roombook/production /srv/roombook/staging /srv/roombook/monitoring /srv/roombook/edge
/usr/local/bin/kubectl apply -k "${root_dir}/deploy/kubernetes/foundation"
/usr/local/bin/kubectl get namespaces -l app.kubernetes.io/part-of=roombook
/usr/local/bin/kubectl get resourcequota -A
ufw status verbose
printf '%s\n' 'K3s foundation installed. Application, database, HTTPS, monitoring and recovery qualification remain in their assigned tickets.'
