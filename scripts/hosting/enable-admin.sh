#!/usr/bin/env bash
set -euo pipefail

fail() { printf '%s\n' "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail 'Run this access setup as root.'
[[ $# -eq 1 && -f $1 ]] || fail 'Usage: enable-admin.sh /path/to/saad-admin.pub'
for tool in sudo visudo ssh-keygen useradd install; do
  command -v "$tool" >/dev/null || fail "Missing prerequisite: ${tool}"
done
key_text=$(cat -- "$1")
[[ ${key_text} != *$'\n'* && ${key_text} =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+\ [A-Za-z0-9._-]+$ ]] || fail 'Expected one ED25519 public key with a simple comment.'
ssh-keygen -lf "$1" >/dev/null || fail 'Invalid public key.'
sudo_rule='saad ALL=(ALL:ALL) NOPASSWD: ALL'
rule_file=$(mktemp /tmp/roombook-sudo.XXXXXX)
trap 'rm -f -- "${rule_file}"' EXIT
printf '%s\n' "${sudo_rule}" > "${rule_file}"
visudo -cf "${rule_file}" >/dev/null
if [[ -e /etc/sudoers.d/roombook-saad ]]; then
  [[ $(cat /etc/sudoers.d/roombook-saad) == "${sudo_rule}" ]] || fail 'An existing sudo rule differs; review it rather than replacing it.'
fi
if ! id saad >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash saad
fi
[[ $(getent passwd saad | cut -d: -f6) == /home/saad ]] || fail 'Existing saad account has a different home directory.'
[[ $(id -u saad) -ne 0 ]] || fail 'The saad account must not have UID 0.'
install -d -m 0700 -o saad -g "$(id -gn saad)" /home/saad/.ssh
touch /home/saad/.ssh/authorized_keys
chown saad:"$(id -gn saad)" /home/saad/.ssh/authorized_keys
chmod 0600 /home/saad/.ssh/authorized_keys
if ! grep -qxF -- "${key_text}" /home/saad/.ssh/authorized_keys; then
  printf '\n%s\n' "${key_text}" >> /home/saad/.ssh/authorized_keys
fi
install -m 0440 "${rule_file}" /etc/sudoers.d/roombook-saad
printf '%s\n' 'Saad administrator key installed. Root/password SSH settings are unchanged. Verify key access before hardening SSH.'
