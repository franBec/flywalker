#!/bin/bash
# flywalker VM startup script. Idempotent: safe on every boot (spot VMs restart
# through this script after preemption recovery).

set -euo pipefail

REPO_URL="$(gcloud compute instances describe flywalker \
  --zone="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ '{print $NF}')" \
  --format='value(metadata.flywalker-repo-url)' 2>/dev/null || true)"
REPO_REF="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/flywalker-repo-ref || true)"
FLY_BRAIN="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/flywalker-fly-brain || echo real)"
MAPILLARY_TOKEN="$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/attributes/mapillary-token || true)"

# Fallback repo location if describe failed (e.g. first boot ordering)
REPO_URL="${REPO_URL:-https://github.com/franBec/flywalker.git}"
REPO_REF="${REPO_REF:-main}"

# --- docker (official convenience script; idempotent) ---
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi

# --- small swap (the kernel can spike past 12GB briefly; 16GB alone is tight) ---
if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- clone / update repo ---
mkdir -p /opt/flywalker
if [ ! -d /opt/flywalker/.git ]; then
  git clone "$REPO_URL" /opt/flywalker
fi
git -C /opt/flywalker fetch origin
git -C /opt/flywalker checkout "$REPO_REF"
git -C /opt/flywalker pull --ff-only origin "$REPO_REF" || true

# --- write .env from metadata (never committed to the repo) ---
cat > /opt/flywalker/.env <<EOF
MAPILLARY_TOKEN=${MAPILLARY_TOKEN}
FLY_BRAIN=${FLY_BRAIN}
ORACLE_URL=http://oracle:8000
ARRIVAL_RADIUS_M=25
MAX_STEPS=1200
THINK_MS=500
DATA_DIR=/data
ROUTE_BBOX=38.7055,-9.1470,38.7235,-9.1345
ROUTE_START=38.7139,-9.1394
ROUTE_GOAL=38.7219,-9.1447
EOF
chmod 600 /opt/flywalker/.env

# --- bring the stack up (oracle waits for its prepare job; walker waits for oracle) ---
cd /opt/flywalker
docker compose up -d --build

echo "flywalker startup complete: $(date)" >> /var/log/flywalker-startup.log
