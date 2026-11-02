# 服务端架构

RMR 是 EVE 2.10 / build 3913（2006）的 machoNet 服务端。协议与玩法以零售客户端为准，服务端只做“客户端期望的那一侧”。

本文件是职责级概览；逐模块的实现细节见 `doc/platform/implementation-overview.md` 及其分册（协议、世界、玩法、服务层、bot、web）。

## Crate 划分

| Crate | 职责 | 关键入口 |
|---|---|---|
| `crates/eve-marshal` | EVE marshal 编解码：值模型、字符串表、CRC、序列化 | `Value`、`StringTable`、`load`/`save`（`crates/eve-marshal/src/lib.rs`） |
| `crates/eve-proto` | LLV 版本握手、machoNet 帧（压缩/长度上限）、包与地址 | `VersionChallenge`、`FrameReader`、`MachoPacket`（`crates/eve-proto/src/lib.rs`） |
| `crates/eve-server` | 连接、服务分发、世界状态、模拟、bot、web | `main.rs`、`conn/`、`services.rs`、`svc/`、`world.rs`、`ballpark.rs`、`bots/`、`web.rs` |

## 启动顺序

`crates/eve-server/src/main.rs:44`：

1. 读配置（`config::Config::load()`，先于日志，因为日志配置在文件里）。
2. 初始化日志（`logging::init`）。
3. `run()`：加载共享字符串表（`RMR_STRINGS`）→ 连 PostgreSQL（`db::connect`，`crates/eve-server/src/db.rs:11`）→ 统计账号 → 建 `Server`（连接表 + `World`）→ 监听 `RMR_BIND` → 可选起 web（`RMR_WEB`）。

## 连接与协议

`crates/eve-server/src/conn/mod.rs`：一条客户端连接 = 帧读取、请求分发、回包、以及其它连接排队给它的通知。

- `conn/auth.rs`：LLV 版本握手与账号登录（`db::authenticate`，`db.rs:21`）。握手比对客户端上报的 build/codename；账号密码直接比对 `account."password"` 字段（零售 2006 语义，无哈希）。
- `conn/location.rs`：会话移动——进游戏、进站、出站、跳跃；每次同步把船移入/移出星系的 ballpark，让同一星系的其他玩家看到进出。
- 角色/会话变量（`session.rs`）：`ROLE_LOGIN`/`ROLE_PLAYER`/`ROLE_PETITIONEE` 与 `PERSIST_VARS`（客户端会话持久字段）。

## 服务分发

- `services.rs`：`Call`（service、method、args、kwargs，`services.rs:19`），`service_name()` 会剥掉 bound object 前缀（`N=1:invbroker#60000004`）。
- `svc/mod.rs:58` 的 `registry()` 把 service 名映射到 handler，handler 在 `crates/eve-server/src/svc/*.rs`（agents、inventory、market、dogma、factory、station、chat、corp、alliance、war、gm ……）。
- 大块数据走 `bulkdata.rs`（压缩的 rowset/tuple），避免单帧超限（`main.rs` 的 `BULK_WARN_BYTES` 提醒接近 1 MB 的帧）。
- GM 命令在 `svc/gm.rs`（`/create`、`/giveisk`、`/giveskill`、`/setstanding`、`/spawn`、`/tr me`、`/bots ...`、`/help`）；只有带 `ROLE_GML`/`ROLE_LEGIONEER` 的会话能用（`config.rs:9` 的 `GM_ROLES`）。

## 世界与模拟

- `world.rs`：所有连接共享的状态——在线角色、打开的聊天频道、各星系 ballpark、每连接的待发通知队列。**一把锁保护全部**，持锁期间不 `await`（通知只入队不发送）。
- `ballpark.rs`：服务端 destiny——星系内每条船的位置与运动，是 `destiny.dll` 的 `Ballpark::Evolve` 移植（每秒一 tick），不是近似；偏离客户端就会出现“两人看到船在两个位置”。
- `destiny.rs`：`SetState`/`AddBalls` 携带的 ball 流格式（由 `ReadBallFromStream` 反汇编得出，注释里有字段布局）。
- `combat.rs`/`fight.rs`/`drones.rs`/`npc.rs`/`sites.rs`/`pos.rs`/`loot.rs`/`losses.rs`/`gates.rs`/`concord.rs`/`guard.rs`：战斗、NPC、死亡空间、POS、掉落、击杀、星门、CONCORD 等玩法模块。
- `items.rs`/`dogma.rs`/`gates.rs` 等：物品实例、属性计算与移动。

## Bot 人口

`bots/`：服务端自己扮演的角色，让宇宙不空。

- `bots.count`（`RMR_BOTS`）首次启动时生成并保留；`bots.speed` 加快时钟用于测试。
- 每个 bot 到点由 `behaviour::step` 推进，状态写回是批量、定期；玩家所在星系才把 bot 显示成船（`presence`）。
- 大部分 bot 属于 bot 军团/联盟，互相打仗（`battle`、`war`、`sov`、`politics`）；`economy` 造市场，`hire`/`defense`/`relations` 处理雇佣、防御与玩家关系。
- `/bots on|off|status`、`/bots event|war|density|follow` 与 web 仪表盘都能操纵它们（`bots/mod.rs:101`）。

## Web 仪表盘

`web.rs`：内建页面（`web/index.html` + `style.css` + 编译后的 `web/dist/app.js`）与 JSON 接口：`/api/summary`、`/api/news`、`/api/sieges`、`/api/wars`、`/api/players`、`/api/alliances`、`/api/corporations`、`/api/systems`、`/api/kills` 等（`web.rs:105` 起）。唯一的写操作是 `POST /api/control`（操纵 bot），且要 `bots.dashboardControls` 打开。

前端是 TypeScript（`web/src/app.ts`），`npm run build` 生成 `web/dist/app.js` 并随源提交——构建服务端不需要 Node。

## 无头验证

`crates/eve-server/src/bin/fakeclient.rs`：连 26000、走 LLV 握手、登录、按脚本发 service 调用并断言，是客户端之外最可靠的回归入口。参数：地址（默认 `127.0.0.1:26000`）、`--script <file>`、`--no-cache`（`fakeclient.rs:141`，脚本语法见 `parse_script`，`fakeclient.rs:192`）。
