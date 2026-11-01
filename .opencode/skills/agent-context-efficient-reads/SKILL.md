---
name: agent-context-efficient-reads
description: Use for RMR large files, big tool/log output, or many tool steps. Triggers: 大文件, offset/limit, tool_output, 少往返, 并行, 子代理
---

# RMR 上下文高效读取

规则本体见 `AGENTS.md`「工具使用与上下文效率（强制）」。本 skill 是可执行细节与判定条件，目标是把工具输出与来回轮次压到最小，降低上下文膨胀与 provider 费用。

## 减少往返（最高杠杆）

每次 LLM 调用都会把整个上下文重发一遍，所以「轮数」比「单次输出大小」影响更大。

- **并行批量**：一轮内把相互独立的调用一起发出——多个 `read`/`grep`/`glob`，多条命令用 `;` 合并；不要一个接一个串行。
- **探索用子代理**：开放式/多轮翻找交给 `task`（`explore` 定位、`general` 多步）；往返发生在子代理自己的上下文，主会话只收一条结论。
- **先规划后动手**：动手前列步骤，避免读一步想一步、反复追加；同一文件/命令不重复读、不重复验证。
- **一次取够**：宁可在一次调用里多取，也不要为一点新信息再开一轮。

## 何时触发

- 要读的文件 > ~400 行或 > ~16KB。本仓库典型大文件：`crates/eve-server/src/svc/**/*.rs`、`crates/eve-server/src/bots/**`、`crates/eve-server/src/web.rs`、`db/*.sql.gz`、客户端 `compiled.code`、大 `doc/*.md`。
- 要跑会产出大段输出的命令：`docker compose logs`、`cargo build`/`cargo test`、`git log`/`git diff`、跨目录 `Select-String`、SQL 查询。
- 同一文件或同一命令即将重复调用。

## 读取

- 先 `glob`/`grep` 定位，再用 `read` 的 `offset`/`limit` 只取片段；同一大文件一个会话最多整读一次，之后一律 `grep` + 定点读。
- Rust 文件优先读模块头 `//!` 与函数签名，不整文件回显。
- 二进制/压缩数据（`compiled.code`、`*.stuff`、`*.sql.gz`）永远不直接读：用工具（`tools/localization/*.py`、`zcat`）抽取需要的部分。

## 命令输出（PowerShell）

- 日志：`docker compose logs server --tail 100 --since 10m | Select-String 'ERROR|WARN|panic'`；禁止 `--tail 400` 整段回显。
- 构建：`cargo build -p eve-server 2>&1 | Select-Object -Last 30`；成功时只报结论。
- 外部数据：结果重定向到 `C:\Users\zhang\AppData\Local\Temp\opencode` 下的文件，再用 `Select-String`/`jq`/`Select-Object -First N` 只回显所需字段；禁止整段 JSON/HTML 回显。
- 通用裁剪：长输出接 `Select-Object -First N` / `Select-String`；git 用 `--oneline`/`-n`；不用 `Get-Content` 回显已写内容。
- PowerShell 管道到文件默认 UTF-16：需要文本时 `Out-File -Encoding utf8`，二进制用 `-Encoding Byte`。

## 探索与查询

- 大范围开放式探索交给 `task`（`explore`/`general`），只让子代理回传结论。
- 数据库查询一律带 `LIMIT`，先聚合再取明细；禁止 `SELECT *` 全表回显；列名大小写敏感要加双引号。

## 配置层兜底

- `opencode.json`/全局配置的 `tool_output` 对每条工具输出做上限截断；被截断的完整输出落文件，需要时定点 `read`/`grep` 该文件，而不是重跑放大命令。

## 触发关键词

大文件, 整读, offset, limit, read, tool_output, 截断, Select-Object, Select-String, docker logs, SELECT *, cargo build 输出, 上下文膨胀, 前缀重发
