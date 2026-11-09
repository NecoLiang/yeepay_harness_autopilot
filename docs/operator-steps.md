# 操作员步骤（只有你本人能做，约 20 分钟）

本机已经完成：安装 gh、lark-cli、dsh 0.2.1-rc.3；构建 dsh-superagent，创建 `superagent` 配置并启动（面板 http://127.0.0.1:3082）；生成 `gh-agent` 和 `lark-bot` 两个 CLI 包装；把 yeeHarness 的技能和团队提示词写入 superagent。

下面这些步骤涉及注册账号或输入密钥，只能由你本人完成。**密钥不要粘贴到 AI 对话里**，所有命令都在你自己的终端里执行。

## 1. GitHub agent 账号（约 5 分钟）

1. 用一个新邮箱注册 GitHub 账号，例如 `yeeharness-bot`，作为 AI 成员的身份。不要用你自己的账号：它发出的每条评论、开的每个 PR 都会署这个名字。
2. 终端执行，**登录时选这个新账号**：

   ```sh
   ~/.local/bin/gh-agent auth login        # GitHub.com → HTTPS → Login with a web browser
   ~/.local/bin/gh-agent api user --jq .login   # 应打印 agent 账号名
   ```

## 2. 飞书机器人（约 10 分钟）

1. 打开 [飞书开放平台](https://open.feishu.cn/app)，创建企业自建应用，例如「yeeHarness 助手」，并添加「机器人」能力。
2. 在权限管理中开通：接收群聊中@机器人消息、读取与发送单聊和群组消息、获取群组信息、获取群成员。在事件订阅中选择「长连接」，并添加「接收消息 v2.0」事件。
3. 创建版本并发布（企业内可见即可）。
4. 新建飞书群，例如「yeeHarness Autopilot 演示群」，把机器人拉进群。
5. 终端执行，App Secret 从标准输入粘贴，不会留在命令历史里：

   ```sh
   LARKSUITE_CLI_CONFIG_DIR="$HOME/.lark-cli-dsh-superagent" lark-cli config init --app-id <cli_xxx> --app-secret-stdin
   LARKSUITE_CLI_CONFIG_DIR="$HOME/.lark-cli-dsh-superagent" lark-cli config strict-mode bot --global
   ~/.local/bin/lark-bot auth status        # bot 一项应为 ready
   ```

## 3. 模型 API Key（约 2 分钟）

在 [DeepSeek 开放平台](https://platform.deepseek.com/api_keys) 创建 API Key，然后任选一种方式配置：

- 面板：打开 superagent 启动日志里的地址（带 token），在 Settings → Models 里填入；或者
- 环境变量：在 `~/.zshrc` 里 `export DEEPSEEK_API_KEY=...`，再重启：`cd ~/src/dsh-superagent && scripts/dsh-superagent restart`

> 演示仓库是脱敏代码，可以使用 DeepSeek 官方 API。接入真实业务仓库前，必须换成内部部署的模型（P-007）。

## 4. 一条命令上线

```sh
cd ~/yeeharness-autopilot && scripts/go_live.sh --chat "yeeHarness Autopilot 演示群"
```

它会依次完成：
1. 检查两个账号
2. 用 agent 账号把 `demo/payment-demo` 发布为公开仓库
3. 克隆工单检出目录
4. 查找飞书群 id
5. 写入来源、准入策略（群成员都可以提需求）、执行器和提示词
6. 做健康检查

输出「✓ 就绪」后，按 [demo-script.md](demo-script.md) 开始演示。

## 常见问题

| 现象 | 处理 |
|---|---|
| `status` 退出码 3 | 运行 `cd ~/src/dsh-superagent && scripts/dsh-superagent status`，按 `setup.detail` 的提示处理，再回到第 4 步 |
| 找不到飞书群 | 确认机器人已经在群里；或者把 chat id 写进 `autopilot.config.json` 后运行 `scripts/apply_settings.py` |
| 机器人不回话 | 面板 Overview 里看 Trigger 是否进来、是否被准入名单过滤；准入名单来自群成员同步 |
