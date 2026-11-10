#!/usr/bin/env bash
# From "operator steps done" to "listening in Feishu", in one command:
#   scripts/go_live.sh --chat "<飞书群名>"
# Re-runnable: every step checks what already exists.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKOUT="${YH_CHECKOUT:-$HOME/src/payment-demo}"
GH_AGENT="$HOME/.local/bin/gh-agent"
LARK_BOT="$HOME/.local/bin/lark-bot"
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY=python3
CHAT_NAME=""

while [ $# -gt 0 ]; do
  case "$1" in
    --chat) CHAT_NAME="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$CHAT_NAME" ] || { echo "usage: $0 --chat <飞书群名>" >&2; exit 2; }

step() { printf '\n== %s\n' "$*"; }
fail() { printf '✗ %s\n' "$*" >&2; exit 1; }

step "1/5 检查 Claude Code 与账号"
command -v claude >/dev/null || fail "未找到 claude 命令"
AGENT_LOGIN="$("$GH_AGENT" api user --jq .login 2>/dev/null)" || fail "gh-agent 未登录：运行 $GH_AGENT auth login（用 agent 账号）"
AGENT_ID="$("$GH_AGENT" api user --jq .id)"
"$LARK_BOT" config strict-mode 2>/dev/null | grep -q "strict-mode: *bot" || fail "飞书机器人未配置为 bot 严格模式，见 docs/operator-steps.md"
echo "claude: $(claude --version)  agent: $AGENT_LOGIN  飞书机器人: 已配置"

step "2/5 准备演示仓库 $CHECKOUT"
[ -d "$CHECKOUT/.git" ] || bash "$ROOT/scripts/init_demo_repo.sh" "$CHECKOUT"

step "3/5 发布演示仓库 $AGENT_LOGIN/payment-demo"
if "$GH_AGENT" repo view "$AGENT_LOGIN/payment-demo" >/dev/null 2>&1; then
  echo "已存在，跳过创建"
else
  "$GH_AGENT" repo create "$AGENT_LOGIN/payment-demo" --public \
     --description "yeeHarness Autopilot demo: payment split-settlement service"
fi
git -C "$CHECKOUT" remote get-url origin >/dev/null 2>&1 || \
  git -C "$CHECKOUT" remote add origin "https://github.com/$AGENT_LOGIN/payment-demo.git"
# Push as the agent account only, never with the operator's stored git credentials.
git -C "$CHECKOUT" -c credential.helper= -c "credential.helper=!$GH_AGENT auth git-credential" push -u origin main

step "4/5 查找飞书群「$CHAT_NAME」"
CHAT_ID="$("$LARK_BOT" im +chat-list --page-all --format json --as bot 2>/dev/null | "$PY" -c '
import json, sys
def chats(node):
    if isinstance(node, dict):
        if "chat_id" in node and "name" in node:
            yield node
        for value in node.values():
            yield from chats(value)
    elif isinstance(node, list):
        for value in node:
            yield from chats(value)
text = sys.stdin.read()
data = json.loads(text[text.find("{"):] if "{" in text else "{}")
ids = sorted({c["chat_id"] for c in chats(data) if c.get("name") == sys.argv[1]})
print(ids[0] if len(ids) == 1 else "")' "$CHAT_NAME")" || true
[ -n "$CHAT_ID" ] || fail "没找到唯一名为「$CHAT_NAME」的群：确认机器人已在群里，或手工把 chat id 写进 autopilot.config.json"
echo "chat id: $CHAT_ID"

step "5/5 写配置"
"$PY" - "$ROOT/autopilot.config.json" "$CHECKOUT" "$CHAT_ID" "$AGENT_LOGIN" "$AGENT_ID" <<'PYEOF'
import json, sys
out, checkout, chat, login, agent_id = sys.argv[1:]
config = {"checkout": checkout, "commitName": login, "commitEmail": f"{agent_id}+{login}@users.noreply.github.com",
          "feishu": {"cli": "~/.local/bin/lark-bot", "chats": [chat], "syncChat": chat},
          "github": {"cli": "~/.local/bin/gh-agent", "repository": f"{login}/payment-demo"}}
open(out, "w", encoding="utf-8").write(json.dumps(config, ensure_ascii=False, indent=2))
print("wrote", out)
PYEOF
echo
echo "✓ 就绪。启动监听：cd $ROOT && $PY -m autopilot serve"
echo "  然后在飞书群「$CHAT_NAME」里 @机器人 提需求。"
