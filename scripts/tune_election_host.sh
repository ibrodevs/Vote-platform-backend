#!/usr/bin/env bash
# Idempotent host tuning for the Hetzner CCX33 election-day profile.
# Run as root on the APPLICATION host, never on a load-generator machine.
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

CONF=/etc/sysctl.d/99-vote-platform-election.conf
STAMP=$(date +%Y%m%d-%H%M%S)

if [ -f "$CONF" ]; then
  cp -a "$CONF" "${CONF}.bak.${STAMP}"
fi

cat >"$CONF" <<'EOF'
# Vote Platform — Hetzner CCX33 election-day network profile
# No tcp_tw_reuse/TIME_WAIT tricks: correctness and predictable failure modes first.
fs.file-max = 1048576
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 10000 65535
vm.swappiness = 1
EOF

# conntrack exists on normal Docker hosts, but do not make the script fail on
# systems where the module is not loaded.
if sysctl -n net.netfilter.nf_conntrack_max >/dev/null 2>&1; then
  echo 'net.netfilter.nf_conntrack_max = 524288' >>"$CONF"
fi

sysctl --system >/dev/null

echo "Applied $CONF"
echo "Verification:"
sysctl net.core.somaxconn net.core.netdev_max_backlog \
  net.ipv4.tcp_max_syn_backlog net.ipv4.ip_local_port_range vm.swappiness
if sysctl -n net.netfilter.nf_conntrack_max >/dev/null 2>&1; then
  sysctl net.netfilter.nf_conntrack_max
fi

echo
printf 'Host open-file hard limit in this shell: '
ulimit -Hn
printf 'Host open-file soft limit in this shell: '
ulimit -Sn

echo "Docker container nofile limits are configured separately in docker-compose.prod.yml."
