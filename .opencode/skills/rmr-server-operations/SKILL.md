---
name: rmr-server-operations
description: Use when building, running, configuring or debugging the RMR server (Rust, Docker, Postgres) for EVE 3913. Triggers: rmr.yml, docker compose, cargo build, postgres, fakeclient
---

# RMR 服务端运维

规则与记录要求见 `AGENTS.md`；主题文档见 `doc/setup/server-operations.md`、`doc/data/database.md`。

## 一键运行

```powershell
M:\EVE-LOCAL\redmoonrising\Start-RMR.bat            # 起服务端 + 等 26000 + 拉起客户端（本地脚本，未跟踪）
M:\EVE-LOCAL\redmoonrising\Start-RMR.bat --no-client # 只起服务端
docker compose up -d
docker compose logs -f server --tail 100
```

端口：26000 游戏、8080 web、5432 Postgres。EveJS 等服务在跑会占 26000/5432——先停对应容器，不要改 RMR 端口来“绕开”。

## 构建

```powershell
cargo build --release -p eve-server --bins
cargo test -p eve-marshal -p eve-proto
docker compose build server
```

- `target/` 在各自 worktree 内；并发构建要抢 `CARGO_TARGET_DIR` 锁。
- `Dockerfile` 需要拉 `rust:1.97-slim-trixie` 与 crates；断网时优先本地 cargo。
- web 前端：`cd crates/eve-server/web; npm run build` 生成 `dist/app.js`（随源提交，构建服务端不需要 Node）。

## 配置优先级

`RMR_*` 环境变量 > `rmr.yml` > `crates/eve-server/src/rmr.default.yml` 内置默认（`config.rs:181` 的 `load()`）。

- 改 `rmr.yml` 后必须重启服务端；容器只读挂载该文件。
- 常用：`RMR_LOG=debug`、`RMR_LOG=trace`、`RMR_DATABASE`、`RMR_BOTS=0`（先关掉 10 万 bot 再看玩家路径性能）、`RMR_WEB=`（关仪表盘）。
- 账号在 `rmr.yml accounts:` 里声明，每次启动创建/对齐；`gm: true` 才能用 `/` 命令。

## 数据库

```powershell
docker compose exec postgres psql -U rmr -d rmr -c "SELECT count(*) FROM \"account\";"
docker compose exec -T postgres pg_dump -U rmr -d rmr | Out-File -Encoding utf8 backup.sql
```

- `db/*.sql.gz` 只在卷为空时导入；改它不会影响已有卷。
- 清卷 = 删所有角色，先确认。
- PowerShell 重定向默认 UTF-16，恢复时用 `Get-Content -Encoding UTF8 ... | docker compose exec -T ... psql`。

## 无头验证

```powershell
cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000
cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000 --script calls.txt
```

`fakeclient` 走完整 LLV 握手与登录，再按脚本发 service 调用并断言——客户端之外最可靠的回归入口。脚本语法见 `crates/eve-server/src/bin/fakeclient.rs` 的 `parse_script`。

## 排障顺序

1. `docker compose ps`：两个容器是否 healthy。
2. `docker compose logs server --tail 100`：`cannot reach PostgreSQL`、`string table`、`panic`。
3. 端口是否被占：`Get-NetTCPConnection -LocalPort 26000 -ErrorAction SilentlyContinue`。
4. 无法解码的帧在 `RMR_DUMP_DIR`（容器 `/app/dumps`），`docker cp rmr-server:/app/dumps .` 取出。
5. 客户端侧证据：`M:\EVE-LOCAL\inputs\EVE-Online-3913\capture\Gamelogs`。

## 禁止事项

- 客户端（`exefile` 进程）在跑时禁止重启服务端/数据库。
- 不提交 `dumps/`、`target/`、日志或本机备份。

## 触发关键词

rmr.yml, RMR_LOG, docker compose, rmr-server, rmr-postgres, pgdata, db 转储, cargo build, fakeclient, 26000, 8080, 5432, 启动失败, postgres 连不上, 服务端重启
