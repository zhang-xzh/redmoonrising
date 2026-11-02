# 服务端运行与配置

RMR 服务端如何构建、启动、配置和观察。所有命令在仓库根 `M:\EVE-LOCAL\redmoonrising` 执行（worktree 同）。

## 组成

| 组件 | 说明 |
|---|---|
| `eve-server` | 服务端二进制（crate `crates/eve-server`），监听 26000；可选 web 仪表盘 8080 |
| `postgres` | `postgres:16-alpine`，容器 `rmr-postgres`，库/用户/密码均 `rmr`，卷 `pgdata` |
| `fakeclient` | 无头客户端二进制（同 crate 的 `bin/fakeclient.rs`），用于握手与 service 调用验证 |

## 启动

```powershell
# 推荐：起 compose、等 26000 就绪，再拉起客户端（仓库根，已跟踪）
M:\EVE-LOCAL\redmoonrising\Play.bat

# 只起服务端（不拉客户端）
M:\EVE-LOCAL\redmoonrising\Play.bat --no-client

# 手动
docker compose up -d
docker compose logs -f server --tail 100
```

先决条件：端口 26000/8080/5432 未被占用（EveJS 等服务若在跑，先停对应容器）。

`Play.bat` 以脚本所在目录为 compose 目录（`%~dp0`）。`docker-compose.yml` 固定项目名 `rmr`，所有 checkout 共用同一组容器，所以从 worktree 运行会用该 worktree 的代码重建 `rmr-server`；日常仍在主工作区 `M:\EVE-LOCAL\redmoonrising` 运行。`--no-client` 只起服务端；客户端目录用 `RMR_CLIENT_DIR` 覆盖。

## 本地构建（不走 Docker）

```powershell
cargo build --release -p eve-server --bins
cargo test -p eve-marshal -p eve-proto        # marshal/proto 的回归
cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000
```

服务端需要 Postgres（`RMR_DATABASE`）与字符串表（`RMR_STRINGS`，默认 `crates/eve-marshal/tests/data/strings.txt`）。

Docker 构建从 `rust:1.97-slim-trixie` 与 crates.io 拉依赖；离线或直连不通时用本地 cargo 构建镜像外版本。

## 配置：`rmr.yml`

- 文件位置：仓库根 `rmr.yml`（compose 以只读挂载进容器 `/app/rmr.yml`）；模板是 `crates/eve-server/src/rmr.default.yml`。
- 优先级：`RMR_*` 环境变量 > `rmr.yml` > 内置默认（见 `crates/eve-server/src/config.rs:15` 的 `Config` 字段注释，`config.rs:181` 的 `load()`）。
- **改完要重启服务端**才生效（`docker compose restart server`）；客户端在跑时不得重启（见 `AGENTS.md`）。

| 键 | 环境变量 | 作用 / 当前值 |
|---|---|---|
| `server.bind` | `RMR_BIND` | 客户端连接地址，`0.0.0.0:26000` |
| `server.web` | `RMR_WEB` | 仪表盘地址，`0.0.0.0:8080`（空 = 关闭；无登录，只在本机暴露） |
| `server.database` | `RMR_DATABASE` | PostgreSQL URL；compose 里覆盖为 `postgres://rmr:rmr@postgres:5432/rmr` |
| `server.nodeId` | `RMR_NODE_ID` | machoNet 节点 ID，保持 1 |
| `server.autoCreateAccounts` | `RMR_AUTO_CREATE_ACCOUNTS` | 未知用户名登录即建号；本地 `rmr.yml` 为 `true` |
| `server.dumpDir` | `RMR_DUMP_DIR` | 无法解码帧的落盘目录；容器内 `/app/dumps` |
| `log.level` | `RMR_LOG`（或 `RUST_LOG`） | `off`/`error`/`warn`/`info`/`debug`/`trace`，支持 filter（如 `info,eve_server::svc=trace`）；本地为 `debug` |
| `log.file` | `RMR_LOG_FILE` | 额外写文件；空 = 不写 |
| `game.startingIsk` | `RMR_STARTING_ISK` | 新角色初始 ISK，本地 5000 |
| `game.allianceJoinDelaySeconds` | `RMR_ALLIANCE_JOIN_DELAY` | 联盟加入延迟（客户端说 24 小时），86400 |
| `game.starbaseSpeedup` | `RMR_STARBASE_SPEEDUP` | 建筑锚定/上线加速倍率 |
| `game.sovClaimDelaySeconds` | `RMR_SOV_CLAIM_DELAY` | 主权宣称延迟（客户端说最多 6 天），518400 |
| `bots.count` | `RMR_BOTS` | bot 角色数量；**本地 `rmr.yml` 为 100000**（首次启动生成，之后保留） |
| `bots.speed` | `RMR_BOTS_SPEED` | bot 时钟倍速 |
| `bots.shownPerSystem` | `RMR_BOTS_SHOWN` | 同一星系最多显示的 bot 船数，本地 200 |
| `bots.piratesAttackPlayers` | `RMR_BOTS_PIRATES_ATTACK` | 海盗 bot 是否主动打玩家 |
| `bots.dashboardControls` | `RMR_BOTS_CONTROLS` | 仪表盘是否可操纵 bot（无登录，慎开） |
| `accounts[]` | — | 每次启动创建/对齐的账号（`gm`、`banned`、`startingIsk`、`role`）；本地含 `testuser`/`testpass` 与 `root`/`root`(GM) |

`rmr.yml` 会随仓库提交；账号密码属于本地测试凭据，不要换成本机真实密码。

## 观察与排障

```powershell
docker compose logs server --tail 100
docker compose logs server --since 10m | Select-String 'ERROR|WARN|panic'
docker compose exec postgres psql -U rmr -d rmr -c "SELECT count(*) FROM \"account\";"
```

- 启动日志会打印字符串表条目数、账号数、bot 数等；`debug` 级别逐条打印 service 调用。
- 无法解码的帧落到 `RMR_DUMP_DIR`（容器 `/app/dumps`，`docker cp rmr-server:/app/dumps .` 取出）。
- 客户端侧证据：`M:\EVE-LOCAL\inputs\EVE-Online-3913\capture\Gamelogs`（游戏事件）与 `capture\Chatlogs`。

## 验证清单（改动后）

1. `cargo fmt --check`；改到协议/marshal 时 `cargo test -p eve-marshal -p eve-proto`。
2. `cargo build -p eve-server`（或 `docker compose build server`）通过。
3. `docker compose up -d` 后日志无 `ERROR`/`panic`，26000 可连。
4. `fakeclient` 完成 LLV 握手并调通目标 service（无头断言）。
5. 进客户端实际走一遍受影响流程；证据落 `capture\Gamelogs`。

数据库初始化、备份与重置见 `doc/data/database.md`；客户端侧见 `doc/client/client-3913.md`。
