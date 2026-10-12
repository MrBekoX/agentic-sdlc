# AGENTIC-SDLC（ZCode 实验性适配器）

> ZCode 是**适配器目标，不是 0.4.3 受支持的发布目标**。受支持的发布目标仍然是
> Claude Code 和 Codex（见仓库 `README.md` 与 `docs/runtime-adapter.md`）。本清单与
> Hook 接线是 ZCode marketplace 安装（以文件源添加根目录的 `marketplace.json`，或以本地
> 目录或 GitHub 添加本仓库）的基础设施，并不构成发布支持。

AGENTIC-SDLC 将带门禁的规格/计划/TDD/安全/评审流程打包为 16 个技能、1 个手动命令和
确定性的守护 Hook。本目录是 ZCode 插件清单（`.zcode-plugin/plugin.json`）；共享的技能
源代码仍在仓库根目录 `skills/`（扁平的 `skills/<name>/SKILL.md` 布局，无分组文件夹）。

## 安装

获取软件包：文件源是包目录中根目录下的 `marketplace.json`，包目录即本仓库文件的解压副本。
可以克隆仓库，或下载并解压其源码 ZIP 或发布归档（维护者使用
`python3 scripts/build_release.py --output agentic-sdlc.zip` 构建；GitHub Releases 尚未发布）。
目录内的文件无需编辑。ZCode 桌面版提供 Windows（x64/ARM64）、macOS（Apple Silicon/Intel
DMG）和 Linux（x64 AppImage）版本。

1. 打开 ZCode **Settings → Plugins**，**Discover** 标签页，点击 **+**
   （**Create → Add marketplace**）。
2. 将根目录的 `marketplace.json`（ZCode marketplace 模式）**作为文件源**添加。若以目录或
   GitHub 源添加，ZCode 会先读取 `.claude-plugin/marketplace.json`，虽然仍可安装插件，但显示的是
   Claude 条目，没有 ZCode 的类别、标签与翻译。ZCode 会在添加前进行校验。
3. 请先查看下方「信任与副作用」中的 Hook 表：新安装的插件**默认即启用**，其 Hook 会立即
   运行。在 **Personal** 分区找到 `agentic-sdlc` 卡片（名称、版本、类别 `developer-tools`），
   点击 **Install**。只有在停用后才需要在「Manage installed」中再次点击 **Enable**。
4. 开启新会话（或重新加载），使技能、命令与 Hook 被发现。

没有本地包目录时，在第 2 步改为将 GitHub 仓库 `MrBekoX/agentic-sdlc`（或其 URL）添加为
marketplace 源。仓库自 2026-10-12 起已公开；该方式尚未经过原生验证。厂商插件页面将
GitHub 仓库列为 marketplace 源（2026-10-08 核对）。如第 2 步所述，ZCode 会先通过
`.claude-plugin/marketplace.json` 读取该源：插件以 Claude 条目安装，没有 ZCode 的类别、
标签与翻译。

前提条件：`node` 必须在 `PATH` 上——每个 Hook 执行器都是通过 argv 运行
`node <script>`。辅助工作流还需要 Python 3（已测试 3.12；技能运行的辅助脚本经静态检查
保持与 3.8 的导入兼容）和 Git；在 Windows 上，若 `python3` 缺失或是 Microsoft Store 别名，
请使用 `py -3`。在 macOS 上，从 Finder 或 Dock 启动的图形界面应用可能不会继承 shell 的
`PATH`；若 ZCode 找不到 `node`，Hook 会以放行方式失败（fail open），守护脚本将静默失效。
请确认 ZCode 应用本身（而不只是终端）能找到 `node`（此处未验证）。

## 使用方式

- 在聊天输入框输入 `$using-agentic-sdlc`（或打开 `/` → Skills）调用路由器。路由器会
  选择最小充分的技能；仅完整的 SDLC 信封才使用 `agentic-sdlc-pipeline`。
- Hook 进程会收到 `${ZCODE_PLUGIN_ROOT}` 及 `${CLAUDE_PLUGIN_ROOT}` 别名；技能正文中只会替换
  `${CLAUDE_SKILL_DIR}` / `${ZCODE_SKILL_DIR}`，因此技能通过各自的 **Plugin root** 规则
  （`${CLAUDE_SKILL_DIR}/../..`）或 SessionStart Hook 打印的插件根目录来定位脚本。
- 手动命令 `git-safety-check` 从 `commands/` 发现（命令名来自文件名）。
- `agents/` 下的子代理带有 ZCode 要求的 `name` + `description` frontmatter。

## 信任与副作用

启用本插件即等同于允许其 Hook 运行代码。已接线的 Hook（`hooks/hooks-zcode.json`）在
以下已验证的事件与工具上执行 `node` 脚本：

| 事件 | 匹配器 | 处理器 |
|---|---|---|
| `PreToolUse` | `Bash` | `scan-commit.mjs`、`destructive-command-guard.mjs`、`branch-guard.mjs` |
| `PostToolUse` | `Write\|Edit` | `scan-write.mjs` |
| `SessionStart` | `startup\|resume\|clear\|compact` | `session-start.mjs` |

副作用：守护脚本读取 Hook stdin JSON（`tool_input.command`、`tool_input` 写入字段、
`cwd`）与本地 `git` 状态。拒绝操作使用已文档的 `hookSpecificOutput.permissionDecision`
字段，SessionStart 引导使用已文档的 `additionalContext` 字段。写入扫描器的建议以
`hookSpecificOutput.additionalContext` 送达模型。脚本以两种已文档的方式识别 ZCode ——
wire 传入字面量 `--zcode-runtime` argv 参数，且 ZCode 会把 `ZCODE_PLUGIN_ROOT` 作为环境
变量注入 —— 在该模式下只输出已文档的键（`hooks/hook-output.mjs`）：警告移入
`hookSpecificOutput.additionalContext`，绝不写出顶层的 `systemMessage` 建议通道（Claude
Code 的约定）。在线 Hook 文档称 ZCode 会忽略未知字段，而内置的 `diagnosing-hooks` 技能称
任何多余的键都会使运行失败并丢弃其效果；两种读法下输出都安全。原生显示与调用尚未验证。
**没有网络访问**
（未声明任何 MCP 服务器），数据不会离开本机。长期可写数据应放在 `ZCODE_PLUGIN_DATA`
下，而不是安装目录。

ZCode 上未接线（已记录的缺口，见 `docs/runtime-adapter.md`）：Stop 完成/流程守护
（它们读取 Claude transcript / Codex rollout）、flow-order 守护与工作区 Stop 扫描。
Claude 与 Codex 的 Hook 文件（`hooks-claude.json`、`hooks-codex.json`）不与 ZCode 共享。

## 编排回退

ZCode 在客户端 3.14.0 中新增了动态工作流（官方更新日志，2026-09-19），可从输入框加号
菜单或 `/workflow` 启动。开源客户端把已保存的工作流存放在项目的 `.zcode/workflows/` 或用户的
`~/.zcode/workflows/` 目录中，但 `plugin.json` 没有 `workflows` 组件键——因此**本插件无法为你
分发工作流**。Claude Code 会运行
`spec-plan-draft` 工作流、Codex 使用其内嵌适配器的地方，ZCode 会话在主循环中以相同的
**作者 → 评审 → 修订**纪律运行，并保存工件和 `scripts/validate_artifacts.py` 证据。
保留在 `workflows/zcode/spec-plan-draft.dwf.ts` 的移植版尚未验证，仅作为实机运行的起点，
不是受支持的路径。

## 版本

`.zcode-plugin/plugin.json` 与根目录 `marketplace.json` 条目中的 `version` 由
`scripts/bump_version.py` 统一维护，`tests/test_zcode_packaging.py` 检查二者与 `VERSION` 一致。
只有版本号变化时，ZCode 才会提供更新：刷新 marketplace，然后在
「Manage installed → Check for updates」中应用更新，并开启新会话。当前范围与发布要求见
[分发准备](../docs/publication/multi-platform-distribution.md)。

## 卸载

打开「Settings → Plugins → Manage installed」，进入插件详情后点击 **Uninstall**；ZCode
会先请求确认，再移除插件。现有厂商文档未说明持久数据是否保留，因此不要假定卸载会删除
这些数据。请使用原生界面，并保留其他插件与设置。详见
[生命周期指南](../docs/publication/multi-platform-distribution.md)。

## 原生验证证据

已签名的 ZCode 桌面版 3.14.5 所附带的 agent CLI 0.16.9 于 2026-10-12 在隔离环境中通过了
原生的校验、以由根目录 `marketplace.json` 派生的目录添加 marketplace（目录源，而非图形界面的文件源步骤）、安装（已启用，16 个技能、5 个
Hook 声明）、版本递增后的更新以及经确认的卸载：Windows（E9）、Linux x64 AppImage（E15）
与 macOS Apple Silicon DMG（E14），见[兼容性矩阵](../docs/publication/compatibility-matrix.md)。
该 CLI 只在 Electron 的 Node 模式下管理插件，这不是文档化的用户路径，因此上述证据只验证了
附带的插件管理器；桌面 GUI 流程、GitHub 源、实际的 Hook 投递与模型行为仍未验证。更早的
准备证据见 [marketplace 就绪记录](../docs/publication/marketplace-readiness-2026-10-11.md)。

## 官方市场提交

未提交，也未声称已提交。未来 `zai-org/zcode-plugins` PR 仍需补齐的内容见
`docs/publication/zcode-marketplace.md`。

## 许可与致谢

采用 MIT 许可，见 [LICENSE](../LICENSE)。[obra/superpowers](https://github.com/obra/superpowers)
（同样采用 MIT 许可）影响了部分技能流程的设计；详见
[仓库 README](../README.md#related-work-and-acknowledgements)。
