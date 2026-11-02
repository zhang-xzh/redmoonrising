# 知识清单
> 客户端工具、补丁与本地化流水线已迁至独立仓库 `M:\EVE-LOCAL\inputs\EVE-Online-3913-code`；
> 本文中的 `tools/...`、`config/localization/...` 均相对该仓库根目录。

RMR 项目的知识索引：技能（skills）、仓库文档、脚本与工具，以及给后续 agent 的环境事实。

## 环境事实

- 服务端：`M:\EVE-LOCAL\redmoonrising`（Rust workspace；镜像 `rmr-server`，容器 `rmr-server` / `rmr-postgres`；端口 26000 / 8080 / 5432）。
- 客户端：`M:\EVE-LOCAL\inputs\EVE-Online-3913`（EVE 2.10 / build 3913 / codename Blood，`eve.exe`，永不升级）。
- 客户端启动：`M:\EVE-LOCAL\redmoonrising\Play.bat`（仓库根；起服务端并拉起客户端，设 `USERDOMAIN=CENTRAL` 显示 Local Servers）。
- 远端：`origin` = 上游 `github.com/pixelcatburglar/redmoonrising`（只作对照/取上游，`main` 跟踪 `origin/main`）；`fork` = 自己的 GitHub fork `github.com/zhang-xzh/redmoonrising`，`plus` 跟踪 `fork/plus` 并作为推送目标。`main` 为上游基线，`plus` 为开发主分支。
- 数据库：PostgreSQL 16，命名卷 `pgdata`，初始化数据 `db/*.sql.gz`（212 个表转储）。
- 客户端代码：`script/compiled.code` 当前是**零售原版**（sha256 `daa5eae3…`、md5 `36e18ef3…`）；上一版中文包在 `script/compiled.code.zh-prev-20261101-194509`（md5 `251dfdef…`）和 `tools/localization/artifacts/compiled.code.zh`；`script/compiled.code.vanilla` 当前**缺失**，重置来源用 `M:\EVE-LOCAL\inputs\EVE-Online-3913-code\dist\compiled.code`（与零售原版同 hash）。客户端代码工具 `tools/client-code/`、本地化流水线 `tools/localization/` 与映射 `config/localization/ui_en_zh.json` 已入库；逐模块基线见 `doc/client/client-code-baseline.md`，版本/完整性基线见 `doc/data/provenance-3913.md`。
- 技能目录：`M:\EVE-LOCAL\redmoonrising\.opencode\skills\`（纳入 git）。
- 仓库文档：`M:\EVE-LOCAL\redmoonrising\doc\`（按领域分目录，见下）。

## 技能

| Skill | 用途 |
|---|---|
| `agent-context-efficient-reads` | 大文件/大输出/多步骤时的上下文压缩与少往返策略 |
| `rmr-server-operations` | 构建、启动、配置（`rmr.yml`）、日志、数据库与客户端联调 |
| `rmr-client-code` | `compiled.code` 容器格式、`tools/client-code` 代码工具、`tools/localization` 本地化流程 |
| `eve-online-university-wiki` | 查 EVE 玩法/机制（现代资料，取值仍需回到 3913 客户端） |

## 仓库文档

| 目录 | 放什么 |
|---|---|
| `doc/setup/` | 运行、构建、配置、启动器、agent 规则迁移记录 |
| `doc/platform/` | crate 划分、连接与服务、世界状态、ballpark/destiny、bots、web |
| `doc/data/` | PostgreSQL 表转储、卷操作、备份/重置、版本溯源 |
| `doc/client/` | 3913 客户端目录、`compiled.code`、本地化、多语言 |
| `doc/issues/` | 已解决异常归档与索引 |

## 文档清单

| 文档 | 内容 |
|---|---|
| `doc/setup/server-operations.md` | 构建/运行/配置/日志/联调 |
| `doc/setup/agent-rules.md` | 本仓库 agent 规则（AGENTS.md/.opencode/skills/doc 约定）的来源与生效方式 |
| `doc/platform/architecture.md` | 服务端架构总览（crate、模块、数据流） |
| `doc/platform/implementation-overview.md` | 实现手册入口：启动、配置、常驻任务、并发模型、状态归属、调用全链路、验证入口 |
| `doc/platform/implementation-protocol.md` | marshal、LLV 握手、machoNet 帧、服务分发、bulk 数据、异常 |
| `doc/platform/implementation-world.md` | 世界状态、会话变量、移动、ballpark/destiny、物品/dogma、心跳脉冲 |
| `doc/platform/implementation-gameplay.md` | 战斗、NPC/站点、无人机、损失/掉落、犯罪与警察、生产、POS/主权 |
| `doc/platform/implementation-services.md` | 服务注册表与每个 service 的 method/数据表契约 |
| `doc/platform/implementation-bots.md` | bot 人口、行为状态机、战争/政治、经济、控制面 |
| `doc/platform/implementation-web.md` | web 仪表盘路由/API/前端构建与 fakeclient 用法 |
| `doc/data/database.md` | 数据库结构、初始化、备份、重置 |
| `doc/data/provenance-3913.md` | 客户端/数据库版本锚点、sha256 基线、消息键交叉校验 |
| `doc/client/client-3913.md` | 客户端布局、`compiled.code`、本地化工具链 |
| `doc/client/client-code-baseline.md` | 零售代码基线仓库（`dist`+`tree`+`lib`+`stdlib`）、反编译工具与验证 |
| `doc/client/multilanguage-3913.md` | 多语言机制、分层方案、会话/bulk/客户端文案的实施阶段 |
| `doc/client-localization-3913.md` | 客户端本地化流水线的原始说明（依据、现状、限制），根级方法文档 |
| `doc/issues/INDEX.md` | 异常归档索引 |

## 脚本与工具

| 路径 | 用途 |
|---|---|
| `Play.bat`（仓库根，已跟踪） | 起 compose、等 26000、拉起客户端（`--no-client` 只起服务端）；`RMR_CLIENT_DIR` 覆盖客户端目录 |
| `docker-compose.yml` / `Dockerfile` | Postgres + 服务端容器；镜像内带 `strings.txt` |
| `crates/eve-server/src/bin/fakeclient.rs` | 无头客户端：LLV 握手 + 脚本化服务调用 |
| `crates/eve-server/web/` | TypeScript 仪表盘（`npm run build` 产出 `web/dist/app.js`，随源提交） |
| `M:\EVE-LOCAL\inputs\EVE-Online-3913-code\tools\client-code\*.py` | `compiled.code` 容器解包/反汇编/扫描/重打包校验与诊断探针（独立客户端仓库） |
| `M:\EVE-LOCAL\inputs\EVE-Online-3913-code\tools\localization\*.py` | 本地化映射构建、字符串改写、静态消息生成与产物（独立客户端仓库） |
| `tools/data-provenance/*.py` | 客户端 + `db/` 的 sha256 清单、数据库内容锚点、客户端消息键交叉校验；基线 JSON 与用法见 `doc/data/provenance-3913.md`（已纳入版本库，新增文件要 `git add -f`） |
| `db/*.sql.gz` | 官方表转储，卷首次启动时导入 |
