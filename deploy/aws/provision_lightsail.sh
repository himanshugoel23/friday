#!/usr/bin/env bash
# Create the Friday beta server on AWS Lightsail (Mumbai) from the command line.
# Needs the AWS CLI and credentials in the environment (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY),
# ideally an IAM user restricted by deploy/aws/lightsail-iam-policy.json. Idempotent: re-running
# skips what already exists. Creates: key pair, instance (with deploy/lightsail-launch.sh as the
# first-boot script), static IP, firewall (SSH 22, HTTP 80, HTTPS 443 only).
# Usage: deploy/aws/provision_lightsail.sh [--ssh-cidr 1.2.3.4/32]
#   (default SSH rule is open to the world because a phone/shared IP is not stable; tighten it
#    with --ssh-cidr when you can. Key-only SSH, no passwords.)
set -euo pipefail
cd "$(dirname "$0")/../.."
REGION="${AWS_REGION:-ap-south-1}"
AZ="${REGION}a"
NAME="${FRIDAY_INSTANCE_NAME:-friday-prod}"
KEY="${FRIDAY_KEY_NAME:-friday-prod}"
IP_NAME="${FRIDAY_IP_NAME:-friday-ip}"
BUNDLE="${FRIDAY_BUNDLE:-medium_3_0}"        # 4 GB RAM / 2 vCPU / 80 GB (check: aws lightsail get-bundles)
BLUEPRINT="ubuntu_24_04"
OUT="${FRIDAY_OUT_DIR:-$HOME/.friday-aws}"
SSH_CIDR="0.0.0.0/0"
[[ "${1:-}" == "--ssh-cidr" ]] && SSH_CIDR="${2:?cidr}"
L() { aws lightsail --region "$REGION" "$@"; }

L get-regions >/dev/null || { echo "AWS credentials missing or not allowed for Lightsail" >&2; exit 1; }
echo "bundle check:"; L get-bundles --query "bundles[?bundleId=='$BUNDLE'].[bundleId,ramSizeInGb,cpuCount,diskSizeInGb,price]" --output text

mkdir -p "$OUT"; chmod 700 "$OUT"
if ! L get-key-pair --key-pair-name "$KEY" >/dev/null 2>&1; then
  L create-key-pair --key-pair-name "$KEY" --query privateKeyBase64 --output text > "$OUT/$KEY.pem"
  chmod 600 "$OUT/$KEY.pem"; echo "key pair created: $OUT/$KEY.pem (keep it private)"
fi

if ! L get-instance --instance-name "$NAME" >/dev/null 2>&1; then
  L create-instances --instance-names "$NAME" --availability-zone "$AZ" --blueprint-id "$BLUEPRINT" \
    --bundle-id "$BUNDLE" --key-pair-name "$KEY" --user-data "file://deploy/lightsail-launch.sh" \
    --add-ons addOnType=AutoSnapshot,autoSnapshotAddOnRequest={snapshotTimeOfDay=21:30} >/dev/null
  echo "instance $NAME requested (snapshot time 21:30 UTC = 03:00 IST)"
fi
until [[ "$(L get-instance-state --instance-name "$NAME" --query state.name --output text 2>/dev/null)" == "running" ]]; do sleep 5; done

L get-static-ip --static-ip-name "$IP_NAME" >/dev/null 2>&1 || L allocate-static-ip --static-ip-name "$IP_NAME" >/dev/null
L attach-static-ip --static-ip-name "$IP_NAME" --instance-name "$NAME" >/dev/null 2>&1 || true

L put-instance-public-ports --instance-name "$NAME" --port-infos \
  "fromPort=22,toPort=22,protocol=tcp,cidrs=$SSH_CIDR" \
  "fromPort=80,toPort=80,protocol=tcp" \
  "fromPort=443,toPort=443,protocol=tcp" \
  "fromPort=443,toPort=443,protocol=udp" >/dev/null

IP="$(L get-static-ip --static-ip-name "$IP_NAME" --query staticIp.ipAddress --output text)"
echo "DONE. Server: $NAME  static IP: $IP  region: $REGION"
echo "Next: point an A record for your domain at $IP, then deploy (docs/DEPLOY_AWS.md step 7 onward)."
