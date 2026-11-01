# Agent 规则（来源、落地与生效）

本仓库的 agent 规则从 EveJS 工作区（`M:\EVE-LOCAL\EveJS`）迁移并按 RMR 的技术栈重写，2026-11-01 一次落地。本文记录“现在有哪些规则文件、为什么这样改、怎么生效”。

## 落地文件

| 路径 | 作用 |
|---|---|
| `AGENTS.md` | 规则本体：worktree、提交、异常归档、功能记录、零售优先、验证、数据库、客户端重启、客户端代码、性能前提、目录、Shell、上下文效率 |
| `AGENTS-DETAIL.md` | 按需读取的详细操作：worktree 命令、Postgres 卷操作、异常正文模板、skill 规范 |
| `.opencode/plugins/session-id.js` | 把会话 id 注入 `$OPENCODE_SESSION_ID`，供分支命名使用 |
| `.opencode/skills/agent-context-efficient-reads/` | 大文件/大输出的上下文压缩策略 |
| `.opencode/skills/rmr-server-operations/` | 构建、启动、配置、排障 |
| `.opencode/skills/rmr-client-code/` | `compiled.code` 容器与本地化工具链 |
| `.opencode/skills/eve-online-university-wiki/` | 外部玩法资料查询（现代资料，取值仍需回到 3913） |
| `doc/` | 文档体系：`README.md`、`knowledge-inventory.md`、`issues/INDEX.md` 与各领域主题文档 |

## 保留的通用规则

以下规则与具体游戏无关，按原意保留：

- 每任务独立 worktree（`plus` 开发主线 / `main` 上游基线）、分支命名带 session id、完成后 `--no-ff` 合并并保留分支。
- 完成即自动提交；提交信息英文祈使句；不自动 push；不提交密钥/日志/临时产物。
- 异常归档（`doc/issues/` 一篇一异常 + 索引）。
- 功能修改必须有文档记录，写成“当前状态”。
- 零售版本优先、仔细验证、不写兼容层、破坏性变更先列受影响清单。
- 客户端在运行时禁止重启服务端。
- 性能分析默认「单机单用户、无客户端升级」前提。
- 工具使用与上下文效率（少往返、并行、子代理、定点读）。

## 按 RMR 技术栈改写的规则

| EveJS 原规则 | RMR 对应 |
|---|---|
| 客户端 build 3396210、`code.ccp`（ZIP + `.pyj`）、独立代码仓库 | 客户端 build 3913、`script\compiled.code`（pickle + marshal）、尚无代码仓库（缺口写在 `AGENTS.md`） |
| Docker 命名卷 `evejs-data`/`evejs-logs`、`gamestore.sqlite`/`market.sqlite` | PostgreSQL 16 命名卷 `pgdata`、`db/*.sql.gz` 首次初始化、`psql`/`pg_dump` 操作 |
| 客户端进程 `exefile.exe`、`tq\code.ccp` | 启动器 `eve.exe` + 真实进程 `bin\exefile.exe`；`boot.ini` 标注 2.10/3913/Blood |
| Bash（Git Bash）命令 | PowerShell 5.1 命令（本工作区实测），POSIX 工具显式 `bash -lc` |
| `docker compose` 服务 `server`/`market`/`content-tools` 等 | `rmr-postgres` + `rmr-server` 两个服务 |
| 验证用 `tools/gridcheck` MCP | 验证用内置 `fakeclient`（无头 LLV 握手 + 脚本化 service 调用） |
| 静态数据 FSD/SDE、`evejs-fsd-dogma-editor` | 无对应物：老客户端数据在 `res\*.stuff` 与 `db/`；不迁该 skill |
| EveJS 专属 skill（elysian importer、external mod merge、gm-menu、server-debugging 等） | 不适用于 Rust 服务端/老客户端，未迁移；需要时按实际栈新写 |

## 分支模型变更

- 迁移前仓库只有 `main`（跟踪 `origin/main`）。
- 现在：`plus` = 开发主分支（从 `main` 同一提交建立，主工作区固定检出）；`main` = 上游基线，只用于对照/重置，不承载开发。
- `plus` **尚未推送**到 `origin`（规则：不自动 push）；推送前 `origin/plus` 不存在属预期。

## 生效方式

- 从 `M:\EVE-LOCAL\redmoonrising`（或其它 worktree）启动 opencode，会自动读取该目录的 `AGENTS.md` 与 `.opencode/skills/`。
- 新增/修改 skill 后需**重启 opencode** 才会出现在会话里。
- `AGENTS-DETAIL.md` 不常驻，只在执行对应任务时读取。

## 验证

- `git status` 干净、`git log --oneline -3` 有本次提交。
- 文件存在性：`AGENTS.md`、`AGENTS-DETAIL.md`、四个 skill 的 `SKILL.md`、`doc/README.md`、`doc/knowledge-inventory.md`、`doc/issues/INDEX.md`、五篇主题文档。
- `Get-Content .opencode/plugins/session-id.js` 与 `.opencode/package.json` 可解析（JSON 合法）。
- 每个 skill 的 `name` 与目录名一致。

## 回滚

- 规则文件全部是新增文件，回滚只需 `git revert <commit>`（或在分支上删除）。
- `plus`/`main` 分支关系不受影响；`rmr.yml`、服务端代码与数据库未做任何改动。

## 已知缺口

- 3913 客户端没有独立代码仓库；`tools/localization/` 与 `config/localization/` 未纳入版本控制（`tools/` 被 `.gitignore` 忽略）。
- 迁移未引入任何 MCP 服务；需要无头测试时直接用 `fakeclient`。
