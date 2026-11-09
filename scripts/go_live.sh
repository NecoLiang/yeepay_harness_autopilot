#!/usr/bin/env bash
# One command from "operator steps done" to "send a request in Feishu".
#   scripts/go_live.sh --chat "<飞书群名>"      # look up the chat, publish the demo repo, configure everything
# Re-runnable: every step checks what already exists.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUPERAGENT="${DSH_SUPERAGENT_HOME:-$HOME/src/dsh-superagent}"
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

step "1/6 检查账号"
AGENT_LOGIN="$("$GH_AGENT" api user --jq .login 2>/dev/null)" || fail "gh-agent 未登录：运行 $GH_AGENT auth login（用 agent 账号）"
echo "agent GitHub 账号: $AGENT_LOGIN"
"$LARK_BOT" config strict-mode 2>/dev/null | grep -q "strict-mode: *bot" || fail "飞书机器人未配置为 bot 严格模式，见 docs/operator-steps.md 第 2 步"
echo "飞书机器人: 已配置"

step "2/6 准备演示仓库 $CHECKOUT（工单从这里建 worktree）"
[ -d "$CHECKOUT/.git" ] || bash "$ROOT/scripts/init_demo_repo.sh" "$CHECKOUT"

step "3/6 发布演示仓库 $AGENT_LOGIN/payment-demo"
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

step "4/6 查找飞书群「$CHAT_NAME」"
CHAT_ID="$("$LARK_BOT" im +chat-list --page-all --format json 2>/dev/null | "$PY" -c '
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
[ -n "$CHAT_ID" ] || fail "没找到唯一名为「$CHAT_NAME」的群：确认机器人已加入该群，或把 chat id 直接写进 autopilot.config.json 后运行 scripts/apply_settings.py"
echo "chat id: $CHAT_ID"

step "5/6 生成配置并写入 dsh-superagent"
"$PY" - "$ROOT/autopilot.config.json" "$AGENT_LOGIN" "$CHAT_ID" "$CHAT_NAME" "$CHECKOUT" <<'PYEOF'
import json, sys
out, login, chat_id, chat_name, checkout = sys.argv[1:]
config = {"port": 3082, "repository": f"{login}/payment-demo", "githubCli": "~/.local/bin/gh-agent",
          "feishuCli": "~/.local/bin/lark-bot", "chats": [{"chatId": chat_id, "name": chat_name, "listen": "mentions"}],
          "syncChat": chat_id, "feishuAllowed": [], "checkout": checkout, "maxWorkers": 2}
open(out, "w", encoding="utf-8").write(json.dumps(config, ensure_ascii=False, indent=2))
print("wrote", out)
PYEOF
"$PY" "$ROOT/scripts/build_skills.py"
"$PY" "$ROOT/scripts/apply_settings.py" --config "$ROOT/autopilot.config.json"

step "6/6 健康检查"
(cd "$SUPERAGENT" && scripts/dsh-superagent status) && echo "✓ 就绪：在飞书群「$CHAT_NAME」里 @机器人 提需求即可"
