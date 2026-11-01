#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${TARGET:-/opt/grayco/ha-dev/config/custom_components/reorder}"
python3 -m compileall -q "$ROOT/custom_components/reorder"
python3 -m json.tool "$ROOT/custom_components/reorder/strings.json" >/dev/null
python3 -m json.tool "$ROOT/custom_components/reorder/translations/en.json" >/dev/null
mkdir -p "$TARGET"
rsync -rvc --delete --exclude='__pycache__/' --exclude='*.pyc' \
  "$ROOT/custom_components/reorder/" "$TARGET/"
echo "Source deployed. Restart: cd /opt/grayco/ha-dev && docker compose restart homeassistant-dev"
