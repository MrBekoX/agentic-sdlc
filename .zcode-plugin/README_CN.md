# AGENTIC-SDLC（ZCode 实验性适配器）

> ZCode 是**适配器目标，不是 0.4.3 受支持的发布目标**。受支持的发布目标仍然是
> Claude Code 和 Codex（见仓库 `README.md` 与 `docs/runtime-adapter.md`）。本清单与
> Hook 接线仅用于本地 ZCode 安装的基础设施；不得将其引用为发布支持。

AGENTIC-SDLC 将带门禁的规格/计划/TDD/安全/评审流程打包为 16 个技能、1 个手动命令和
确定性的守护 Hook。本目录是 ZCode 插件清单（`.zcode-plugin/plugin.json`）；共享的技能
源代码仍在仓库根目录 `skills/`（扁平的 `skills/<name>/SKILL.md` 布局，无分组文件夹）。

## 本地安装

1. 打开 ZCode **Settings → Plugins**，**Discover** 标签页，点击 **+**
   （**Create → Add marketplace**）。
2. 将本仓库根目录（包含 ZCode marketplace 模式文件 `marketplace.json` 的文件夹）作为
   本地目录或文件源添加。ZCode 会在添加前进行校验。
3. 在 **Personal** 分区找到 `agentic-sdlc` 卡片（名称、版本、类别 `developer-tools`），
   点击 **Install**，然后 **Enable**。
4. 开启新会话（或重新加载），使技能、命令与 Hook 被发现。

前提条件：`node` 必须在 `PATH` 上——每个 Hook 执行器都是通过 argv 运行
`node <script>`。

## 使用方式

- 在聊天输入框输入 `$using-agentic-sdlc`（或打开 `/` → Skills）调用路由器。路由器会
  选择最小充分的技能；仅完整的 SDLC 信封才使用 `agentic-sdlc-pipeline`。
- 手动命令 `git-safety-check` 从 `commands/` 发现（命令名来自文件名）。
- `agents/` 下的子代理带有 ZCode 要求的 `name` + `description` frontmatter。

## 信任与副作用

启用本插件即等同于允许其 Hook 运行代码。已接线的 Hook（`hooks/hooks-zcode.json`）在
以下已验证的事件与工具上执行 `node` 脚本：

| 事件 | 匹配器 | 处理器 |
|---|---|---|
| `PreToolUse` | `Bash` | `scan-commit.mjs`、`destructive-command-guard.mjs`、`branch-guard.mjs` |
| `PostToolUse` | `Write\|Edit` | `scan-write.mjs` |
| `SessionStart` | `startup\|clear\|compact` | `session-start.mjs` |

副作用：守护脚本读取 Hook stdin JSON（`tool_input.command`、`tool_input` 写入字段、
`cwd`）与本地 `git` 状态。拒绝操作使用已文档的 `hookSpecificOutput.permissionDecision`
字段，SessionStart 引导使用已文档的 `additionalContext` 字段；建议消息所用的
`systemMessage` 通道是 Claude Code 的约定，ZCode 是否显示它尚未验证。**没有网络访问**
（未声明任何 MCP 服务器），数据不会离开本机。长期可写数据应放在 `ZCODE_PLUGIN_DATA`
下，而不是安装目录。

ZCode 上未接线（已记录的缺口，见 `docs/runtime-adapter.md`）：Stop 完成/流程守护
（它们读取 Claude transcript / Codex rollout）、flow-order 守护、工作区 Stop 扫描，
以及上述建议消息通道。Claude 与 Codex 的 Hook 文件（`hooks-claude.json`、
`hooks-codex.json`）不与 ZCode 共享。

## 编排回退

ZCode 在客户端 3.14.0 中新增了动态工作流（官方更新日志，2026-09-19），可从输入框加号
菜单或 `/workflow` 启动。但 Z.ai 尚未公开其脚本 API、文件格式或存储路径，且 `plugin.json`
没有 `workflows` 组件键——因此**本插件无法为你分发工作流**。Claude Code 会运行
`spec-plan-draft` 工作流、Codex 使用其内嵌适配器的地方，ZCode 会话在主循环中以相同的
**作者 → 评审 → 修订**纪律运行，并保存工件和 `scripts/validate_artifacts.py` 证据。
保留在 `workflows/zcode/spec-plan-draft.dwf.ts` 的移植版尚未验证，仅作为实机运行的起点，
不是受支持的路径。

## 版本

`.zcode-plugin/plugin.json` 与根目录 `marketplace.json` 条目中的 `version` 由
`tests/test_zcode_packaging.py` 锁定到 `VERSION`。`scripts/bump_version.py` 尚未跟踪
这两个 ZCode 文件——版本升级必须手动更新它们，否则本地门禁会失败。

## 官方市场提交

未提交，也未声称已提交。未来 `zai-org/zcode-plugins` PR 仍需补齐的内容见
`docs/publication/zcode-marketplace.md`。
