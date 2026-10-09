#!/usr/bin/env bash
# Paste into AWS CloudShell (console bottom-left). Creates the Friday server in Mumbai. Safe to re-run.
set -euo pipefail
R=ap-south-1; N=friday-prod; K=friday-prod; IPN=friday-ip
L() { aws lightsail --region $R "$@"; }
cat > /tmp/launch.sh <<'LAUNCH'
#!/bin/bash
# Friday: Lightsail "launch script" (Ubuntu 24.04). Paste this whole file into the
# "Add launch script" box when you create the instance (Lightsail > Create instance).
# It runs once, as root, at first boot. It contains NO secrets and does NOT download Friday itself
# (follow docs/DEPLOY_AWS.md step 7 afterwards).
# Log: /var/log/friday-bootstrap.log   Done marker: /var/log/friday-bootstrap.done
set -euxo pipefail
exec > >(tee -a /var/log/friday-bootstrap.log) 2>&1
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get -y upgrade
apt-get -y install git unzip curl ca-certificates python3 unattended-upgrades ufw openssl

timedatectl set-timezone Asia/Kolkata

# 2 GB swap so a busy moment (or the image build) cannot crash a small server
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Docker (official repository)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker ubuntu || true

# Folders: code in /opt/friday, root-only secrets folder /etc/friday
install -d -o ubuntu -g ubuntu /opt/friday
install -d -m 750 /etc/friday

# Second firewall layer (the Lightsail firewall is the main one). Only SSH, HTTP, HTTPS.
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

# Automatic security updates
dpkg-reconfigure -f noninteractive unattended-upgrades || true

date -u +"bootstrap finished %Y-%m-%dT%H:%M:%SZ" > /var/log/friday-bootstrap.done
LAUNCH
L get-key-pair --key-pair-name $K >/dev/null 2>&1 || { L create-key-pair --key-pair-name $K --query privateKeyBase64 --output text > ~/$K.pem; chmod 600 ~/$K.pem; echo "key saved in CloudShell: ~/$K.pem"; }
L get-instance --instance-name $N >/dev/null 2>&1 || L create-instances --instance-names $N --availability-zone ${R}a --blueprint-id ubuntu_24_04 --bundle-id medium_3_0 --key-pair-name $K --user-data file:///tmp/launch.sh --add-ons 'addOnType=AutoSnapshot,autoSnapshotAddOnRequest={snapshotTimeOfDay=22:00}' >/dev/null
for _ in $(seq 1 60); do
  [ "$(L get-instance-state --instance-name $N --query state.name --output text 2>/dev/null)" = running ] && break
  sleep 5
done
[ "$(L get-instance-state --instance-name $N --query state.name --output text 2>/dev/null)" = running ] || { echo "The server did not reach 'running'. Open Lightsail in Mumbai and check, or send me the last lines above."; exit 1; }
L get-static-ip --static-ip-name $IPN >/dev/null 2>&1 || L allocate-static-ip --static-ip-name $IPN >/dev/null
L attach-static-ip --static-ip-name $IPN --instance-name $N >/dev/null 2>&1 || true
L put-instance-public-ports --instance-name $N --port-infos fromPort=22,toPort=22,protocol=tcp fromPort=80,toPort=80,protocol=tcp fromPort=443,toPort=443,protocol=tcp fromPort=443,toPort=443,protocol=udp >/dev/null
echo "DONE. Static IP: $(L get-static-ip --static-ip-name $IPN --query staticIp.ipAddress --output text)"
