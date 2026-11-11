# 操作员步骤（只有你本人能做，约 15 分钟）

不需要安装 dsh，也不需要 DeepSeek Key。执行引擎就是本机已登录的 Claude Code，yeeHarness 技能已经装在 `~/.claude/skills`。

本机已完成：gh、lark-cli 已安装；`gh-agent` 和 `lark-bot` 两个 CLI 包装已生成（`scripts/install_wrappers.sh`）。

下面的步骤涉及注册账号或输入密钥，只能由你本人完成。**密钥不要粘贴到 AI 对话里**，所有命令都在你自己的终端里执行。

## 1. GitHub agent 账号（约 5 分钟）

> 也可以直接用你自己的账号：把 `~/.local/bin/gh-agent` 的内容改成 `exec gh "$@"`，PR 就会署你的名字。本次演示用的就是这种方式（NecoLiang）。

1. 用一个新邮箱注册 GitHub 账号，例如 `yeeharness-bot`。PR 和提交都会署这个名字，所以不要用你自己的账号。
2. 终端执行，**登录时选这个新账号**：

   ```sh
   ~/.local/bin/gh-agent auth login            # GitHub.com → HTTPS → Login with a web browser
   ~/.local/bin/gh-agent api user --jq .login  # 应打印 agent 账号名
   ```

## 2. 飞书机器人（约 10 分钟）

1. 打开 [飞书开放平台](https://open.feishu.cn/app)，创建企业自建应用，例如「yeeHarness 助手」，并添加「机器人」能力。
2. 在权限管理中开通：接收群聊中@机器人消息、读取与发送单聊和群组消息、获取群组信息、获取群成员。在事件订阅中选择「长连接」，并添加「接收消息 v2.0」（im.message.receive_v1）。
3. 创建版本并发布。新建一个飞书群，例如「yeeHarness Autopilot 演示群」，把机器人拉进群。
4. 终端执行，App Secret 从标准输入粘贴：

   ```sh
   LARKSUITE_CLI_CONFIG_DIR="$HOME/.lark-cli-dsh-superagent" lark-cli config init --app-id <cli_xxx> --app-secret-stdin
   LARKSUITE_CLI_CONFIG_DIR="$HOME/.lark-cli-dsh-superagent" lark-cli config strict-mode bot --global
   ~/.local/bin/lark-bot auth status            # bot 一项应为 ready
   ```

## 3. 上线

```sh
cd ~/yeeharness-autopilot
scripts/go_live.sh --chat "yeeHarness Autopilot 演示群"   # 发布演示仓库、查找群、写配置
.venv/bin/python -m autopilot serve                       # 开始监听（建议在 tmux 里跑）
```

群成员都可以提需求（准入名单启动时从群成员同步）。在群里 @机器人 即可开始，演示流程见 [demo-script.md](demo-script.md)。

## 不想配飞书时：本地模式

本地模式和飞书走的是同一条流水线，只是回复打印在终端里，不会发到飞书：

```sh
.venv/bin/python -m autopilot --config autopilot.local.json ask "<需求>"
.venv/bin/python -m autopilot --config autopilot.local.json reply <工单号> "A"
.venv/bin/python -m autopilot --config autopilot.local.json status
```

## 常见问题

| 现象 | 处理 |
|---|---|
| 机器人不回话 | 看 `serve` 的日志：每条消息都会打印 `new / followup / ignore` 及原因（比如不在准入名单、没有 @机器人） |
| 工单状态为 failed | 运行 `python -m autopilot status` 查看；详细错误在 `~/.yeeharness-autopilot/autopilot.sqlite` 的 event 表 |
| Claude 权限被拒 | 在配置里调整 `allowedTools`。推送、gh、lark-cli 始终禁止 Claude 调用，由编排器负责 |
