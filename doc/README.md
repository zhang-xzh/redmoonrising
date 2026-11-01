# RMR 文档目录

本仓库 `doc/` 的入口。按领域分目录，文件名统一小写 kebab-case；完整登记表（每个文档一行）见 [`knowledge-inventory.md`](knowledge-inventory.md)，已解决异常见 [`issues/INDEX.md`](issues/INDEX.md)。

## 目录地图

| 目录 | 内容 | 先读 |
|---|---|---|
| [`setup/`](setup/) | 运行、构建、配置、启动器、agent 规则迁移记录 | [`setup/server-operations.md`](setup/server-operations.md)、[`setup/agent-rules.md`](setup/agent-rules.md) |
| [`platform/`](platform/) | 架构：crate 划分、连接/服务/世界状态、ballpark、bots、web | [`platform/architecture.md`](platform/architecture.md) |
| [`data/`](data/) | PostgreSQL 表转储、卷、备份/重置 | [`data/database.md`](data/database.md) |
| [`client/`](client/) | 3913 客户端目录、`compiled.code`、本地化工具链、逐模块代码基线仓库 | [`client/client-3913.md`](client/client-3913.md)、[`client/client-code-baseline.md`](client/client-code-baseline.md) |
| [`issues/`](issues/) | 已解决异常归档（一篇一异常 + 索引） | [`issues/INDEX.md`](issues/INDEX.md) |

后续出现新领域（如 `gameplay/`、`market/`、`history/`）时按需建目录，并同时更新本文件与 `knowledge-inventory.md`。

## 放置约定

- 新文档先判领域：能落某个子目录就落；跨域的按主归属落（服务端机制归 `platform/`、客户端补丁归 `client/`、数据库与静态表归 `data/`）。
- 历史流水账（合并、回退、变更）只进 `history/`，文件名带日期：`merges-YYYY-MM-DD[-主题].md`、`revert-YYYY-MM-DD-主题.md`。
- 主题文档写成“当前状态”，不追加更新日志；被取代的内容直接删除。
- 新文档同时登记到 [`knowledge-inventory.md`](knowledge-inventory.md)（表格一行）。
- 文件名一律小写 kebab-case，不再新增 UPPER-CASE 或下划线命名。
- 仓库里另有一篇 `docs/client-localization-3913.md`（早期路径，客户端本地化的原始说明）；新增文档一律进 `doc/`，该文件保留作历史参考。
- 文档内引用其它文档用仓库相对路径 `doc/<领域>/<文件>.md`（正文反引号）或相对链接。

## 维护

- 移动/重命名文档时，同步更新：本文件、`knowledge-inventory.md`、`AGENTS.md`/`AGENTS-DETAIL.md`、`.opencode/skills/` 与 `crates/**` 注释中的引用。
- 全仓检查是否还有旧路径：`git grep -n "doc/" -- ':!doc/'`。
