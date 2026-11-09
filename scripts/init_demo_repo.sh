#!/usr/bin/env bash
# Materializes demo/payment-demo as a standalone git repository at <dest> with one initial commit.
# The demo lives in this repository as plain files; the agent works on its own repository.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:?usage: init_demo_repo.sh <dest>}"
[ -e "$DEST" ] && { echo "$DEST already exists" >&2; exit 1; }
mkdir -p "$(dirname "$DEST")"
rsync -a --exclude target --exclude .git "$ROOT/demo/payment-demo/" "$DEST/"
cp "$ROOT/gate/yh_verify.py" "$DEST/.yeeharness/yh_verify.py"
git -C "$DEST" init -q -b main
git -C "$DEST" add -A
git -C "$DEST" -c user.name="yeeHarness Autopilot" -c user.email="autopilot@users.noreply.github.com" \
  commit -q -m "feat: payment split-settlement demo service"
echo "created $DEST ($(git -C "$DEST" rev-parse --short HEAD))"
