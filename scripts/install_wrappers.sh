#!/usr/bin/env bash
# Creates the two account wrappers dsh-superagent needs (docs/006-deployment.md › Accounts).
# They hold no secrets: each points a CLI at its own config directory, so the agent never uses
# the operator's personal GitHub or Feishu login. Safe to re-run.
set -euo pipefail

BIN="${HOME}/.local/bin"
mkdir -p "$BIN"

write_wrapper() {
  local path="$1" body="$2"
  if [ -f "$path" ] && [ "$(cat "$path")" != "$body" ]; then
    echo "refusing to overwrite $path: it exists with different content" >&2
    exit 1
  fi
  printf '%s\n' "$body" > "$path"
  chmod +x "$path"
  echo "ok  $path"
}

write_wrapper "$BIN/gh-agent" '#!/bin/sh
GH_CONFIG_DIR="$HOME/.config/gh-agent" exec gh "$@"'

write_wrapper "$BIN/lark-bot" '#!/bin/sh
export LARKSUITE_CLI_CONFIG_DIR="$HOME/.lark-cli-dsh-superagent"
exec lark-cli "$@"'

cat <<MSG

Next, in your own terminal (secrets never go through the chat):
  $BIN/gh-agent auth login            # sign in as the AGENT GitHub account, not your own
  LARKSUITE_CLI_CONFIG_DIR="\$HOME/.lark-cli-dsh-superagent" lark-cli config init --app-id <cli_xxx> --app-secret-stdin
  LARKSUITE_CLI_CONFIG_DIR="\$HOME/.lark-cli-dsh-superagent" lark-cli config strict-mode bot --global
MSG
