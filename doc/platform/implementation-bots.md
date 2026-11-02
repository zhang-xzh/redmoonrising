# Bot 人口模拟实现

`crates/eve-server/src/bots/` 是服务端自己扮演的“玩家人口”：真实角色行、真实军团/联盟、真实市场订单与击杀记录，让 3913 客户端里的宇宙不空。本文件描述**当前实现**：模块职责、启动与配置、时间模型、身份与 Local、行为状态机、战争与政治、经济与关系、控制面、数据库写入与已知限制。

所有数值均取自代码常量，括号内为真实位置。

## 模块地图

| 文件 | 职责 |
|---|---|
| `bots/mod.rs` | 运行时本体：`Sim` 状态、250 ms tick 循环、到点队列、批量写回、击杀写入、星图计数、Local 名单、`/bots` 入口与报告 |
| `bots/population.rs` | 静态地图 `Atlas`（星系/星门/空间站/小行星带/枢纽）、bot 角色的批量生成与读回 |
| `bots/behaviour.rs` | 单 bot 状态机 `step`、`Activity`/`Role`、活跃度曲线、会话与下线、移动/采矿/刷怪/长途、舰船升级与补船 |
| `bots/ships.rs` | 各 role 的舰船阶梯、市场价与货舱、按种族/吨位生成装配（炮、弹药、坦、采矿激光）、`punch` |
| `bots/presence.rs` | “被观察的一半”：有玩家在太空的星系把 bot 变成真实舰船、按 activity 给航向、战斗与反杀、胶囊、Local 之外的进出特效 |
| `bots/battle.rs` | 被玩家看见的攻城战：双方集结、站位、15 分钟上限、清场后轰塔、按剩余舰船或概率判定 |
| `bots/politics.rs` | 军团/联盟的形成与演化、战争（建立/结束/招募）、无人观看的遭遇战 `skirmish`、联盟 Logo |
| `bots/sov.rs` | 零安联盟的主权：控制塔落位、燃料、围城计划与公告、结算（毁塔/插塔/主权延迟）、星系内塔的增删同步 |
| `bots/war.rs` | **当前不存在该文件**；bot 战争的数据写入与判定分别在 `politics.rs`（`war_between`/`start_wars`）与 `sov.rs`（`Siege`），对玩家的战争由 `relations.rs` 声明 |
| `bots/economy.rs` | 采矿→精炼→运输→建船→挂单的聚合经济，真实 `market_orders`/`market_transactions`，公司税与联盟分成 |
| `bots/relations.rs` | 玩家与 bot 阵营的 heat/favor、声望、赏金、宣战、雇佣合同、邮件、入团申请与招募 |
| `bots/hire.rs` | 玩家雇佣 bot 僚机：报价、按小时扣费、跟船/跟跳/停靠、协战、解约 |
| `bots/defense.rs` | bot 控制塔被玩家攻击时的防御舰队：本星系即刻响应、20 s 后周边增援、3 分钟无攻击后解散 |
| `bots/events.rs` | 背叛、合并、崩溃、围剿联盟、海盗袭击五类事件，以及袭击的每分钟结算 |
| `bots/control.rs` | 控制请求队列与解析（event/war/density/follow）、`Following` 追踪历史 |
| `bots/panels.rs` | web 仪表盘的四个 JSON 窗口（市场、关系、追踪、事件）以及系统/空间站名字缓存 |
| `bots/schema.rs` | 启动时补建/迁移 bot 专用表与序列（`botStock`、`botRelations`、`botRegionDensity`、`bots.tier`） |

## 启动与配置

`main.rs:119` 先 `bots::configure(pirates_attack_players, dashboard_controls)`，`main.rs:120` 再 `tokio::spawn(bots::run(server, count, speed, shown))`。`bots::run` 在 `count == 0` 时直接返回（`bots/mod.rs:120`），不占用任何资源。

`run` 的启动顺序（`bots/mod.rs:119`）：

1. 记住 `server.db_url`，供后续另开连接（`bots/mod.rs:123`）。
2. `start()`：连库 → `schema::ensure` → `population::atlas` 读地图 → `population::ensure(target)` 生成缺口 → `population::load` 读回（`bots/mod.rs:165`）。
3. `politics::load`；若库中没有 bot 军团则 `politics::form` 现场组建（`bots/mod.rs:127-135`）。
4. `sov::establish` 给零安联盟插塔，并刷新 `svc::starbase::sovereignty`（`bots/mod.rs:136-143`）。
5. `markets()`：读所有阶梯舰船、经济品、市场枢纽，给每个 bot 定 `hull`/`tier`/`prime`（`bots/mod.rs:144-202`）。
6. `Presence::new(hulls, shown)` 载入舰船属性；`relations::load` 读玩家关系；读区域密度、名字表、角色头像类型（`bots/mod.rs:148-157`）。
7. `Sim::new` 建运行时，`sim.run()` 进入主循环（`bots/mod.rs:158-159`）。

配置项（`config.rs:143-149`、`config.rs:171-175`，YAML 为 camelCase）：

| YAML 键 | 环境变量 | 默认 | 含义 |
|---|---|---|---|
| `bots.count` | `RMR_BOTS` | `0` | 目标 bot 数；只在首次启动生成，之后保留 |
| `bots.speed` | `RMR_BOTS_SPEED` | `1.0` | bot 时钟相对真实时间的倍率 |
| `bots.shownPerSystem` | `RMR_BOTS_SHOWN` | `120` | 单个星系最多同时显示多少条 bot 船 |
| `bots.piratesAttackPlayers` | `RMR_BOTS_PIRATES_ATTACK` | `true` | 低安海盗是否主动打玩家 |
| `bots.dashboardControls` | `RMR_BOTS_CONTROLS` | `false` | web 仪表盘是否可操纵 bot |

环境变量通过 `FromStr` 覆盖（`config.rs:230-234`、`config.rs:301-306`），布尔值只接受 `true`/`false` 这类可解析文本。

### 运行时挂载点

`Sim` 不直接持有连接，而是把共享状态挂到 `WorldState`，让服务层与 web 只读地取用（`world.rs:100-115`）：

| 字段 | 类型 | 写入者 | 读取者 |
|---|---|---|---|
| `bot_counts` | `HashMap<星系, (在太空, 在站)>` | `publish_counts`，每 10 s（`mod.rs:901-951`） | 星图人数、`online_count`（`world.rs:241-245`） |
| `bot_stats` | `BotStats` | 同上 | `/api/summary`、`/api/wars`、`/api/sieges` |
| `bot_roster` | `Arc<Vec<LocalBot>>` | 启动、政治 tick（`mod.rs:350`、`531`） | Local 名单、`/api/pilots` |
| `bot_local` | `HashMap<星系, Vec<下标>>` | `publish_counts`，每 10 s（`mod.rs:937-946`） | `chat::local_members`（`chat.rs:650-652`） |
| `bot_index` | `HashMap<角色ID, 下标>` | 启动（`mod.rs:351`） | gang 邀请识别 bot（`svc/gang.rs:164`） |
| `hire_requests` | `Vec<(玩家, bot)>` | `svc/gang.rs:259` | `hire::run`（`hire.rs:72`） |
| `bot_panels` | `BotPanels`（四个 JSON） | `flush_all`（`mod.rs:790-796`） | `/api/market|relations|followed|events` |

启动时会打印三行可核对的事实：地图规模与读图耗时（`mod.rs:170`）、读回的 bot 数（`mod.rs:173`）、生成进度（`population.rs:261`，形如“made N of M (X/s)”）。

“生成并保留”的语义是**只增不减**：`population::ensure` 先 `SELECT count(*) FROM "bots"`，`have >= target` 就返回（`bots/population.rs:217-223`）；调小 `count` 不会删除已有 bot。

`schema::ensure` 逐条执行幂等 SQL（`bots/schema.rs:36-41`）：给 `bots` 加 `tier`，建 `botStock`、`botRelations`、`botRegionDensity`，并把 `killLog` 的序列校正到当前最大 `killID`（`bots/schema.rs:7-34`）。

## 时间模型

- **心跳 250 ms**：`TICK = 250ms`（`bots/mod.rs:56`），`tokio::time::interval` 配 `MissedTickBehavior::Skip`（`bots/mod.rs:357-358`），积压的 tick 不会连发。
- **模拟时钟**：每 tick `clock += 实际经过秒数 × speed`（`bots/mod.rs:366`）。`now` 取 `clock as u32` 的整秒；bot 的等待时间也是整秒。
- **到点队列**：`BinaryHeap<Reverse<(时刻, bot 下标, 代数)>>`（`bots/mod.rs:252`）。每次重排 `generation[i] += 1` 并压入新条目（`bots/mod.rs:324-329`）；出队时代数不符即丢弃（`bots/mod.rs:440-442`），因此同一步被多次重排不会重复执行。
- **每 tick**：`step_due(now)` 推进所有到期 bot（`bots/mod.rs:433`），`behaviour::step` 的返回值下限为 1 秒（`bots/mod.rs:445`）。
- **每 60 bot 秒**：`skirmish(now)`——无人观看的遭遇战、海盗袭击每分钟结算、玩家猎杀（`bots/mod.rs:371-374`，`SKIRMISH_EVERY = 60`，`bots/mod.rs:64`）。
- **每 600 bot 秒**：`politics_tick(now)`——战争起止、主权维护与围城、经济慢半拍、入团/招募、事件、关系冷却（`bots/mod.rs:378-381`，`POLITICS_EVERY = 600`，`bots/mod.rs:63`）。
- **每 1 真实秒**：`sync`——防御舰队、攻城战、控制请求、雇佣、presence 同步、玩家击杀入账、stance 发布（`bots/mod.rs:383-386`，`SYNC = 1s`，`bots/mod.rs:66`）。
- **每 10 真实秒**：`flush_all`——把脏 bot 批量写回，保存经济/关系/击杀，重建面板与星图计数（`bots/mod.rs:387-400`，`FLUSH = 10s`）。
- **每 120 真实秒**：在 flush 分支里回读 bot 钱包，吸收玩家付给它们的钱（`bots/mod.rs:394-399`，`BALANCES = 120s`）。
- **每 60 真实秒**：`report`——日志与 `/bots status` 的摘要，然后清零本轮统计（`bots/mod.rs:401-427`，`REPORT = 60s`）。

关键点：`speed` 只缩放 bot 时钟与按 bot 秒安排的行为，`sync`/`flush`/报告始终按真实时间走。`politics.hour` 由 `day0 + clock` 换算成 UTC 小时（`bots/mod.rs:368`），所以加速时一天会更快过完。

| 任务 | 触发条件 | 时钟 | 作用 |
|---|---|---|---|
| 到点推进 | 每 250 ms 检查堆顶 | bot 秒 | 到期 bot 逐个 `step`，压回下一次 |
| 遭遇战 | `now ≥ next_skirmish` | bot 秒（每 60） | `skirmish` + `events::raids` + `relations::hunt` |
| 政治 | `now ≥ next_politics` | bot 秒（每 600） | 战争/主权/经济/招募/事件 |
| 同步 | 每 1 s | 真实秒 | 防御、攻城、控制、雇佣、presence、击杀、stance |
| 保存 | 每 10 s | 真实秒 | 脏 bot、舰船、经济、关系、killlog、面板、星图 |
| 钱包回读 | 每 120 s（挂在保存里） | 真实秒 | 吸收玩家付款 |
| 摘要 | 每 60 s | 真实秒 | 日志与 `/bots status` |

暂停（`/bots off`）只清 `RUNNING`：bot 时钟不再前进（`mod.rs:364-366`），但 `sync` 仍会以 `running = false` 调用（跳过防御/攻城/控制/雇佣），`flush_all` 照常保存与更新面板（`mod.rs:758-798`），因此数据库里的角色与钱包不会丢。注意星图计数与 Local 名单由 `publish_counts` 的 `running` 过滤生成（`mod.rs:901-949`），暂停期间它们会被清空，恢复后下一次 flush 重建。

## 人口与身份

- **角色来源**：全部挂在账号 `rmr-bots` 下（`bots/population.rs:35`），该账号 `password = ''`、`banned = 1`，不能用于登录（`bots/population.rs:224-235`）。
- **命名**：从 `character_` 中 `accountID IS NULL` 的 NPC 角色按种族收集首名/末名（`bots/population.rs:102-118`）；随机拼接，经 `name_shape_ok` 校验且全库不重名，最多尝试 40 次，前 30 次用本种族名，之后允许换种族（`bots/population.rs:203-214`）。
- **外观**：从同血脉/性别的 NPC 角色复制 30 多个外观列（`LOOKS`，`bots/population.rs:279-283`），角色 `typeID` 也随该 NPC（决定 Local 头像）。
- **血统与种族**：`chrBloodlines` 中 1–8 号，随机取一（`bots/population.rs:130-135`、`248`）。
- **军团**：初始进入其血统的“学校军团”（`chrBloodlines.corporationID`，`bots/population.rs:311-316`），并写 `chrEmployment`、`chrCorporationRoles`、`eveNames`、`corporation.memberCount`（`bots/population.rs:320-341`）。bot 自己的军团与联盟不在生成阶段创建，而由 `politics::form` 一次性组建（见下节）。
- **属性**：`balance = 10^[5.5, 8.5]`，海盗 `securityRating ∈ [-8, -2]`，其他 `[-0.5, 3]`，`share ∈ [0.1, 0.5]`（`bots/population.rs:254-257`）。**技能只存在于模拟中**：不写技能表（`bots/population.rs:7-8`）。
- **职业分布**：矿工 30%、商人 15%、运输 15%、刷怪 20%、探索 10%、海盗 10%（`bots/population.rs:24-31`）。

| Role | 占比 | 初始舰船组 | 舰船阶梯（`ships::ladder`） |
|---|---|---|---|
| `Miner` | 30% | 护卫 25 / 采掘驳船 463 | 护卫 → 驳船 → 采掘者（`ships.rs:109`） |
| `Trader` | 15% | 穿梭机 31 / 工业 28 | 穿梭机 → 工业（`ships.rs:112`） |
| `Hauler` | 15% | 工业 28 | 工业三档，按货舱大小分三份（`ships.rs:111`、`204-211`） |
| `Ratter` | 20% | 护卫 26 / 战列巡洋 419 / 巡洋 27 | 护卫 → 驱逐 → 巡洋 → 战巡 → 战列（`ships.rs:107`） |
| `Explorer` | 10% | 护卫 25 | 护卫 → 驱逐 → 巡洋（`ships.rs:108`） |
| `Pirate` | 10% | 护卫 25 / 巡洋 26 | 同战斗阶梯（`ships.rs:107`） |

- **住址**：按职业与星系治安/枢纽加权抽空间站（`bots/population.rs:146-162`）：商人在枢纽站权重 400、枢纽星系 20；刷怪在零安 1.5、低安 1.0、高安 0.1；海盗在高安为 0。
- **五大枢纽**：Jita 4-4、Amarr VIII、Dodixie IX-20、Rens VI-8、Hek VIII-12（`60003760/60008494/60011866/60004588/60005686`，`population.rs:34`）；只有库里确实存在的空间站才计入 `atlas.hubs`（`population.rs:83`）。
- **初始舰船**：按 role 的舰船组 + 种族从 `invTypes` 抽取（`bots/population.rs:189-201`）；矿工 25/463，运输 28，商人 31/28，刷怪 26/419/27，探索 25，海盗 25/26。
- **批量写入**：每批 `BATCH = 5000`（`bots/population.rs:36`），一个事务里做多次集合式 `INSERT ... SELECT unnest(...)`（`bots/population.rs:285-343`），`character_` 与 `entity` 的 `dyn_id_seq` 一次预取 2N 个 ID。

**生成事务**（`population::insert`，`bots/population.rs:285-343`）一批一个事务，顺序是：

1. 从 `dyn_id_seq` 一次取 `2N` 个 ID，前 N 个给角色、后 N 个给舰船物品（`population.rs:287-293`）。
2. 插入 `character_`：位置取 `staStations` 的星座/区域，外观列从“脸”NPC 复制，`shipID` 指向舰船物品（`population.rs:307-319`）。
3. 用 CTE 一次写入 `entity`（角色身体、`flag = 4` 的舰船）、`eveNames`、`chrCorporationRoles`、`chrEmployment`，并累加 `corporation.memberCount`（`population.rs:320-336`）。
4. 插入 `bots` 行：`characterID/role/homeStationID/share`（`population.rs:337-341`）。

**读回**（`population::load`，`bots/population.rs:349-400`）：按 `characterID` 排序取前 `limit` 个，读 `role/homeStationID/share/stationID/balance/turf/tier`、角色名、军团、治安、`shipID` 与舰船 `typeID`；读回时一律 `online = false`，`activity = Docked`，若原站已不存在则退回 home。

**Local 显示**（`presence.rs` + `world.rs` + `chat.rs`）：

- 每次 flush 重建 `world.bot_local`：所有在线 bot 按星系分组，元素是 `bot_roster` 下标（`bots/mod.rs:937-946`）。
- 启动时与每次政治 tick 重建 `world.bot_roster`：`char_id/corp_id/alliance_id/name/type_id`（`bots/mod.rs:972-985`、`531-532`）。
- `world.bot_index` 是 `角色 ID → 下标`，供雇佣与按 ID 追踪（`bots/mod.rs:350-351`）。
- Local 成员列表由 `chat.rs:639-677` 从 `bot_local` + `bot_roster` 拼出，角色位固定为 `ROLE_LOGIN | ROLE_PLAYER`。
- 进出星系只在该星系有玩家打开 Local 时发 `OnLSC` 成员变动：`tell_local` 对比前后集合，用 `chat::announce_counted` 发 `JoinChannel`/`LeaveChannel`（`bots/mod.rs:955-969`）；服务器启动后的第一次不播报“到达”。

## 行为与状态机

`behaviour::step`（`bots/behaviour.rs:284`）每次只推进一个 bot，返回距下次的秒数。状态字段在 `Bot`（`bots/behaviour.rs:87-122`）。

| 状态 `Activity` | 进入/停留 | 退出条件与产出 |
|---|---|---|
| `Docked` | 在站内 | `leave`：先 `refit` 补船/升级；有矿石且非运输则卖给本站库存并停留 120–900 s；否则按 role 决定下一步（`behaviour.rs:364-406`） |
| `Travelling` | `go` 设 `route`，每步弹出一个星系 | 每跳 45–120 s（`jump_time`，`behaviour.rs:187-190`）；走完有 `dock_at` 就停靠，否则按 role 开始工作（`behaviour.rs:527-560`） |
| `Mining` | 在小行星带 | 产出 m³ 按舰船组：驳船 8–16k、采掘者 14–26k、其他 2–6k（`behaviour.rs:333-340`）；按治安选矿种（`economy::ore_for`），随后回 home |
| `Ratting` | 在带内 | 赏金 `[200k, 1.5M] × (1 + 1.5 × 吨位等级)`（`behaviour.rs:319-324`），随后回 home |
| `Camping` | 海盗在星门 | `roam`：85% 跳到相邻低安/零安，15% 回 home 停靠（`behaviour.rs:564-587`） |
| `Sieging` | 被 `battle::enlist` 征召 | 每 60 s 自检一次，直到 `release`（`behaviour.rs:328`、`344-360`） |
| `Escorting` | 被雇佣 | 同上，由 `hire::run` 决定结束（`behaviour.rs:328`） |

1. **在线/离线**：`!online` 时上线并给 `session_time() ∈ [30 min, 4 h]`（`behaviour.rs:286-291`、`243-245`）。
2. **下线**：`now >= session_end` 且不在 Travelling/Sieging/Escorting 时，先回 home 停靠，再按 `offline_time` 离线（`behaviour.rs:293-299`、`248-252`）；离线时长使一天的在线比例贴近 `share`。
3. **活跃度曲线**：`activity(hour, prime) = 1 + 0.75·cos(2π(hour-prime)/24)`（`behaviour.rs:194-197`），峰值为 1.75、谷值 0.25、日均 1。实际在线概率 = `share × 区域密度 × activity`，夹在 `[0.01, 0.97]`（`behaviour.rs:219-223`）。
4. **黄金时段**：`PRIME_TIMES = [19, 2, 10, 16]`（UTC，欧洲/美东/澳洲/俄罗斯），联盟按其 ID 取一个；个人按 `id % 10` 分配（`behaviour.rs:201-211`）。
5. **移动**：`go` 用 `gates::route` 求路径（`behaviour.rs:509-525`）；不可达则留在原地并“就地停靠”。
6. **采矿**：进入带后把 m³ 换算成矿种单位放入 `hold`；若该矿没有市场（`ore_for` 返回 `None`），直接按 `20 ISK/m³` 记收入（`behaviour.rs:303-318`）。
7. **运输**：在枢纽卸货拿货值 4%（`economy::unload`）；在非枢纽装走“非矿石、价值/体积比最高”的货（`economy::load`）；空舱时去 6 跳内最近的货源（同距离取更富的），没有就去枢纽或附近高安站跑一趟（`behaviour.rs:410-445`、`economy.rs:329-352`）。
8. **商人**：90% 概率在站里停留 30 min–2 h；10% 概率换一个枢纽并把家搬过去（有挂单的“trader”除外，`behaviour.rs:383-392`）。
9. **探索**：15 跳内随机选站，30% 概率把家搬过去（`behaviour.rs:393-399`）。
10. **补船/升级**：`refit` 在每次离站时调用；`hull_lost` 时从当前 tier 往下找买得起的最便宜档，最低档无条件可得；否则每次离站有 5% 概率考虑升一档，要求钱包 ≥ 新船价 × `CUSHION = 6`（`behaviour.rs:449-487`、`ships.rs:352`）。
11. **被击毁**：舰船损失 → `podded` 进入胶囊、清空货舱、飞回 home（`behaviour.rs:256-261`）；胶囊也被毁 → `reclone` 直接回 home 站内复活并标记 `hull_lost`（`behaviour.rs:265-275`）。

单次 `step` 的判定顺序固定（`behaviour.rs:284-330`）：

1. 不在线 → 上线并直接返回（不给任务）。
2. 会话超时且不在移动/攻城/护航 → 回家、停靠、离线。
3. 按 `activity` 分派：Travelling → `travel`；Docked → `leave`；Mining/Ratting → 结算产量或赏金后回家；Camping → `roam`；Sieging/Escorting → 固定 60 s。
4. 返回等待秒数；税、船型变更、presence 变更都在 `Sim::step_due` 里统一处理（`mod.rs:446-458`）。

### 舰船阶梯与装配

- 阶梯由 `ships::ladder` 定义（`ships.rs:105-114`），每档的 `hull_for` 按 (组, 种族) 抽，缺该种族时退到同组最小编号种族（`ships.rs:196-213`）。
- 舰船价来自经济品的 `ask`（NPC 卖价）；货舱、槽位、炮位读 `invTypes.capacity` 与 `dgmTypeAttributes` 的 12/13/14/38/102 号属性（`ships.rs:136-167`）。
- 装配按吨位分尺寸（`weight_class`，`ships.rs:117-125`）：护卫/驱逐用 Small、巡洋/战巡用 Medium、战列用 Large；武器按种族取能量/投射/混合，弹药数与炮数匹配（`ships.rs:291-299`）。
- 中槽：推进器 + （Caldari/Minmatar）护盾扩展与护盾回充；低槽：工业/采矿船放损伤控制，战斗船按种族放甲修+装甲板或回转/散热/磁性稳定（`ships.rs:306-333`）。
- 富有的 bot 选 meta 更高的“命名”模块（`fitting` 的 `rich` 分支，`ships.rs:267-270`）；`punch = 1 + 0.05 × 最高炮的 meta`（`ships.rs:339-347`）。
- 同一 bot、同一舰船永远得到同一套装配（以 `bot.id` 与 `typeID` 播种，`ships.rs:255`），这套装配就是它残骸里的战利品与 killmail 内容（`presence.rs:497-509`）。

**批量写回**：只有 `dirty` 的 bot 进入 `changed`（`bots/mod.rs:317-322`），每 10 s 用一次 `unnest` 批量 `UPDATE` 位置/在线/钱包增量（`bots/mod.rs:803-825`）；舰船变更单独批量写 `entity.typeID` 与 `bots.tier`（`bots/mod.rs:829-837`）。钱包写的是**增量** `isk - isk_saved`，因此玩家在这期间付款不会被覆盖（`bots/mod.rs:813-814`）。

### 被观察时的表现（presence）

- **观察范围**：`observed` = 至少有一名玩家在太空的星系（`presence.rs:262`）。这是“显示成船”的唯一条件；Local 中的 `bot_local` 则包含停靠的 bot，两者不同。
- **显示上限**：每系最多 `bots.shownPerSystem` 条；攻城舰队优先，名额满时可挤掉非舰队 bot（`presence.rs:344-384`、`470-472`）。
- **落点**：采矿/刷怪在带边，海盗在星门边，其余在该系随机天体旁；从星门进来用门的到达点并播 `effects.JumpIn`（`presence.rs:476-516`、`592-599`）。
- **航向**：`command_for` 给采矿/刷怪 4 km + `id%7` km 环绕带、海盗 6 km + `id%5`×2 km 环绕门、旅行者向下一跳的星门或目标站跃迁（`presence.rs:602-632`）；巡航速度比例 `CRUISE = 0.5`，跃迁为 1.0（`presence.rs:47`、`708`）。
- **战斗**：武装舰船带 `bot_brain`，被攻击即锁定反击；战斗期间 `steer` 只记录 `resume`，不打断当前机动（`presence.rs:529-540`、`702-707`）。海盗在治安 < 0.45 且 `bots.piratesAttackPlayers` 为真时见玩家就打；袭击事件的 `raiders` 在高安也打（`presence.rs:49-54`、`495-496`）。
- **击毁**：ballpark 把 `BotLoss` 压入 `park.bot_losses`，`sync` 抽干；舰船死亡生成胶囊（`eject`）并飞回 home，胶囊死亡则 `reclone` 回站；玩家造成的击杀进入 `relations::killed`（`presence.rs:267-290`、`bots/mod.rs:648-658`）。
- **离开视野**：跳出时按星门播 `effects.JumpOut` 再 `RemoveBalls`；不再被观察、已停靠或下线的 bot 直接移除（`presence.rs:292-341`、`519-526`）。
- **残骸**：`bot_loot` = 装配模块 + 货舱内容（`presence.rs:497-509`）；舰船被击毁时约一半作为战利品掉给击杀者，其余进 killmail；装配为空时按质量折算 10k–1M ISK 的随机掉落（`fight.rs:699-714`）。

## 战争与政治

**组建（只发生一次）**（`politics::form`，`politics.rs:340`）：

1. 约 70% 的 bot 被随机分进新军团（`IN_CORPS = 0.7`，`politics.rs:39`）。
2. 军团规模服从长尾 `tail(4.0, 0.8, 2500)`，最少 3 人（`politics.rs:236-238`、`366`）；战斗职业过半即战斗军团，否则工业军团（`politics.rs:369-370`）。
3. 联盟数 = `max(军团数 / 30, 3)`（`politics.rs:384`）；最多 25 个零安联盟（需该区域 ≥20 个零安系）、15 个海盗联盟（低安系 ≥10）、其余工业联盟（`politics.rs:385-397`）。
4. ≥8 人的军团有 60% 概率入盟；战斗军团 70% 进零安、否则海盗；其他 40% 进零安、否则工业（`politics.rs:409-420`）。无人加入的联盟不落库。
5. 零安/海盗成员（商人除外）搬到联盟区域的空间站，`turf` 设为该区域某个有带的星系（`politics.rs:424-443`）。
6. 联盟执行军团 = 成员最多的军团（`politics.rs:461-470`）；军团启动资金 = `members × 5M × rand(0.5, 2)`（`politics.rs:509`）。
7. 落库：`alliances`、`corporation`、`allianceMembers`、`chrEmployment`、`botGroups`，并改写 `character_` 与 `bots` 的 home/turf（`politics.rs:445-589`）。
8. `start_wars` 开局即开战（`politics.rs:614`）。

**演化（每 600 bot 秒）**（`politics::tick`，`politics.rs:651`）：

- 到期战争写 `crpWars.retracted/timeFinished` 并移出内存（`politics.rs:653-661`）。
- `start_wars` 维持 `零安联盟数/2 + 海盗联盟数/2` 场战争；60% 概率在相邻零安联盟间开战，否则海盗对其猎物（`politics.rs:694-725`）。
- 战争时长 3–14 天（`WAR_DAYS`，`politics.rs:49`）；`war_between` 写 `crpWars`，`mutual = 1`、声明时间回拨一天（跳过零售的“宣战次日生效”）、结束时间按 `days / speed` 缩放（`politics.rs:728-746`）。
- NPC 军团里的 bot 每天约 1% 加入 bot 军团（`RECRUIT_PER_DAY`，`politics.rs:51`、`668-689`），按职业匹配战斗/工业军团。

**无人观看的遭遇战**（`politics::skirmish`，`politics.rs:751`，每 60 bot 秒）：

- 只看**无玩家在太空**的星系、在线且不在站内、双方处于交战状态的 bot（`politics.rs:757-764`）。
- 每对阵营的交战概率 `min(0.05 × 较少方人数, 0.8)`（`politics.rs:776`）；按人数比例决定败方，败方损失 1–3 条，`reclone` 回家，同时记 `unseen_kills`、战争 `kills` 与全局 `lost`（`politics.rs:780-798`）。

**主权与围城**（`sov.rs`）：

- 落位：每个零安联盟在其 home 区域（无 NPC 势力）从 home 系 BFS 向外，每 25 名飞行员 1 个系、至少 3 个系、最多占该区域零安系的 60%（`PILOTS_PER_SYSTEM = 25`、`MIN_SYSTEMS = 3`、`MAX_SHARE = 0.6`，`sov.rs:30-33`、`171-201`）；按种族选大型控制塔（`TOWERS`，`sov.rs:35`），插在月亮外 30 km（`OFF_MOON`，`sov.rs:38`），claim 时间回拨到延迟之前，使地图一开始就显示主权（`sov.rs:156-157`、`197`）。
- 维护：每政治 tick 每个塔向所属军团扣 35,000 ISK（`UPKEEP_PER_TICK`，`sov.rs:55`、`252-259`），燃料补到 30 天（`FUEL_PERIODS = 30×24`）与 3,000 锶（`sov.rs:40-41`、`214-234`）；余额不足则不补，塔会耗尽。
- 围城计划：每场战争每 tick 3% 概率（`SIEGE_CHANCE = 0.03`，`sov.rs:45`），且必须在进攻方黄金时段 ±3 h（`in_prime`，`politics.rs:123-126`）；目标优先选与进攻方接壤的防守星系（`sov.rs:290-299`）；提前 15 bot 分钟公告（`SIEGE_NOTICE`，`sov.rs:47`、`307-309`）。富裕联盟按金库把参战人数放大，最多 2 倍（`RICH = 5e9`，`sov.rs:57`、`288-289`）。
- 结算（`sov::conclude`，`sov.rs:364`）：战果计入 `war.kills` 与 `politics.lost`；进攻失败只发新闻；获胜则删除该系防守方全部塔及其中物品（`destroy_towers`，`sov.rs:434-452`），从进攻方执行军团扣塔款（最多扣到 0，`sov.rs:386`），插新塔并按 `delay/speed` 回拨 claim（`sov.rs:387-393`）。
- 战后同步：`show_towers` 把该系 `posStructures` 重新载入，向客户端发 `TerminalExplosion`/`RemoveBalls`/新增结构（`sov.rs:400-431`）。

**被观看的攻城战**（`battle.rs`）：

- 舰队规模 = `参战人数 / 30`，夹在 6–40，且不超过 `(每系上限 - 10)/2`（`battle.rs:27-31`、`212-215`）。
- 防守方在力场外 15 km 集结（`DEFENDERS_OUT`），进攻方在 55 km 进入、35 km 环绕（`battle.rs:33-35`、`219-220`）。
- 一方清空：进攻方需对塔轰炸 60 s（`BOMBARD`）才判胜；超过 15 分钟（`MAX_FIGHT`）按剩余舰船多寡判；战斗中途没人观看则按剩余数量概率判（`battle.rs:125-140`）。
- 败方与胜方损失写入 `conclude`；幸存者 `presence.dismiss` + `behaviour::release` 回家（`battle.rs:148-158`）。
- 无人观看的围城直接按 `attackers/(attackers+defenders)` 概率判定，损失随机 1–4 / 3–10（`battle.rs:117-122`）。

**新闻与损失**：`Politics.news` 保存最近 60 条（`NEWS_KEPT`，`politics.rs:54`、`100-105`）；全局 `lost` 与各战争 `kills` 进 `world.bot_stats`（`bots/mod.rs:916-918`）。无人观看的击杀在 flush 时批量写入 `killLog` + `killLogParticipants`，每条伤害记 1000、final blow 记给胜方随机一人（`bots/mod.rs:858-897`）。

## 经济与关系

### economy

- **商品**：矿石（`ORES` 四档治安）、矿物（group 18）、舰船（各阶梯）。NPC 参考价取自 `market_orders` 中 `charID < 100_000_000` 且未结的订单：最低卖价为 `ask`、最高买价为 `bid`（`economy.rs:510-533`）。
- **矿带**：治安 ≥0.7 出 Veldspar/Scordite；0.45–0.7 再加 Pyroxeres/Plagioclase/Omber；0–0.45 为 Kernite/Jaspet/Hemorphite/Hedbergite/Omber；≤0 为 Gneiss/Dark Ochre/Spodumain/Crokite/Bistot/Arkonor（`economy.rs:72-81`、`256-268`）。
- **枢纽**：五个 NPC 枢纽 + 每个零安联盟的首都，按星门 BFS 把每个星系归给最近枢纽；每个枢纽选一个 trader（优先住在本站的 `Trader`，否则任一住民），它的钱包与挂单就是该枢纽的 bot 市场（`mod.rs:190-199`、`economy.rs:570-604`）。
- **精炼**：`invOreReprocessing` + `portionSize`，产出乘 `REFINE_YIELD = 0.8`（`economy.rs:50`、`429-445`）。
- **建船**：配方来自 `TL2MaterialsForTypeWithActivity`（activity 6、`damagePerJob = 1`、只取矿物），每个枢纽每 tick 最多建 4 艘（`BUILDS_PER_TICK`，`economy.rs:61`、`449-489`）；优先补短缺，需求每 tick 衰减为 0.9 倍（`DEMAND_KEPT`，`economy.rs:69`）。
- **价格**：`ask` 在 `[NPC bid×1.05, max(NPC ask×0.95, NPC bid×1.1)]` 之间，按库存稀缺度插值（`1/(1+库存/够用库存)`）；`bid = max(本 bot 卖价×0.75, NPC bid×1.02)`；四舍五入到 4 位有效数字（`economy.rs:209-233`、`496-504`）。
- **矿工收入**：卖入本站库存，按所属枢纽的 `bid × MINER_CUT(0.95)`（`economy.rs:52`、`276-286`）。
- **运输收入**：卸货价值的 `HAULER_CUT = 0.04`（`economy.rs:54`、`317-325`）；货源需价值 > 2M ISK（`economy.rs:349`）。
- **买船**：优先最近枢纽库存，其次任一枢纽库存最多者；都没货就按 NPC 价成交并记一次短缺（`economy.rs:357-388`）。枢纽卖单成交后钱付给该枢纽的 trader bot（`economy.rs:369-371`）。
- **公司税**：bot 军团固定 10%（`BOT_CORP_TAX`），玩家军团读 `corporation.taxRate`；其中 20%（`ALLIANCE_SHARE`）转给联盟执行军团（`economy.rs:64-65`、`391-405`）。
- **真实订单**：每个枢纽一个 trader bot；卖单覆盖该站全部库存，买单只覆盖矿石/矿物且补到“够用价值”（`ENOUGH_VALUE = 40M`，`ENOUGH_HULLS = 12`），托管上限为 trader 钱包的 30%（`ESCROW_SHARE`，`economy.rs:57-67`、`743-866`）；订单有效期 90 天、`range = -1`（仅本站）。
- **玩家交互**：`reconcile` 回读订单的 `volRemaining`/`orderState` 计算玩家买走/卖给 bot 的量（`economy.rs:677-719`）；`absorb` 删除玩家交给 trader 机库的物品并计入库存（`economy.rs:723-738`）；`fill_player_bids` 用 `ItemTxn` 把库存交给玩家、走钱包入账、写 `market_transactions` 并推送 `OnItemChange`（`economy.rs:906-975`）；bot 之间的成交也写 `market_transactions` 形成价格历史（`economy.rs:979-1003`）。

### relations

| 行为 | 数值与后果 |
|---|---|
| 玩家击杀 bot（heat） | 非胶囊 `1 + 0.25×吨位等级`，胶囊固定 2.0（`relations.rs:197`） |
| 玩家攻击 bot 的塔 | `+1.5`，同一 (阵营, 玩家) 每 10 bot 分钟最多一次（`relations.rs:234-243`） |
| `THREATENED` | 首次被杀：被害人发“复仇”邮件（`relations.rs:201-204`） |
| `HOSTILE`（heat ≥ 3） | 声望设为 −10（`ownerStandings`，塔的炮会开火），bot 见即打（`relations.rs:48`、`245-251`） |
| `BOUNTY`（heat ≥ 6） | 从执行军团钱包出 `heat × 2.5M` 挂真实赏金；钱不够按余额，低于 10 万则放弃（`relations.rs:49`、`524-549`） |
| `WAR`（heat ≥ 10） | 对玩家军团/联盟宣战 7 天，成本 2M（`relations.rs:50`、`555-586`） |
| 击杀该阵营的敌人（favor） | 每次 `1 + 0.25×等级`；达 2 给 +5 声望与雇佣合同（每杀按 `750k × (1+等级)^2` 付钱）；达 6 给 +10 与 `BLUE`，并邀请入团（`relations.rs:52-53`、`207-229`） |
| 冷却 | 每 bot 日 heat ×0.85、favor ×0.95；heat < 1 时撤销 HOSTILE/BOUNTY/WAR 并清声望（`relations.rs:55-56`、`271-293`） |

- **私人恩怨**：每次被杀记 2 bot 天（`GRUDGE_SECS`），仇恨者会主动猎杀（`relations.rs:58`、`194`）。
- **猎杀**：只发生在治安 < 0.45 的星系；每名玩家最多 5 个猎人、4 跳内、持续 30 bot 分钟（`HUNTERS/HUNT_JUMPS/HUNT_SECS`，`relations.rs:60-63`、`299-354`）；候选必须是海盗/刷怪/探索、在线、非胶囊、非攻城/护航且带武器。
- **空间中的敌我**：`publish` 把 heat/favor/恩怨编译成静态 `STANCES`，`stance()` 被 NPC/bot 大脑查询（`relations.rs:357-376`、`163-174`）。
- **邮件与赏金**都是真实客户端可见对象：`chat::deliver` 发 EVE mail，`bounties` + `character_.bounty` 记赏金（`relations.rs:619-670`、`541-547`）。
- **入团申请**：玩家申请 bot 军团时，若对该阵营 `HOSTILE` 则拒绝，否则接受（`relations.rs:676-698`）；NPC 军团的 bot 每政治 tick 以 `1/36` 概率向玩家军团投申请，待处理上限 3（`APPLY_CHANCE`/`PENDING_MAX`，`relations.rs:71-72`、`781-817`），被接受后走 `membership::change_corporation` 并把家搬到军团总部（若可达，`relations.rs:714-761`）。

### hire

- 入口：玩家在太空中对 bot 发出 gang 邀请 → `svc/gang.rs:259` 压入 `world.hire_requests`，由每秒 `sync` 中的 `hire::run` 处理（`bots/mod.rs:620-637`）。
- 成交条件：同星系、在太空、在线、非胶囊、带武器、未在攻城/护航、该玩家僚机 < 5、对玩家非敌对（`hire.rs:88-100`）。
- 费率按吨位：0.5M / 1M / 2.5M / 5M / 10M ISK 每小时（`RATES`，`hire.rs:25`、`44-47`），入队即扣第一小时。
- 行为：加入 gang，`Activity::Escorting`，跟随玩家过门/停靠（`hire.rs:176-186`）；战斗中优先打“最后攻击玩家的人”，其次玩家锁定的目标，150 km 内（`ASSIST_RANGE`，`hire.rs:30`、`225-243`）。
- 结束：玩家下线、被踢、gang 变化、或到点扣费失败 → 发邮件说明并回家/留站（`hire.rs:133-172`）。

### defense

- 触发：`park.tower_alarms`（玩家攻击 POS 时由 ballpark 记录）在每秒 `sync` 被 `defense::run` 抽干（`defense.rs:85-97`）。
- 归属判定：塔的联盟是 bot 联盟，或塔的军团有 bot 成员（`defense.rs:98-104`）。
- 响应：本星系已在线者（含停靠，`nearness ≤ 1`）立即响应（`defense.rs:141-146`）；20 s（`RESPONSE`）后从 3 跳内补人（`defense.rs:164-179`）；规模 `飞行员/60` 夹在 4–20、且不超过每系上限的一半（`defense.rs:25-27`、`139`）；在力场外 10 km 集结（`OUT`，`defense.rs:29`、`127`）。
- 解散：最后一次警报后 3 分钟（`CALM`）无新攻击，全体 `release` 回家（`defense.rs:152-163`）。
- 记录：攻击者若是玩家，记入 `relations.tower_attacked`（`bots/mod.rs:608-610`）。

### events

每次政治 tick 独立掷骰；也可由 `/bots event <kind>` 或 dashboard 指定强制执行（`events.rs:97-134`）。

| 事件 | 概率 | 规则 | 位置 |
|---|---|---|---|
| Betrayal | 0.004 | 交战中零安联盟的一个非执行军团叛投敌方，并按比例带走该联盟的星系（塔一并转手） | `events.rs:32`、`202-235` |
| Merger | 0.003 | 相邻、未交战、双方人数都不超过中位数的两个零安联盟合并，小的并入大的，塔与军团转移，小联盟解散 | `events.rs:33`、`245-275` |
| Collapse | 0.01 | 无塔且金库 < 1.5 亿的零安联盟解体，军团全部独立 | `events.rs:34`、`286-305` |
| Coalition | 0.01 | 某零安联盟持有 ≥20 系且 ≥1.8 倍于第二名时，最多 3 个邻居同时对其宣战 7–14 天，7 天内不重复 | `events.rs:35`、`307-335` |
| Raid | 0.006 | 海盗联盟派 15–45 艘船袭击 8 跳内 0.5–0.7 的高安系，持续 2 h | `events.rs:36-39`、`339-391` |

袭击的每分钟结算（`events::raids`，`events.rs:397`）：到达者改为 `Camping`；若该系无人观看，每次以 `min(0.1×袭击人数, 0.9)` 概率击杀一名非海盗、非护航的太空 bot，并以 15% 概率让 CONCORD 击毁一名袭击者；到时全体回家并发布战果（`events.rs:401-449`）。

## 控制面

**`/bots`（GM 斜杠命令）**：只有 `ROLE_GML`/`ROLE_LEGIONEER` 可用（`gm.rs:50-52`），分派在 `gm.rs:66-77`：

| 命令 | 行为 |
|---|---|
| `/bots on` | `bots::set_running(true)`，恢复模拟（`mod.rs:78-80`） |
| `/bots off` | 暂停推进；`sync`/`flush` 仍运行但不产生新行为（`mod.rs:364-365`、`582-639`） |
| `/bots status` | 返回最近一次 60 s 报告文本（`mod.rs:83-86`、`419-421`） |
| `/bots event <kind>` | `betrayal/merger/collapse/coalition/raid`，下一 tick 强制执行（`control.rs:44`、`mod.rs:673-677`） |
| `/bots war <a> \| <b>` | 按联盟/军团名、ticker 或 ID 找双方，立即开战 7 天并刷新 war 服务；同一方或已在交战则拒绝（`control.rs:45-48`、`mod.rs:678-696`） |
| `/bots density <region> <factor>` | 按区域名或 ID 设置活跃度倍率，夹在 `[0, 5]`；1 等于删除该行（`control.rs:49-53`、`mod.rs:697-719`） |
| `/bots follow <name>` | 名字精确/前缀匹配或角色 ID，最多同时追踪 12 个（`control.rs:61`、`mod.rs:720-737`） |
| `/bots unfollow <charID>` | 取消追踪（`control.rs:55`、`mod.rs:738-742`） |

请求先进静态队列 `QUEUE`（`control.rs:27-37`），由每秒 `sync` 里的 `Sim::requests` 取出执行（`bots/mod.rs:619`、`670`），因此命令是异步生效，回复只是“已请求”。

**web 控制**：`POST /api/control?do=<命令>`，`do` 与斜杠后的词表同构；未开 `bots.dashboardControls` 时返回 403，解析失败 400，成功 200 并回 `{"ok": ...}`（`web.rs:82-95`）。

**只读 JSON**：

- `/api/summary` 的 `bots` 块：`total/online/inSpace/running`（`web.rs:192-195`）。
- `/api/sieges`、`/api/wars` 分别读 `bot_stats.sieges`、`war_losses`（`web.rs:207`、`250`）；`/api/systems` 用 `WorldState::counts` 把 `bot_counts` 与在线玩家合并后取前 30 个星系（`world.rs:273-290`、`web.rs:326-330`）。
- `/api/market`、`/api/relations`、`/api/followed`、`/api/events` 直接克隆 `world.bot_panels` 的四个窗口（`web.rs:115-118`）。
- `/api/pilots?q=` 在 `bot_roster` 里按名字前缀取前 15 个，供 dashboard 选择追踪对象（`web.rs:377-384`）。

**panels 的 JSON 结构**（每次 flush 重建，`bots/mod.rs:787-796`、`panels.rs`）：

| 窗口 | 顶层字段 |
|---|---|
| `market` | 累计统计（`minedM3/refinedUnits/hauledM3/hullsBuilt/hullsBought/hullsFromNpcs/soldToPlayers/boughtFromPlayers/playerOrdersFilled/orders/corpTax`）、按价值排序的 `hubs`（每站最多 24 行：`name/kind/stock/ask/bid/npcAsk`）、`shortages`、`log`（最近 10 条） |
| `relations` | `standings`（最多 100 条，含 heat/favor/flags）、`wingmen`、`hunting`、`grudges` |
| `followed` | 每个被追踪 bot 的 id/name/role/corp/alliance/ship/tier/isk/online/activity/system/security/station 与最近 60 条历史 |
| `events` | `raids`（星系/人数/击杀/损失）与 `log`；运行时另加 `said`（最近 20 条运行消息）与 `controls`（是否允许控制） |

## 与数据库的交互

| 表 | 用途 | 写入方式 |
|---|---|---|
| `bots` | bot 的角色 ID、role、home、share、turf、tier | 生成时批量插入；离站补船时批量更新 `tier` |
| `character_` | 角色本体、位置、在线、钱包、治安、军团 | 生成时批量插入；每 10 s `unnest` 批量更新 `stationID/solarSystemID/constellationID/regionID/online/balance` |
| `entity` | 角色身体、舰船、模块/货物、POS | 生成时批量插入；换船时批量改 `typeID`；经济吸收玩家交付物时批量删除 |
| `eveNames` / `chrEmployment` / `chrCorporationRoles` | 名字缓存、雇佣史、军团角色 | 生成/换团时集合式写入 |
| `corporation` / `alliances` / `allianceMembers` | 军团与联盟、执行军团、成员关系、Logo、钱包 | 组建/合并/背叛/崩溃时批量写入；税收与建塔直接改 `balance` |
| `botGroups` | bot 军团/联盟及其 kind、home region | 组建时插入；解散时删除 |
| `botStock` | 每站每种商品的聚合库存 | 每 10 s 批量 upsert 脏行 |
| `botRelations` | 每个 (阵营, 玩家) 的 heat/favor/flags | 每 10 s 批量 upsert / 删除 |
| `botRegionDensity` | 区域活跃度倍率 | `/bots density` 时单行 upsert/删除 |
| `market_orders` | bot 的卖单/买单 | 每政治 tick 批量 update + insert，读回成交 |
| `market_transactions` | bot 成交与玩家成交的价格历史 | 批量插入 |
| `market_journal` | 玩家军团收税流水 | 有税时批量插入 |
| `killLog` / `killLogParticipants` | 无人观看战斗的击杀记录 | 每 10 s 批量插入，共享 `killID` 序列 |
| `crpWars` | bot 战争与对玩家战争 | 开战/结束时写入 |
| `crpApplications` | 玩家申请 bot 军团、bot 申请玩家军团 | 单条 upsert，结果实时通知客户端 |
| `ownerStandings` / `bounties` | 阵营对玩家声望、赏金 | 关系升级时写入 |
| `posStructures` | bot 控制塔、燃料、claim | 插塔/毁塔/补燃料时写入 |

批量策略：常规状态用 `UPDATE ... FROM unnest($1::int[], ...)` 一次成百上千行（`mod.rs:803-825`、`economy.rs:609-621`、`relations.rs:399-430`）；建塔/毁塔/军团变更是少量语句的事务；市场订单用一条 `INSERT ... SELECT unnest(...) WITH ORDINALITY ... RETURNING` 保住顺序与 ID（`economy.rs:838-857`）。

## 已知限制/未实现行为

1. **技能与装配不是真实角色数据**：bot 不写技能表，装配只在内存里按舰船组与种族生成，用于 `punch`、残骸战利品和 killmail；模块不会成为真实物品行（`ships.rs:253-347`、`presence.rs:497-509`）。
2. **战斗参数是近似**：`presence::arms` 只按舰船组给固定 DPS/射程/转速，海盗 ×1.5，再乘装配 `punch`；不是按 dogma 属性逐件计算（`presence.rs:546-569`）。
3. **显示有上限**：只有“有玩家在太空”的星系才把 bot 变成船，且每系最多 `bots.shownPerSystem` 条；看不见的 bot 只是数字（`presence.rs:262`、`344-384`、`470-472`）。
4. **经济是聚合模型**：库存记在 `botStock` 的 (站, 类型) 上，不区分归属；不支持除矿石/矿物/舰船外的商品；也没有逐 bot 的货舱持久化（`hold` 只在内存，重启丢失）。
5. **市场只挂一种订单形态**：卖单覆盖全部库存、买单只补矿石/矿物，`range = -1` 仅本站、固定 90 天；没有跨站撮合（`economy.rs:743-866`）。
6. **调整 `bots.count` 不会缩小人口**：`ensure` 只补不删；要减员必须手工清库。
7. **加速只影响 bot 时钟**：`speed` 不影响 `sync`/`flush`/报告，也不影响零售客户端的实际时间；高倍率下 bot 的“一天”会在几分钟内过完。
8. **部分状态不持久**：`Siege`、`Defense`、`Hires`、`Following`、`Events.raids`、`presence` 的显示集合都只在内存，服务端重启即清空；战争、主权、库存、关系会从库里恢复。
9. **Local 名单重建有延迟**：`bot_roster` 只在启动与政治 tick（600 bot 秒）刷新，换团信息最多滞后一个政治 tick；`bot_local` 每 10 s 刷新。
10. **无人观看的损失是抽象的**：`skirmish`/`raid` 只写 killlog 与损失计数，不会生成残骸、掉落或真实伤害过程；玩家看到的战斗才走 ballpark 的真实舰船与武器。
11. **防御只对“已加载 park 里的塔”生效**：`tower_alarms` 由玩家实际开火产生；没有玩家在线的星系不会触发响应。
12. **`/bots follow` 有上限**：最多 12 个，历史仅 60 条；`unfollow` 只接受角色 ID。
13. **雇佣限制**：必须同星系且在太空，单玩家最多 5 名僚机；被雇佣的 bot 不参与攻城/防御征召（`activity` 检查，`hire.rs:94`、`battle.rs:183`、`defense.rs` 的 `pick`）。
14. **没有独立的 `war.rs`**：战争状态由 `politics::War` 与 `crpWars` 承载，攻城由 `sov::Siege` + `battle::Fight` 承载；文档或代码检索时不要按文件名找。
