#!/bin/bash
# Friday: first-boot server script (Ubuntu 24.04; Lightsail, DigitalOcean, Vultr, any VPS). Paste this whole file into the
# "Add launch script" box when you create the instance (Lightsail > Create instance).
# It runs once, as root, at first boot. It contains NO secrets and does NOT download Friday itself
# (the repository is private; follow docs/DEPLOY_AWS.md step 7 afterwards).
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

# Non-AWS providers (DigitalOcean, Vultr...) log in as root and have no 'ubuntu' user: create it
id ubuntu >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo ubuntu

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
