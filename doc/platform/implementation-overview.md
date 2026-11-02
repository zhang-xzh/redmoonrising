# 服务端实现总览

本文件是 RMR 服务端（EVE 2.10 / build 3913，codename Blood）的**实现手册入口**：讲清代码怎么组织、进程怎么启动、有哪些常驻任务、状态放在哪里、一次客户端调用如何走完。协议细节、世界模拟、玩法、服务层、bot 与 web 各有专文，见文末「阅读顺序」。

架构的职责级概览见 `doc/platform/architecture.md`；本手册面向「要改代码/排查行为」的读者，结论都带 `file:line` 依据。

## 1. Workspace 与依赖

| Crate | 行数量级 | 职责 |
|---|---|---|
| `crates/eve-marshal` | ~1.0k | EVE marshal 值模型与编解码、客户端共享字符串表 |
| `crates/eve-proto` | ~1.0k | LLV 握手、machoNet 帧、压缩、包与地址 |
| `crates/eve-server` | ~39k | 连接、服务分发、世界状态、模拟、bot、web、无头客户端 |

依赖（`crates/eve-server/Cargo.toml:10`）：

- `tokio`（multi-thread runtime、net、time）：每个连接一个任务。
- `tokio-postgres`：**没有连接池**；主连接 `Server.db` 由所有 handler 共享，心跳另外开一条连接。
- `flate2`：bulk 数据与帧的 zlib 压缩。
- `serde` / `serde_json` / `serde_yaml_ng`：配置、web JSON。
- `tracing` / `tracing-subscriber`：日志。
- `thiserror`：错误类型。

workspace 只有这三个成员（`Cargo.toml:3`），edition 2021、MSRV 1.75（`Cargo.toml:6`、`Cargo.toml:7`）。

## 2. 进程启动

入口 `crates/eve-server/src/main.rs:44`：

1. `Config::load()`（`crates/eve-server/src/config.rs:181`）读 `RMR_CONFIG` 指定的 YAML，默认工作目录 `rmr.yml`；文件不存在时把内置默认（`crates/eve-server/src/rmr.default.yml`）写到磁盘。**配置先于日志**，因为日志级别写在配置里。
2. `logging::init`（`crates/eve-server/src/logging.rs:41`）按 `log.level` / `RMR_LOG` / `RUST_LOG` 建过滤器和可选文件输出。
3. `run(config)`（`main.rs:64`）依次：
   - 读共享字符串表 `RMR_STRINGS`（`main.rs:66`），解析成 `StringTable`。
   - 连 PostgreSQL（`db::connect`，`crates/eve-server/src/db.rs:11`），统计 `account` 行数。
   - `db::sync_accounts`（`db.rs:72`）把配置文件里的账号建出来或对齐密码/GM 角色/封禁。
   - `config::set_rules` 把新角色初始 ISK 与自动建号开关放进进程级 `OnceLock`（`config.rs:318`）。
   - `BulkData::load`（`crates/eve-server/src/bulkdata.rs:164`）把静态表预编码成登录时下发的 bulk 对象。
   - `dogma::Catalog::load` 载入属性/效果目录。
   - `svc::registry()`（`crates/eve-server/src/svc/mod.rs:58`）构造服务表。
   - 组装 `Arc<Server>`（`crates/eve-server/src/conn/mod.rs:33`）。
   - 起三个常驻任务：`heartbeat::run`（250 ms 脉冲）、`bots::run`、`web::run`（`main.rs:118`）。
   - 监听 `RMR_BIND`（默认 `0.0.0.0:26000`），每接受一条连接就 `tokio::spawn(Conn::new(..).run())`（`main.rs:126`）。

启动期失败一律 `std::process::exit`：配置/日志错误退出码 2，运行期错误退出码 1（`main.rs:46`、`main.rs:58`）。

## 3. 配置

配置文件分五段（`config.rs:98`）：`server`、`log`、`game`、`bots`、`accounts`，字段用 camelCase，**拼错的键直接报错**（`deny_unknown_fields`，`config.rs:97`）。空文件或纯注释视为全部默认（`config.rs:290`）。每个键都有对应的 `RMR_*` 环境变量，环境变量覆盖文件（`config.rs:205` 起）。

| 文件键 | 环境变量 | 默认 | 作用 |
|---|---|---|---|
| `server.bind` | `RMR_BIND` | `0.0.0.0:26000` | 游戏监听地址 |
| `server.web` | `RMR_WEB` | `0.0.0.0:8080` | web 面板；空串关闭 |
| `server.database` | `RMR_DATABASE` | `postgres://rmr:rmr@127.0.0.1:55432/rmr` | PostgreSQL URL |
| `server.nodeId` | `RMR_NODE_ID` | `1` | machoNet 节点号，clientID 低位；限制 0..10,000,000 |
| `server.autoCreateAccounts` | `RMR_AUTO_CREATE_ACCOUNTS` | `false` | 未知用户名登录时自动建号 |
| `server.strings` | `RMR_STRINGS` | 仓库内 `crates/eve-marshal/tests/data/strings.txt` | 客户端共享字符串表 |
| `server.dumpDir` | `RMR_DUMP_DIR` | `.` | 无法解码的帧落盘目录 |
| `log.level` | `RMR_LOG` / `RUST_LOG` | `debug` | off/error/warn/info/debug/trace 或自定义过滤器 |
| `log.file` | `RMR_LOG_FILE` | 空 | 额外追加的日志文件 |
| `game.startingIsk` | `RMR_STARTING_ISK` | 5000 | 新角色初始 ISK |
| `game.allianceJoinDelaySeconds` | `RMR_ALLIANCE_JOIN_DELAY` | 86400 | 联盟接受公司后的生效延迟 |
| `game.starbaseSpeedup` | `RMR_STARBASE_SPEEDUP` | 1 | 母星建筑锚定/上线/解锚加速倍率 |
| `game.sovClaimDelaySeconds` | `RMR_SOV_CLAIM_DELAY` | 518400 | 主权声明生效前的等待 |
| `bots.count` | `RMR_BOTS` | 0 | bot 角色总数；首次生成后保留 |
| `bots.speed` | `RMR_BOTS_SPEED` | 1 | bot 模拟时间倍速 |
| `bots.shownPerSystem` | `RMR_BOTS_SHOWN` | 120 | 玩家所在星系最多显示多少 bot 船 |
| `bots.piratesAttackPlayers` | `RMR_BOTS_PIRATES_ATTACK` | true | 海盗 bot 是否主动攻击玩家 |
| `bots.dashboardControls` | `RMR_BOTS_CONTROLS` | false | web 面板能否操纵 bot |
| `accounts[]` | — | 一个 `testuser` | 每次启动建号/对齐：`username`、`password`、`gm`、`banned`、`startingIsk`、`role` |

账号列表会做重名与空用户名/密码校验（`config.rs:240`）。GM 位来自 `GM_ROLES = ROLE_GML|ROLE_GMH|ROLE_PETITIONEE|ROLE_LEGIONEER`（`config.rs:9`）。

**生效方式**：配置只在启动时读取，改 `rmr.yml` 必须重启服务端容器；客户端在线时禁止重启（见 `AGENTS.md`）。

## 4. 常驻任务与并发模型

进程里长期存在五类任务：

| 任务 | 起点 | 频率 | 职责 |
|---|---|---|---|
| accept 循环 | `main.rs:126` | 每新连接 | 接受 TCP，起 `Conn` |
| 每条连接 | `conn/mod.rs:108` | 事件驱动 | 握手、读帧、分发、回包、消费通知队列 |
| 心跳 | `heartbeat.rs:137` | 250 ms | 推进每个有玩家在太空的 ballpark、战斗、POS；每分钟做慢事务 |
| bot 模拟 | `bots/mod.rs`（`bots::run`） | 自己的时钟 | 人口、行为、战争、经济、Local 显示 |
| web | `web.rs` | 请求驱动 | HTTP 仪表盘 |

线程模型：`#[tokio::main]` 默认多线程 runtime（`main.rs:43`）。**没有按连接分线程**，也没有 actor/消息总线；跨连接共享状态只有三处：

1. `World`：`Arc<Mutex<WorldState>>`，一把标准库 `Mutex` 保护全部世界状态（`world.rs:173`）。连接之间要看到一致顺序的变更（船离开星系、聊天行）都在这把锁里做；**持锁期间不 `await`**，通知只入队（`world.rs:5`）。
2. `Server`：`Arc<Server>`，内含不可变的大对象（字符串表、bulk 数据、dogma 目录、服务表）与数据库客户端。
3. 进程级 `OnceLock`：`config::Rules`（`config.rs:318`）、POS 加速倍率等少量开关。

每条连接自己的可变状态（`Session`、认证标志、待发 session change、客户端调用回调表）不外借，只在该连接任务里改。通知、强制移动、服务器对客户端发起的调用都通过 `world` 里每连接的 `UnboundedSender<Push>` 排队，由连接任务在 `select!` 中和读帧一起消费（`conn/mod.rs:131`）。

数据库并发：`Server.db` 是一个共享的 `tokio_postgres::Client`，**没有连接池**——同一时刻只有一条 TCP 连接，查询由 tokio-postgres 的后台连接任务多路复用（`db.rs:11`）。心跳为了在锁外做事务并拿到 `&mut Client`，另建了自己的连接（`heartbeat.rs:138`）。

## 5. 状态都在哪里

| 状态 | 位置 | 生命周期 |
|---|---|---|
| 客户端连接、在线角色、聊天频道、各星系 ballpark、交易、舰队、bot 视图 | `WorldState`（`world.rs:91`） | 进程内；断线移除 |
| 单连接的会话变量 | `Session`（`session.rs:18`） | 连接内；登录/移动时改 |
| 物品、角色、军团、市场、合同等持久数据 | PostgreSQL | 永久 |
| 静态表（类型、属性、效果、星系名…） | 启动时 `BulkData` / `dogma::Catalog` | 进程内只读快照 |
| bot 人口身份 | `bots` 等表；`world.bot_*` 是运行时视图 | 首次生成后跨重启保留 |
| 配置 | `Config` + `OnceLock<Rules>` | 启动时定死 |

## 6. 一次客户端调用的全链路

以任意 `CallReq` 为例：

1. `Conn::serve` 用 `FrameReader` 从 TCP 缓冲切出一帧；解不开就落盘 `badframe-<client>-<len>.bin` 并带原因关闭连接（`conn/mod.rs:145`、`conn/mod.rs:502`）。
2. `decode_payload` 做帧解压/marshal 解码，`MachoPacket::from_value` 还原包头；非法命令直接拒绝（`conn/mod.rs:156`）。
3. `dispatch` 把源地址改成该客户端、补 `user_id`，按 `MessageType` 分流（`conn/mod.rs:192`）。
4. `CallReq` 走 `service_call` → `services::parse_call`：解出两层 marshal（外层 `(bound_flag, blob)`，内层 `(service, method, args, kwargs)`），去掉传输元数据 `machoVersion`（`services.rs:52`）。
5. 少数改变连接状态的方法在 `conn` 里直接截获，不进服务表：`character::SelectCharacterID`、`beyonce::Dock/TurboDock/StargateJump`、`ship::Undock/Board`（含 bind 上的 piggyback）（`conn/mod.rs:236`）。
6. 其余交给 `Registry::dispatch`：bound 服务先处理 `MachoResolveObject`/`MachoBindObject`，再按注册顺序试每个 handler，第一个返回 `Some(Outcome)` 的生效（`services.rs:255`）。
7. handler 在 `Ctx` 上拿到 bulk/dogma/session/db/world/client_id，可以查库、改世界、入队通知（`services.rs:122`）。
8. 结果三种：`Outcome::Value` → `CallRsp`；`Unknown` → `ServiceNotFound`；`UserError` → wrapped `ccp_exceptions.UserError`（`conn/mod.rs:272`、`exceptions.rs:6`）。
9. 回包后若还压着登录期的 session change，则在第一条非 `objectCaching` 调用之后释放（`conn/mod.rs:368`）。

## 7. 持久化与数据边界

- 所有持久数据只在 PostgreSQL；`db/*.sql.gz` 只在空数据卷首次启动时导入（见 `doc/data/database.md`）。
- 服务端不缓存可变玩家数据，查询直接用 SQL；只有静态表和 dogma 目录在启动时快照。
- 物品写操作集中在 `items::ItemTxn`（`items.rs`），提交后返回事件列表，再由 `items::notify` 推给客户端。
- 心跳把「锁内决策」与「锁外落库」拆开：`Out` 收集 destiny/通知，`Job` 列表在锁释放后逐条执行（`heartbeat.rs:32`、`heartbeat.rs:187`）。

## 8. 错误、日志与可观测性

- 连接级错误是 `ConnError`（`conn/mod.rs:49`）：IO、协议、marshal、数据库、协议违规、服务器主动关闭。
- 数据库错误在 `Ctx::query/execute` 里被吞掉并记日志，客户端得到空结果而不是异常（`services.rs:139`）；这是有意的降级。
- 日志：控制台带颜色与 `conn{client,peer,user,char}`、`call{svc,method}` span；文件输出无颜色、带日期（`logging.rs:41`、`logging.rs:95`）。`logging::chain` 展开数据库错误的 source 链（`logging.rs:80`）。
- 启动汇总：字符串表条数、账号数、bulk 对象数/行数/字节数/耗时（`main.rs:140`），接近 1 MB 帧上限的 bulk 会告警（`main.rs:41`）。

## 9. 验证入口

| 目的 | 入口 |
|---|---|
| 单元测试 | `cargo test -p eve-marshal -p eve-proto`、`cargo test -p eve-server` |
| 无头协议/玩法回归 | `cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000 [--script <file>]`（见 `doc/platform/implementation-web.md`） |
| 服务端运行日志 | `docker compose logs server --tail 100` |
| 数据库结果 | `docker compose exec postgres psql -U rmr -d rmr -c "<SQL>"` |
| 客户端表现 | 完全重启客户端；证据取 `capture\Gamelogs` / `capture\Chatlogs` |

## 10. 阅读顺序

| 文档 | 内容 |
|---|---|
| `doc/platform/implementation-protocol.md` | marshal、LLV、帧、包、服务分发、bulk、异常 |
| `doc/platform/implementation-world.md` | 世界状态、会话、移动、ballpark/destiny、物品/dogma、心跳 |
| `doc/platform/implementation-gameplay.md` | 战斗、NPC、无人机、掉落/损失、犯罪、生产、POS/主权 |
| `doc/platform/implementation-services.md` | 服务注册表与每个 service 的契约 |
| `doc/platform/implementation-bots.md` | bot 人口、行为、战争、经济、控制面 |
| `doc/platform/implementation-web.md` | web 仪表盘 API 与 fakeclient |

改代码时的最小闭环：先读对应专文的「模块地图」定位文件 → 用 `grep` 找调用方 → 改完按第 9 节验证 → 把行为变化写回对应专文（写「现在是什么样」，不写变更日志）。


