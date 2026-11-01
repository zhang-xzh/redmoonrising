# 知识清单

RMR 项目的知识索引：技能（skills）、仓库文档、脚本与工具，以及给后续 agent 的环境事实。

## 环境事实

- 服务端：`M:\EVE-LOCAL\redmoonrising`（Rust workspace；镜像 `rmr-server`，容器 `rmr-server` / `rmr-postgres`；端口 26000 / 8080 / 5432）。
- 客户端：`M:\EVE-LOCAL\inputs\EVE-Online-3913`（EVE 2.10 / build 3913 / codename Blood，`eve.exe`，永不升级）。
- 客户端启动：`M:\EVE-LOCAL\redmoonrising\Start-RMR.bat`（起服务端并拉起客户端）或客户端目录内 `Launch-EVE-RMR.bat`（设 `USERDOMAIN=CENTRAL` 显示 Local Servers）。
- 上游：`origin` = `github.com/pixelcatburglar/redmoonrising`（`main` 为上游基线，`plus` 为开发主分支）。
- 数据库：PostgreSQL 16，命名卷 `pgdata`，初始化数据 `db/*.sql.gz`（212 个表转储）。
- 客户端代码：`script/compiled.code` 当前是**零售原版**（sha256 `daa5eae3…`、md5 `36e18ef3…`）；上一版中文包在 `script/compiled.code.zh-prev-20261101-194509`（md5 `251dfdef…`）和 `tools/localization/artifacts/compiled.code.zh`；`script/compiled.code.vanilla` 当前**缺失**，重置来源用 `M:\EVE-LOCAL\inputs\EVE-Online-3913-code\dist\compiled.code`（与零售原版同 hash）。工具 `tools/localization/` 与映射 `config/localization/ui_en_zh.json` 已入库；逐模块基线见 `doc/client/client-code-baseline.md`，版本/完整性基线见 `doc/data/provenance-3913.md`。
- 技能目录：`M:\EVE-LOCAL\redmoonrising\.opencode\skills\`（纳入 git）。
- 仓库文档：`M:\EVE-LOCAL\redmoonrising\doc\`（按领域分目录，见下）。

## 技能

| Skill | 用途 |
|---|---|
| `agent-context-efficient-reads` | 大文件/大输出/多步骤时的上下文压缩与少往返策略 |
| `rmr-server-operations` | 构建、启动、配置（`rmr.yml`）、日志、数据库与客户端联调 |
| `rmr-client-code` | `compiled.code` 容器格式、`tools/localization` 工具链、本地化流程 |
| `eve-online-university-wiki` | 查 EVE 玩法/机制（现代资料，取值仍需回到 3913 客户端） |

## 仓库文档

| 目录 | 放什么 |
|---|---|
| `doc/setup/` | 运行、构建、配置、启动器、agent 规则迁移记录 |
| `doc/platform/` | crate 划分、连接与服务、世界状态、ballpark/destiny、bots、web |
| `doc/data/` | PostgreSQL 表转储、卷操作、备份/重置、版本溯源 |
| `doc/client/` | 3913 客户端目录、`compiled.code`、本地化 |
| `doc/issues/` | 已解决异常归档与索引 |

## 文档清单

| 文档 | 内容 |
|---|---|
| `doc/setup/server-operations.md` | 构建/运行/配置/日志/联调 |
| `doc/setup/agent-rules.md` | 本仓库 agent 规则（AGENTS.md/.opencode/skills/doc 约定）的来源与生效方式 |
| `doc/platform/architecture.md` | 服务端架构总览（crate、模块、数据流） |
| `doc/data/database.md` | 数据库结构、初始化、备份、重置 |
| `doc/data/provenance-3913.md` | 客户端/数据库版本锚点、sha256 基线、消息键交叉校验 |
| `doc/client/client-3913.md` | 客户端布局、`compiled.code`、本地化工具链 |
| `doc/client/client-code-baseline.md` | 零售代码基线仓库（`dist`+`tree`+`lib`+`stdlib`）、反编译工具与验证 |
| `doc/issues/INDEX.md` | 异常归档索引 |

## 脚本与工具

| 路径 | 用途 |
|---|---|
| `Start-RMR.bat`（本地脚本，当前未跟踪） | 起 compose、等 26000、拉起客户端（`--no-client` 只起服务端） |
| `docker-compose.yml` / `Dockerfile` | Postgres + 服务端容器；镜像内带 `strings.txt` |
| `crates/eve-server/src/bin/fakeclient.rs` | 无头客户端：LLV 握手 + 脚本化服务调用 |
| `crates/eve-server/web/` | TypeScript 仪表盘（`npm run build` 产出 `web/dist/app.js`，随源提交） |
| `tools/localization/*.py` | `compiled.code` 解包/反汇编/改写/重打包/校验与本地化产物（已纳入版本库；`tools/` 仍在 `.gitignore`，新增文件要 `git add -f`） |
| `tools/data-provenance/*.py` | 客户端 + `db/` 的 sha256 清单、数据库内容锚点、客户端消息键交叉校验；基线 JSON 与用法见 `doc/data/provenance-3913.md`（已纳入版本库，新增文件要 `git add -f`） |
| `db/*.sql.gz` | 官方表转储，卷首次启动时导入 |
