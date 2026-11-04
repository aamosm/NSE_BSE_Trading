#!/bin/sh
# One-time, idempotent server preparation for Ubuntu 24.04 LTS. Run as root:  sh provision.sh
# Does NOT install Tailscale, copy secrets, or open any inbound port except SSH (see docs/DEPLOYMENT.md).
set -eu

if [ "$(id -u)" -ne 0 ]; then echo "Run as root" >&2; exit 1; fi
. /etc/os-release
if [ "${ID:-}" != "ubuntu" ]; then echo "Tested on Ubuntu 24.04 only" >&2; exit 1; fi

# Refuse to disable password SSH unless a key is already installed (prevents locking yourself out).
if ! [ -s /root/.ssh/authorized_keys ]; then
  echo "No SSH key in /root/.ssh/authorized_keys; add your public key first (docs/DEPLOYMENT.md step 2)" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade
apt-get install -y python3 python3-venv git age rclone sqlite3 unattended-upgrades ufw ca-certificates curl
timedatectl set-timezone Asia/Kolkata

id marketlab >/dev/null 2>&1 || useradd --system --home-dir /var/lib/marketlab --shell /usr/sbin/nologin marketlab
install -d -o marketlab -g marketlab -m 700 /var/lib/marketlab /var/lib/marketlab/private \
  /var/lib/marketlab/market /var/lib/marketlab/backups /var/lib/marketlab/.config
install -d -o root -g root -m 755 /opt/marketlab /opt/marketlab/releases /etc/marketlab

# SSH: keys only, no root password login.
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/60-marketlab.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
systemctl reload ssh || systemctl reload sshd || true

# Firewall: SSH only. The app listens on 127.0.0.1 and is reached through Tailscale, never a public port.
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

# Automatic security updates.
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "Provisioned. Next: install Tailscale, then deploy/install_release.sh <commit> (docs/DEPLOYMENT.md)."
