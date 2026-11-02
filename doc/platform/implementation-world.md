# 世界状态与模拟实现

本文讲共同世界（谁在线、在哪里、聊天频道、星系的 ballpark）、每条连接自己的会话、以及把两者粘起来的推进机制：会话移动、destiny 流、心跳脉冲。协议编解码与 service 分发见 `doc/platform/implementation-protocol.md`、`doc/platform/implementation-services.md`，战斗/NPC/bot 细节见 `doc/platform/implementation-gameplay.md`、`doc/platform/implementation-bots.md`。

结论都取自当前代码，行号写在括号里；代码里没有依据的行为一律写"代码中未见"。

## 模块地图

| 文件 | 职责 | 关键入口 |
|---|---|---|
| `crates/eve-server/src/world.rs` | 全服共享状态：连接表、Presence、sees、聊天频道、各星系 Park、trade、gang、bot 统计；每连接一个推送队列 | `World`（`world.rs:173`）、`WorldState`（`world.rs:91`）、`notify`（`world.rs:317`） |
| `crates/eve-server/src/session.rs` | 一条连接的会话变量、`corp_role`、session change 的生成 | `Session`（`session.rs:18`）、`PERSIST_VARS`（`session.rs:10`） |
| `crates/eve-server/src/conn/mod.rs` | 连接任务：帧循环、请求分发、回包、消费推送队列；`Server` 全局依赖 | `Conn::run`（`conn/mod.rs:108`）、`serve`（`conn/mod.rs:126`）、`Server`（`conn/mod.rs:32`） |
| `crates/eve-server/src/conn/location.rs` | 改变会话位置的调用：选角色、出站、换船、进站、跳跃、强制移动 | `select_character`（`location.rs:32`）、`undock`（`:87`）、`dock`（`:171`）、`stargate_jump`（`:261`）、`forced_move`（`:365`） |
| `crates/eve-server/src/conn/auth.rs` | LLV 握手与账号登录，写 `userid/role/languageID` | `authenticate`（`auth.rs:54`） |
| `crates/eve-server/src/svc/space.rs` | `beyonce`/`ship` 绑定对象、Park 的建立与增删船、destiny 条目构造 | `ensure_park`（`space.rs:92`）、`set_state_entries`（`:301`）、`add_ship`（`:417`）、`steer`（`:562`） |
| `crates/eve-server/src/svc/moves.rs` | 容器间物品移动、装配、换弹药；一次 `ItemTxn` 内完成 | `container_write`（`moves.rs:39`）、`assemble_ship`（`:77`）、`run`（`:91`） |
| `crates/eve-server/src/svc/inflight.rs` | `dogmaIM` 在太空中的部分：锁目标、开模块；舰船 profile 的装配与保存 | `profile`（`inflight.rs:78`）、`ship_for_space`（`:181`）、`apply_profile`（`:199`）、`save_vitals`（`:225`） |
| `crates/eve-server/src/ballpark.rs` | 服务端 destiny：每星系的位置/速度/命令，`Park::Evolve` 的逐 tick 复刻 | `Park`（`ballpark.rs:307`）、`advance`（`:407`）、`step`（`:465`） |
| `crates/eve-server/src/destiny.rs` | SetState/AddBalls 里的二进制 ball 流编码 | `encode`（`destiny.rs:99`）、`write_ball`（`:109`）、`tick_now`（`:144`） |
| `crates/eve-server/src/items.rs` | 物品事务：加锁快照、提交时按列差异生成 `OnItemChange` | `ItemTxn`（`items.rs:37`）、`commit`（`:222`） |
| `crates/eve-server/src/dogma.rs` | 属性引擎：`Catalog` 属性类型表 + `Loadout` 逐件装配与计算 | `Catalog::load`（`dogma.rs:175`）、`Loadout::load_with_drones`（`:211`）、`value`（`:532`）、`compute`（`:546`） |
| `crates/eve-server/src/gates.rs` | 星门拓扑，一次读入后常驻；跳数/路径查询 | `graph`（`gates.rs:16`）、`jumps`（`:40`）、`route`（`:52`） |
| `crates/eve-server/src/heartbeat.rs` | 250 ms 脉冲：锁内决策、锁外落库；每分钟慢事务 | `run`（`heartbeat.rs:137`）、`pulse`（`:172`）、`perform`（`:187`） |
| `crates/eve-server/src/svc/gang.rs` | 内存 gang；与会话的耦合只通过 `Move::Gang` 和 `clients_of` | `logged_off`（`gang.rs:370`）、`set_session`（`:415`） |

`svc/mod.rs:58` 的注册表把 `space::ship`、`space::beyonce`、`inflight::dogma_im`、`moves` 等挂到对应 service 名上；会改会话的 `character::SelectCharacterID`、`beyonce::Dock/TurboDock/StargateJump`、`ship::Undock/Board` 不进注册表，由连接层直接接住（`conn/mod.rs:242`、`:245`、`:254`）。

## 并发模型

### 一把锁的范围

`World` 是 `Arc<Mutex<WorldState>>`（`world.rs:173`），锁是 **std 的 `Mutex`**，不是 `tokio::sync::Mutex`。`WorldState`（`world.rs:91`）里装的是：

- `clients: HashMap<i64, Client>`：每条连接的推送发送端、`Presence`、`sees`；
- `channels: HashMap<String, Channel>`：开着的聊天频道与成员；
- `trades`、`gangs`、`parks`（每个星系一个 `Park`）、`bot_counts`/`bot_stats`/`bot_roster`/`bot_local`/`bot_index`/`hire_requests`/`bot_panels`。

`Server` 里其余的东西不在锁内：`table`、`db`（共享的 `tokio_postgres::Client`）、`db_url`、`node_id`、`bulk`、`dogma`、`services`、配置派生值（`conn/mod.rs:32`）。静态表与 dogma 目录只在启动时装载（`main.rs:95`、`:99`），运行期只读。

### 锁内做什么、锁外做什么

| 在锁内（`World::lock`，`world.rs:178`） | 在锁外 |
|---|---|
| `Park::advance`/`step`、下命令、增删船（`space.rs:417`、`:431`、`:450`） | 全部数据库 I/O：角色行、`store_docked`、`ItemTxn`、属性保存 |
| 读写 `Presence`/`sees`（`world.rs:208`、`:219`） | `Loadout`/dogma 的载入与计算（只把结果搬进 Park，`inflight.rs:798`） |
| 频道加入/退出（`world.rs:354`、`:364`） | 睡眠：进站接近（`location.rs:222`）、跳跃演出（`location.rs:313`） |
| gang 状态（`gang.rs:379`、`:401`） | marshal 编码与 socket 写（`conn/mod.rs:445`、`:452`） |
| 给每连接队列 `send` 一条推送（`world.rs:320`、`:330`、`:337`） | 心跳 `Job` 的执行（`heartbeat.rs:187`） |

"持锁不 `await`"既是模块头的约定（`world.rs:5`），也被类型系统在启动路径上兜住：每条连接都是 `tokio::spawn(Conn::new(..).run())`（`main.rs:136`），`std::sync::MutexGuard` 不是 `Send`，跨 `await` 持有守卫的连接 future 无法通过编译。实际写法都是"进函数取锁 → 算完 → 表达式结束即释放"，例如 `space::steer`（`space.rs:562`）在锁内 `park.advance` + `park.command` + `broadcast`，函数返回时守卫就释放。

### 通知只入队

网络发送从不发生在锁内：`notify`（`world.rs:317`）只是对目标连接 `tx.send(Push::Notify(..))`，`call`（`:327`）和 `push_move`（`:335`）同理。真正的编码与写套接字在连接任务里：`send_notification`（`conn/mod.rs:463`）把事件名塞进 `Broadcast` 窄播地址。队列是 `tokio::sync::mpsc::unbounded_channel`（`world.rs:186`），因此**没有背压**：接收端慢下来只会让内存里的 `Push` 增长，发送端从不阻塞，也不会失败（失败仅发生在连接已从 `clients` 移除时，`let _ =` 吞掉，`world.rs:320`）。

### 跨连接顺序

同一把锁把所有状态迁移串行化：谁先进锁，谁就先对所有目标 `send`。因此"A 看到 B 离开"与"B 的会话变更"这些事件，在**每个接收连接自己的队列里**顺序一致；两个不同连接之间的相对时序仍取决于各自的请求何时拿到锁。接收侧的消费点在 `serve` 的 `select!`（`conn/mod.rs:136`）：一次只处理一条 `Push`，与读帧互斥，所以在处理某个 `CallReq` 期间到达的推送会排在后面（见"已知限制"）。

### 锁中毒

`World::lock` 是 `self.state.lock().expect("world lock poisoned")`（`world.rs:179`）。持锁线程 panic 会毒化互斥量，之后**每次取锁都 panic**；代码中没有 `into_inner`/恢复路径，即一次锁内 panic 会扩散成全局不可用。避免手段只有"锁内不做会 panic 的事"：锁内是纯内存操作，`expect` 只出现在"已在上一步检查过"的地方（如 `location.rs:204`）。

## 连接在世界中的表示

### client_id

`client_id = seq * 10_000_000 + node_id`（`conn/mod.rs:85`）。`seq` 是 accept 循环里从 1 递增的计数器（`main.rs:125`、`:135`），`node_id` 来自配置（`conn/mod.rs:38`）。同一个 `seq` 也被用作 `Session::sid`（`conn/mod.rs:100`）。连接的 `tracing` span 从一开始就带 `client`/`peer`，登录后补 `user`，选角后补 `char`（`conn/mod.rs:86`、`:96`、`location.rs:73`）。

### Presence

注册连接只建队列（`world.rs:185`）；`Presence` 要等到第一次 session change 才写入。字段（`world.rs:65`）：

| 字段 | 来源 | 说明 |
|---|---|---|
| `char_id` | `session.char_id` | 未选角色时整条 `Presence` 为 `None`（`conn/mod.rs:418`） |
| `corp_id` | `session.corp_id` | 同样必需，缺失则 `None` |
| `solar_system_id` | `session.solar_system_id2` | **总是**有值的那份系统号；停靠时 `solar_system_id` 为 `None` |
| `docked` | `session.station_id.is_some()` | 舱内/太空的判据 |
| `station_id` | `session.station_id` | 停靠时的空间站 |
| `role` | `session.role` | 账号角色位，`with_role` 用它筛（`world.rs:248`） |

`Presence` 只在 `send_session_change_from` 里刷新（`conn/mod.rs:409`）：先构造 session change，再 `world.set_presence(..)`，最后发包。也就是说**任何不经过该函数的位置变化都不会被世界看到**——当前所有位置改动都走这条路径（`location.rs:75`、`:121`、`:162`、`:255`、`:326`、`:380`；`Move::Teleport` 内部同样走 `teleport` → `send_session_change_from`，`location.rs:427`/`:433`）。

### sees 语义

`Client.sees: Option<i64>`（`world.rs:81`）记录"这个客户端已经收到过哪个星系的 ballpark"。`set_presence` 会在停靠或换星系时清掉它（`world.rs:211`）。真正置位只在 `push_set_state` 末尾（`space.rs:489`）。

这个门控是硬要求：客户端没有 ballpark 时收到 destiny 更新会在 michelle 里报错（`world.rs:79`）。因此 `WorldState::in_space`（`world.rs:304`）要求三件事同时成立——`sees == 该星系`、`presence.solar_system_id == 该星系`、`!docked`——destiny 广播的收件人列表就是它（`space.rs:164`）。

### 断线清理

`Conn::run` 在 `serve` 返回后无条件调用 `leave_world`（`conn/mod.rs:114`），顺序固定：

1. `world.disconnect(client_id)`（`world.rs:193`）：先在 gang 里 `logged_off`（`:195`），移除连接，再把该连接从所有频道摘掉并返回"频道 + 剩下的人"（`:198`），删掉空频道（`:204`）。
2. 若会话在太空（有 `solar_system_id`、有 `ship_id`、`station_id` 为空，`conn/mod.rs:172`），从 Park 里 `remove_ship`（`space.rs:450`），并把 `Fighter` 的损伤用 `tokio::spawn` 异步入库（`conn/mod.rs:176`、`:178`）。
3. 结束它的交易：`pvptrade::left_station` 同样 `spawn`（`conn/mod.rs:184`）。
4. 对第 1 步返回的每个频道，用 `chat::announce` 发 `LeaveChannel`（`conn/mod.rs:186`）。

停靠中掉线不在 Park 里留船，只走频道与 gang 清理。

### 聊天频道

频道以 `channel_key`（`Value` 的 `Debug` 字符串，`world.rs:410`）为键，值里存 `id` 与成员集合（`world.rs:84`）。Local 的频道 ID 形如 `(('solarsystemid2', id),)`，`local_system`（`world.rs:399`）只认这个形状——它给 `local_channels`（`:377`）用，后者是 bot/web 取"哪些星系有 Local 开着"的接口。普通频道 ID 是整数，`local_system` 返回 `None`。

## 会话变量

### PERSIST_VARS

`PERSIST_VARS`（`session.rs:10`）23 项，顺序即 session change 里的输出顺序：

`userid, languageID, regionid, constellationid, role, charid, allianceid, corpid, gangid, gangrole, shipid, stationid, solarsystemid, solarsystemid2, address, callback, userType, hqID, baseID, rolesAtAll, rolesAtHQ, rolesAtBase, rolesAtOther`

`Session::attr`（`session.rs:71`）负责把字段变成 `Value`：整数用 `Value::int_or_none`；`role` 与四个 `rolesAt*` 用 `Value::Long`（位掩码，避免 32 位溢出）；`languageID`/`address` 用 `Value::Bytes`；`callback` 在结构体里没有对应字段，恒为 `Value::None`（`session.rs:101`）。

### login change 与增量 change

两种生成方式，输出形状相同：

| 函数 | old 侧取值 | 用途 |
|---|---|---|
| `login_change`（`session.rs:126`） | `default_for(name)`：`role` = `ROLE_LOGIN`(1)，四个 `rolesAt*` = 0，其余 `None`（`:150`） | 登录后一次性把非默认变量报给客户端 |
| `change_from(old)`（`session.rs:105`） | 调用方在改动前克隆的 `Session` | 每次位置/归属变化只报差异 |

两者都只输出"值确实不同"的项，包成 `Dict{name: (old, new)}`；外层 `change_body_from`/`change_body`（`:119`、`:141`）再包成 `[(0, dict), []]`，作为 `SessionChangeNotification` 的 body（`conn/mod.rs:400`）。外层第二个元素是空 `List`，代码里没有其它用法。

### 客户端如何使用（代码体现的部分）

- 登录时 `authenticate` 写 `userid`、`role = ROLE_LOGIN|ROLE_PLAYER|账号 role`、`address`、`languageID`（`auth.rs:84`），随后把 `change_body` 挂到 `pending_session_change`（`auth.rs:98`），**不当场发**。
- 该包要等客户端的第一个非 `objectCaching` 调用才释放（`conn/mod.rs:368`，注释说明是等 `ConnectToServer` 返回）；这之前的所有 `objectCaching` 调用都跳过释放。
- 之后每次 `send_session_change_from(before)` 都要求调用方先 `clone` 出 `before`（`location.rs:33`、`:117`、`:160`、`:248`、`:321`、`:418`），所以差异是"本次动作"的差异，不会把历史累积进去。
- `Move::Gang` 与 `Move::Affiliation` 在无差异时不发包（`location.rs:386`、`:397`），客户端主动调用则总是发。

### corp_role

`corp_role`（`session.rs:55`）按停靠位置挑掩码：在 `hq_id` 站 → `rolesAtAll|rolesAtHQ`；在 `base_id` 站 → `rolesAtAll|rolesAtBase`；其它 → `rolesAtAll|rolesAtOther`。`has_corp_role(mask)` 要求 `mask != 0` 且全体位命中（`:67`）。注意 `load_affiliation` 把 `base_id` 设成与 `hq_id` 相同（`location.rs:470`），且 HQ 分支先判，所以 base 分支在当前加载路径下取不到。

## 会话移动时序

下面五条路径都从连接层的拦截开始（`conn/mod.rs:236`），结束时都发一次 `SessionChangeNotification`（`Presence` 就是在发它时刷新）。但"先动 Park 还是先改会话"并不统一：出站与换船先改会话再动 Park（`location.rs:121`→`:122`、`:160`），进站、跳跃与传送先 `remove_ship` 再改会话（`:234`→`:248`、`:314`→`:321`、`:414`→`:418`）。

### 1. 登录选角色

1. `character::SelectCharacterID`（`conn/mod.rs:242`）→ `select_character`（`location.rs:32`），先克隆 `before`（`:33`）。
2. 按 `characterID + accountID` 读 `character_`（`:35`）：站、星系、星座、区域、`shipID`、名字、`typeID`。
3. 填会话：`char_id/char_name/char_type_id`、`station_id`、`solar_system_id`、`constellation_id`、`region_id`、`solar_system_id2`（`:56`）；**停靠时把 `solar_system_id` 清空**（`:64`），所以太空/舱内只靠 `solar_system_id2` + `station_id` 区分。
4. 停靠则 `resolve_active_ship`（`:513`）在站内挑一条已装配（`categoryID=6 AND singleton=1`）的船，优先记录的那条，并写回 `character_.shipID`；否则直接用 `character_.shipID`（`:67`）。
5. `load_affiliation`（`:448`）读公司、联盟、公司总部站与四个 `rolesAt*`。
6. `send_session_change_from`（`:75`）：刷新 `Presence`，发增量 change，回 `None`。

### 2. 出站（Undock）

1. `ship::Undock`（`conn/mod.rs:256`）→ `undock`（`location.rs:87`），要求 `station_id` + `solar_system_id2` + `ship_id` 齐备（`:88`、`:94`）。
2. 锁外：`ensure_park` 建/取星系 Park，`inflight::ship_for_space` 造舰船（读 dogma 与 DB），`space::undock_point` 取站外出生点与朝向（`:101`）。
3. 位置=出生点，速度=朝向 × 最大速度（`:111`）。
4. `pvptrade::left_station` 结束该角色的站内交易（`:114`）。
5. 会话改成太空（`station_id=None`，两个系统号都置位，`:118`），发 session change（`:121`）。
6. `space::add_ship`（`:122` → `space.rs:417`）把船插进 Park，`AddBalls` 只发给**除自己以外**的 `in_space` 客户端（`space.rs:424`）。

顺序要点：session change 先于 `AddBalls`，所以别人看到船出现时，该玩家的 `Presence` 已经是"在太空"。

### 3. 换船（Board）

`ship::Board(shipID)`（`conn/mod.rs:257`）→ `board`（`location.rs:134`）。只有停靠时允许（`:135`）；一条带 `EXISTS` 校验的 `UPDATE character_ SET shipID=..` 同时检查"是自己的、在本站、`singleton=1`、`categoryID=6`"（`:138`）；通过后改会话 `ship_id` 并发 change（`:160`）。失败分三种错误路径（`:151`、`:156`）。若调用是 `MachoBindObject` 捎带 `Board`，返回 `bound::bind_result(..)`（`:164`）。

### 4. 进站（Dock）

1. `beyonce::Dock` / `TurboDock`（`conn/mod.rs:247`、`:249`）→ `dock(station_id, towed)`（`location.rs:171`）。
2. 锁内判定（`:180`）：`park.advance(tick_now())` 后确认目标确实是本站系的空间站（`space::is_station`，`space.rs:764`），再用 `surface_distance` 求船到站的表面距离。
3. 距离 > `DOCK_RANGE`(2500 m，`location.rs:27`) 且不是 `TurboDock`：锁内下 `Command::Follow{target: 站, range: 0}`、`eta_within(.., DOCK_APPROACH_LIMIT=600)`（`:29`）、广播 `FollowBall`、给自己排队 `OnRemoteMessage("DockingApproach")`（`:201`）；随后 `sleep(eta + 1)`（`:222`）。ETA 求不出来就拒绝。
4. 锁内取出起点（船位）与终点（站位），`space::remove_ship` 把船摘出 Park（`:226`），有战斗状态则先 `save_vitals`（`:241`）。
5. 给自己发 `OnDockingAccepted(start, end, stationID)`（`:246`）。
6. 改会话（`station_id=Some`，`solar_system_id=None`，系统号保留，`:248`），再 `store_docked`（`:479`）把船写入站内机库（`flag=FLAG_HANGAR`）、角色写回站与 `shipID`，最后发 change（`:255`）。

### 5. 跳跃（StargateJump）

1. `beyonce::StargateJump(fromGate, toGate)`（`conn/mod.rs:250`）→ `stargate_jump`（`location.rs:261`）。
2. 锁内 `advance` 后量船到 `fromGate` 的表面距离，超过 `JUMP_RANGE * RANGE_SLACK`（2500 m × 1.25，`:20`、`:22`）回 `NotCloseEnoughToJump`（`:278`）。
3. `space::resolve_jump`（`space.rs:695`）用 `mapJumps` + `mapDenormalize`（`groupID=10`）确认这条门确实通向目标系，算出目的星系/星座/区域与出点（`arrival_point`，`:719`：门外 `半径+1500 m`、朝太阳一侧）；同时 `ensure_park` 目的系（`location.rs:291`）。
4. 广播离场特效：门 `effects.GateActivity`、船 `effects.JumpOut`（`:309`、`:310`，注释指向 `spaceMgr.py:123`）。
5. `sleep(JUMP_OUT_TIME = 3s)`（`:25`、`:313`）。
6. `remove_ship` 取出船（`:314`）；改会话系统/星座/区域并发 change（`:321`）。
7. 若船上有"已应用"的模块效果，用 `inflight::profile` + `apply_profile` 重算（跃迁时停机的模块效果要撤掉，`:330`）。
8. 船位=出点、速度=0、命令=`Stop`、`arrived_through=Some(toGate)`，`add_ship` 入目的系 Park（`:346`），再只对**其他**在太空的客户端发 `effects.JumpIn`（`:350`）。
9. `arrived_through` 的消费在客户端的 SetState 里：`push_set_state` 取走它并补一条 `JumpIn`（`space.rs:479`、`:484`）。

### forced_move 与客户端主动调用的区别

| | 客户端主动调用 | `forced_move` |
|---|---|---|
| 触发 | `CallReq` 帧，`dispatch` → `handle_call`（`conn/mod.rs:236`） | 服务端排进队列的 `Push::Move`（`conn/mod.rs:139`） |
| 回包 | 必须回 `CallRsp`/错误（`conn/mod.rs:274`、`:483`） | 无回包 |
| 来源 | 玩家操作 | 战斗/损失、GM、gang、归属变更（`losses.rs:194`、`:303`；`gm.rs:259`；`gang.rs:417`；`world.rs:343`） |
| 典型前置 | 无（自己算距离/容量） | 世界或数据库已经改过（如 `losses.rs` 先把胶囊 `AddBalls` 广播给所有人，再 `push_move(ShipLost)`，`:192`、`:194`） |
| 会话无变化时 | 仍然发包 | `Gang`/`Affiliation` 会跳过（`location.rs:386`、`:397`） |

`forced_move` 的五个分支（`location.rs:365`）：`ShipLost`（换船到胶囊）、`Podded`（回克隆站、给/不给胶囊）、`Gang`（gangid/gangrole）、`Teleport`（GM `/tr:`，`:407`）、`Affiliation`（重读公司/联盟/角色位）。`Teleport` 把"出站"和"进站/进太空"合成一个动作：先 `remove_ship` 并保存损伤（`:414`），再按目标是否带站分别走 `store_docked` 或 `ensure_park` + `add_ship`（`:422`、`:430`）。

## ballpark 与 destiny

### Park 数据结构

`Park`（`ballpark.rs:307`）是"一个星系里会动的东西"：

| 字段 | 内容 |
|---|---|
| `solar_system_id`、`tick` | 星系号；`tick` 是"船状态有效的整秒"（`:310`） |
| `celestials` | 恒星/行星/卫星/小行星带/星门/空间站，来自 `mapDenormalize` 的 `groupID ∈ {6,7,8,9,10,15}`（`space.rs:23`、`:127`） |
| `ships` | `BTreeMap<i64, Ship>`；**按 ID 序遍历**，与 destiny 一致（`ballpark.rs:492`） |
| `rocks`、`cans`、`structures`、`sites` | 小行星、漂浮货柜、母星建筑、任务点 |
| `watch`、`belts`、`missiles`、`wildlife`、`rng` | 犯罪/战斗与 NPC 生态的载体 |
| `bot_losses`、`tower_alarms` | 给 bot 模拟/母星告警的收集槽 |

`Ship`（`:212`）除位置速度外还带：`ShipStats`（radius/mass/agility/max_velocity/warp_factor，`:144`）、`Pilot`（type/group/name/char/corp/alliance/security/bounty，`:179`）、`Command`（`:192`）、私有的 `goal`/`prev_vel`/`warp`（`:223`-`:226`）、可选的 `fight`/`npc`/`drone`、`harmonic`、`arrived_through`、`bot` 与 `bot_loot`。

Park 在第一个船到达时惰性创建：先锁外读 celestials、货柜、建筑、NPC 生态，最后一次进锁 `or_insert_with`（`space.rs:92`）；已存在就直接返回，所以**不会重建**，也不会在空星系销毁。

### tick 计算与演化

- 时间单位是整秒：`tick_now = FILETIME 秒`（`destiny.rs:144`），`stamp(tick) = tick as u32`（`:149`）。
- 推进是"按需追赶"：`Park::advance(tick)` 在 `tick <= self.tick` 时什么都不做，否则把起点钳到 `tick - MAX_CATCH_UP`（3600 秒，`ballpark.rs:30`、`:411`），再逐 tick `step()`。
- `step`（`:465`）三步：`thrusts`（每个船按模式算推力）→ `bounces`（将要相撞的巨型球补一份反弹推力）→ 对每船 `move_ship(push)`，最后 `tick += 1`。
- `thrusts`（`:480`）先把所有可作目标的东西（船/岩/柜/建筑/任务点/天体）收进一张表；按船 ID 顺序处理，`Stop` 只做垂直速度的 0.07 衰减（`:500`），`Point/Direction` 用 `steer`，`Follow/Orbit` 找目标、丢目标则 `lose_target`，`Warp` 在 `aligned()` 成立时 `enter_warp` 并让跟随者松手（`:516`、`:535`）。
- `bounces`（`:551`）把巨型船与岩/天体/固定建筑/力场球放一起，对每艘船逐个候选求"本 tick 内的接触时刻与推力"，取**最晚**一次接触（同刻取更硬的），乘 `BOUNCE=0.85`（`:50`、`:597`）。
- 数值常量都标了 destiny.dll 2.10.3913 的地址或公式来源（`:32`-`:62`），例如 `DT=1`、`FRICTION=1e6`、`IMMOVABLE=1e34`、`WARP_FACTOR_SPEED=0x1005a598`；这是"复刻而非近似"的依据（模块头 `:1`-`:19`）。

### 二进制 ball 流

格式在 `destiny.rs:1`-`:21` 有完整记录，来源明确写着 destiny.dll 的 `ReadFullStateFromStream` / `ReadBallFromStream` 反汇编：

```text
i32 ballID  u8 mode  f64 radius  f64 x,y,z  u8 flags
if mode != RIGID:  f64 mass  u8 cloak  i64 harmonic  i32 corporationID  i32 allianceID
if flags & FREE:   f64 maxVelocity  f64 vx,vy,vz  f64 agility  f64 speedFraction
u8 formationID (0xFF = none)
<per-mode payload>  (STOP/FIELD/RIGID 为空)
u8 nameLength  u16[nameLength] name (UTF-16LE)
```

实现要点：

- 包头是 `0u8`（packet type） + `u32` 小端 stamp，然后是若干条 ball（`destiny.rs:99`）。
- 只写 `STOP`(2)、`FIELD`(10)、`RIGID`(11) 三种 mode，因为其它 mode 需要 per-mode payload（`:110` 的 `debug_assert`）。
- 移动中的船也写 `STOP` + 当前速度，真正的命令用紧随其后的 opcode 发送（`:19`），避免 per-mode 负载。
- 名字按"字符数"记长度（UTF-16 code unit），超过 255 截断而不是回绕（`:136`）。
- flags 组合有明确含义：船 `FREE|GLOBAL|MASSIVE|INTERACTIVE`，跃迁中的船去掉 `MASSIVE`（`:45`-`:47`）；空间站/柜子用 `CELESTIAL_PASSABLE`（`:50`），与"空间站不让船反弹"的设计对应（`ballpark.rs:134`）。
- 力场球的 harmonic/corp/alliance 判据见 `passes`（`ballpark.rs:633`），`NO_HARMONIC=-1`、`-2` 过所有场（`destiny.rs:67`）。

### SetState / AddBalls / RemoveBalls

条目统一是 `(stamp, (opcode, args))`（`space::entry`，`space.rs:155`）；一次更新是 `DoDestinyUpdate([entries...], 0)`（`space.rs:164`）。

| 条目 | 内容 | 位置 |
|---|---|---|
| `SetState` | 一个 `key_val` 包：`state`（整 Park 的 ball 流）、`ego`（自己的船）、`slims`（每件的 SlimItem）、`solItem`（星系自身）、`aggressors`、`droneState`、`gangCorps`（空）、`charGangs`、`damageState`（每件血量）、`effectStates`（空） | `space.rs:301`-`:359` |
| `AddBalls` | `(ball 流, [slim], {shipID: 血量})` | `space.rs:368`-`:375` |
| `RemoveBalls` | `[shipID]` | `space.rs:381` |
| `OnSpecialFX` | `(shipID, None, None, targetID, None, [], guid, 0, 1, 0)`，用于门闪、跃出、跃入 | `space.rs:387`-`:404` |

SetState 之后对每条非 `Stop` 的船补 `command_entry` + `SetSpeedFraction`（`course_entries`，`space.rs:292`），否则客户端会把这些船当成静止的。`command_entry` 把内部 `Command` 翻成 `Stop/GotoDirection/GotoPoint/FollowBall/Orbit/WarpTo`；`WarpTo` 必须带 `warpFactor`，否则 destiny 按 2 AU/s 处理（`space.rs:279`）。

SetState 的触发只有两处：`beyonce::GetFormations` 与 `beyonce::UpdateStateRequest`（`space.rs:65`、`:71`）。`push_set_state`（`:466`）会取走 `arrived_through` 并补一条 `JumpIn`（`:479`），把 `sees` 置位（`:489`）。

### 玩家进出的广播

- 进：`add_ship`（`space.rs:417`）在锁内插船、`add_ball_entries`，收件人是 `in_space(星系)` 去掉自己（`:424`）。
- 出：`remove_ship`（`:450`）先 `fight::stand_down`（停火/清锁）再 `fight::detach`，广播 `RemoveBalls`，同样去掉自己（`:459`）。返回的 `Ship` 由调用方决定入库（进站/跳跃/断线）。
- 进站时自己收到的是 `OnDockingAccepted(start, end, stationID)`（`location.rs:246`），不是 `RemoveBalls`。
- 跳跃跨越两个星系：离场系广播 `GateActivity`+`JumpOut` 给所有人（含自己，`location.rs:311`），入场系只给**别人**发 `JumpIn`（`:353`），自己靠下一次 SetState 补（`space.rs:484`）。

## 物品与属性

### items：事务 + 差异事件

`ItemTxn`（`items.rs:37`）包一个 `tokio_postgres::Transaction`，并记两样东西：每个碰过的物品的"改动前快照"（`before: HashMap<i64, Option<Vec<Value>>>`）与触碰顺序（`order`）。

1. `item(id)`（`:55`）用 `SELECT ... FOR UPDATE OF e` 加行锁，**第一次**读时把 `invitem_cells` 存成快照（`:61`），新物品由 `create` 直接记为 `None`（`:186`）。
2. 所有写操作都先 `touch`（`:88`）保证快照存在：`move_to`（`:95`，改 `locationID`+`flag`）、`set_quantity`（`:107`，≤0 走 `destroy`）、`set_owner`（`:118`）、`set_singleton`（`:148`）、`destroy`（`:159`，先删 `entity_attributes` 再删 `entity`）。
3. `set_position`（`:128`）只写 `x/y/z`，**不进快照、不产生事件**（位置由 destiny 传达）。
4. `stack_onto`（`:193`）按 (owner, location, flag, typeID, singleton=0) 找同类堆，找到就加数量，否则 `create`（`:167`，主键取 `nextval('dyn_id_seq')`）。
5. `commit`（`:222`）先在同一事务里把 `order` 中所有行重读出来，比较前 8 列（`COMPARED_COLUMNS`，`:35`），然后提交，最后据此生成事件：改过的列 → `(列号, 旧值)`；消失 → 数量置 0 的旧行；新出现 → 位置 0、数量 0 的当前行（`:245`-`:253`）。事件由 `items::notify` 逐条排队成 `OnItemChange`（`:272`）。

事件形状依赖客户端 `invCache.py:111` 的读法（模块头 `:1`-`:8`）：数量 0 表示没了，旧位置 0 表示新的。

`ItemTxn` 需要 `&mut Client`，而 `Server.db` 是共享的 `&Client`，所以 `moves::run` 每次自己 `db::connect` 开一条连接（`moves.rs:95`），`fitting::set_online` 同样（`fitting.rs:340`）。

### moves：移动与装配

`container_write`（`moves.rs:39`）把客户端方法映射成 `Op`：`Add`/`MultiAdd`、`MergeItems`/`MultiMerge`、`StackAll`、`ReplaceCharges`（`:44`-`:72`）。`run`（`:91`）在一个事务里做完全部改动，提交后依次处理副作用：`OnItemChange`、拿别人货柜算盗窃（`concord::took_from`，`:109`）、清空货柜（`loot::clear_emptied`，`:110`）、交易报价变化（`:112`）、装配属性变化（`fitting::push_attribute_changes`，`:114`）。

目的地规则在 `destination`（`:212`）：站内机库不限容量；对船上的容器，`is_fitting_flag` 的槽位直接落到"装配"（带 `fitting: Some(holder)`）；货柜舱/无人机舱按 `invTypes.capacity`（或无人机属性 283，`:268`）；其它容器必须已装配且容量 > 0。可达性由 `reachable`（`:322`）判断：只能碰自己在本站机库一层/两层内的东西，或太空中自己船上的东西（模块头 `:5`）。

`assemble_ship`（`:77`）→ `Op::Assemble` → `assemble`（`:193`）：只处理本站、自己的、`categoryID=6` 且未装配的船；数量 > 1 拆出一条 `singleton=1` 的新物品，数量 = 1 直接置 `singleton`。

### dogma：Catalog 与 Loadout

`Catalog`（`dogma.rs:170`）只装 `dgmAttributeTypes`：`attributeID → (defaultValue, stackable)`（`:175`）。它是全局共享的只读表，启动时载入一次（`main.rs:99`）。

`Loadout`（`:187`）是一次"这台角色 + 这条船"的求值上下文：

1. 选件 SQL（`:220`）：角色本身、船本身、角色位置 `flag ∈ {7 技能, 61 训练中技能, 88 booster, 89 implant}`、船位置 `flag ∈ [11,35]`（槽位）与 `[92,99]`（rig），外加指定 drone。
2. 定角色（`:251`）：`itemID == charID` → `Character`；`== shipID` → `Ship`；类别 16 → `Skill`；drone → `Drone`；`locationID == charID` → `Implant`；类别 8 → `Charge{MAX}`；其余 `Module`。随后按 `flag` 把 `Charge` 绑到同 flag 的模块（`:279`）。
3. 基础属性两层叠加：先 `dgmTypeAttributes`（按 typeID），再 `entity_attributes`（按 itemID）覆盖（`:292`-`:320`）。
4. 效果集合来自 `dgmTypeEffects`（`:322`）；状态由 `active` 集合与 `isOnline` 属性决定（`:331`）：`Active` / `Online` / `Offline`，非模块一律 `Online`。
5. 修正器来自 `dgmTypeModifiers`（`:339`）：`func ∈ {ItemModifier, LocationGroupModifier, LocationRequiredSkillModifier, OwnerRequiredSkillModifier, LocationModifier}`、`domain ∈ {shipID, charID, itemID, otherID, targetID}`，其余丢弃（`:350`-`:365`）。

`wire`（`:444`）把每个修正器解析到 (目标件, 属性)：`domain` 决定改谁（船/角色/自身/同槽另一件），`func` 决定作用范围（单件/整船装配/同 group/按所需技能筛），`applies`（`:421`）决定此刻是否生效（passive 恒生效；online 在 `Online` 或未标记 `offWhileActive` 的 `Active` 下生效；active 只在 `Active`）。2.10 硬编码的两条也在这里补上：在线模块把自身 `cpu/power` 加到船的 `cpuLoad/powerLoad`，装了炮/发射器的模块各扣一个 hardpoint（`:505`-`:519`）。

`value`（`:532`）带 memo 与"环检测"（`busy` 集合，遇环回退基础值）；`compute`（`:546`）按 dogma 运算序 `-1,0,1,2,3,4,5,6,7` 逐个应用：`-1/7` 赋最后值，`2` 加、`3` 减，其余是乘/除/百分比（`:559`-`:580`）。不 stackable 的属性上，来自模块/无人机等"可叠加惩罚"来源的乘法因子走 `stacking_penalised`（`:601`）：正负分开排序，第 n 强的贡献乘 `exp(-(n/2.67)^2)`；船/弹药/技能/植入体/子系统与角色本身豁免（`:553`）。

`inflight::profile`（`inflight.rs:78`）把 Loadout 变成一条能飞的船：质量与速度受推进模块影响（`:121`-`:133`，`max_velocity *= 1 + factor * thrust / mass`），血量/电容从 `shieldCapacity`/`capacitorCapacity` 起，并用 `entity_attributes` 里存的上次护盾/电容覆盖（`:146`-`:154`），锁定上限取"船与角色技能的较小值"（`:155`）；`Vitals`/`Fighter` 其余字段直接取属性（`:158`-`:176`）。`ship_for_space`（`:181`）造新船；`apply_profile`（`:199`）把新数值搬到已在太空的船上，护盾/电容按比例缩放，保留锁定与模块运行状态。

### 保存

`save_vitals`（`inflight.rs:225`）写 `entity_attributes`：装甲/结构损伤总是写（0 时删行）；`docked=true` 时**删除**护盾与电容两行（进站回满），否则写当前值。调用点覆盖进站（`location.rs:242`）、传送（`:416`）、断线（`conn/mod.rs:178`，异步）。

## 心跳脉冲

### 频率与循环

`PULSE_MS = 250`（`heartbeat.rs:22`），`tokio::time::interval` 且 `MissedTickBehavior::Skip`（`:149`），即落后时丢弃错过的 tick 而不是补跑。

`heartbeat::run`（`:137`）的结构：

1. 用 `db::connect(db_url)` 单独拿一条数据库连接（`:138`），失败每 5 秒重试；`pvptrade::recover` 在启动时跑一次（`:147`）。
2. 每 250 ms：`pulse(&server.world, now)`（`:154`）→ 对返回的每个 `Job` 调 `perform`（`:155`）。
3. `pulses` 计数 +1；`pulses % AFFAIRS_EVERY == 1` 时跑每分钟的慢事务（`:158`）。`AFFAIRS_EVERY = 60_000 / 250 = 240`（`:25`），所以**第一个脉冲就跑一次**，之后每 240 个脉冲一次。

### 每脉冲做什么（锁内决策）

`pulse`（`:172`）：

1. 取锁，`tick = destiny::tick_now()`。
2. 对**每个** Park：`pos::step`（母星建筑的力场重建与定时状态，`pos.rs:446`；不要求有玩家）。
3. 若 Park 里没有任何玩家船（`players().next().is_none()`）就跳过，不再演化（`:178`）。
4. 否则 `park.advance(tick)` 把船推到当前秒，再 `fight::step(park, now, &mut out)` 跑战斗一帧。
5. `out.deliver(&w)`（`:184`）：把攒下的 destiny 条目按星系合并成 `DoDestinyUpdate` 广播（`heartbeat.rs:82`-`:88`）、把 `notes` 逐条排队（`:90`），返回 `Vec<Job>`。

`Out`（`:33`）只是"决策结果"的容器：`destiny`、`notes`、`jobs`、`hurt`、`drained`。全部在锁内生成，锁内不做任何 I/O。

### Out/Job 两阶段

| 阶段 | 位置 | 内容 |
|---|---|---|
| 决策（锁内） | `pulse`（`heartbeat.rs:172`） | 推进、战斗、装配/锁定/矿石/弹药等状态变化，写进 `Out` 与 `Job` |
| 投递（锁内但只入队） | `Out::deliver`（`:82`） | `world.notify` → 每连接队列；不写 socket |
| 落库（锁外） | `perform`（`:187`） | 用心跳自己的 `&mut Client` 执行 `Job` |

`Job` 变体（`:99`-`:135`）与落库动作一一对应（`:187`-`:213`）：`Ammo`（改弹药数量，走 `ItemTxn`，`:216`）、`Ore`（按货柜剩余空间算能装多少，装不下就停激光，`:232`）、`Bounty`（钱包 `market_journal` 入账 + 提升安全等级，`:274`、`:304`）、`Refit`（重算属性，`inflight::refit`）、`Lost`/`BotLost`（损失处理）、`Loot`/`Scrap`（货柜）、`DroneHome`/`DroneLost`、`Security`、`SiteCleared`、`Structure*`/`Reinforce`/`StructureAmmo`。

落库完成后如果要告诉玩家，`perform` 内部会再取一次锁只做 `notify`（如 `heartbeat.rs:289`、`:294`），不跨 `await` 持锁。

### 每分钟的慢事务

`heartbeat.rs:158`-`:167`，顺序固定：

1. `alliance::take_effect`：到期的联盟申请生效。
2. `alliance::bill_alliances`：联盟账单。
3. `war::bill_wars`：战争费用。
4. `starbase::burn_fuel`：母星燃料。
5. `starbase::sovereignty`：主权声明计时。
6. `votes::close_votes`：到期投票结算。
7. `guard::reload`、`guard::refresh_standings`：CONCORD/声望缓存刷新。

## 与数据库的交互

| 表 | 读/写 | 用途 | 位置 |
|---|---|---|---|
| `account` | 读（+自动建号） | 登录校验、账号 role | `db.rs:21` |
| `character_` | 读/写 | 选角、归属/角色位、换船、进站落库、安全等级 | `location.rs:35`、`:449`、`:139`、`:493`、`heartbeat.rs:308` |
| `entity` | 读/写 | 物品实例（类型/所有者/位置/flag/数量/singleton/x,y,z） | `items.rs:56`、`:171`、`:99` |
| `entity_attributes` | 读/写/删 | 物品实例属性；舰船血量/电容存储 | `items.rs:161`、`inflight.rs:108`、`:240`、`dogma.rs:310` |
| `invTypes` / `invGroups` | 读 | 类别、体积、容量、radius/mass、type 属性 | `moves.rs:260`、`inflight.rs:91`、`dogma.rs:222` |
| `dgmAttributeTypes` | 读 | 属性默认值与是否 stackable | `dogma.rs:177` |
| `dgmTypeAttributes` / `dgmTypeEffects` / `dgmTypeModifiers` | 读 | 基础属性、效果集合、修正器 | `dogma.rs:292`、`:322`、`:339` |
| `staStations` / `staStationTypes` | 读 | 站属主、出站点与朝向 | `space.rs:408`、`:737` |
| `mapDenormalize` | 读 | 天体位置/半径、跳门目标、站的坐标 | `space.rs:128`、`:642`、`:700` |
| `mapJumps` | 读 | 星门 → 目的门 | `space.rs:699`、`:132` |
| `mapSolarSystemJumps` | 读（一次性） | 星系图，跳数与路径 | `gates.rs:24` |
| `bookmarks` | 读 | `WarpToStuff("bookmark", ..)` | `space.rs:647` |
| `posStructures` | 读/写 | 母星建筑状态与时间戳 | `pos.rs:306`、`heartbeat.rs:317` |
| `insuranceContracts` | 读/删 | 舰船保险赔付 | `losses.rs:202`、`:216` |
| `market_journal` | 写 | 钱包流水（赏金、保险等） | `wallet.rs:512` |

写路径的共同点：**任何跨多行的改动都在一个事务里**（`ItemTxn` 或裸 `Transaction`），提交后才把事件推给客户端；数据库错误只记日志并给客户端一个笼统的 `CustomError`，不会让连接崩掉（`services.rs:139`、`conn/mod.rs:286`）。

## 已知限制/未实现行为

1. **destiny 只写了三种 mode**：`STOP`/`FIELD`/`RIGID`，其它 mode 在 debug 构建会触发 `debug_assert`（`destiny.rs:110`）；移动中的船靠"STOP + 当前速度 + 紧随的命令 opcode"表达（`:19`）。
2. **SetState 不会自动下发**：只有 `GetFormations`/`UpdateStateRequest` 触发（`space.rs:65`、`:71`）。出站/跳跃后若客户端不请求，`sees` 一直为空，该连接收不到任何 destiny 更新（`world.rs:304`）。
3. **`Presence` 只在 session change 时刷新**（`conn/mod.rs:411`）：任何绕过 `send_session_change_from` 的会话字段改动都会让世界状态过期。
4. **一次慢调用会阻塞该连接的推送处理**：进站接近最多 `sleep(eta+1)` 秒（上限 600 s，`location.rs:29`、`:222`），跳跃固定 3 s（`:313`）。`serve` 在这段时间里不 `select!`，推送堆在无界队列中，返回后才逐条处理。
5. **无背压**：连接队列 `unbounded_channel`（`world.rs:186`），慢客户端只会让内存增长；连接已移除时 `send` 失败被静默丢弃（`:320`）。
6. **锁中毒不恢复**：`expect("world lock poisoned")`（`world.rs:179`），一次锁内 panic 会让之后所有取锁 panic。
7. **`ClientCall` 通路已实现但无调用方**：`World::call`（`world.rs:327`）→ `Push::Call` → `conn::call_client`（`conn/mod.rs:298`）整条链路完整，但代码中未见任何业务调用 `world.call(..)`；需要告知客户端的场合都走 `world.notify`（如 `space.rs:164`、`conn/mod.rs:463`）。
8. **世界是纯内存的**：频道、trade、gang、Park、bot 统计都在 `WorldState` 里，重启即丢；只有物品/钱包/角色等写进了 PostgreSQL（`world.rs:91`）。gang 尤其没有落库（`gang.rs:1`-`:15`）。
9. **空星系冻结**：心跳跳过没有玩家船的 Park（`heartbeat.rs:178`），再进入时用 `advance` 一次追赶，但超过 `MAX_CATCH_UP`（3600 s）的部分直接跳过（`ballpark.rs:30`、`:411`），所以长时间无人星系里的 NPC/船位置是"跳"过来的。
10. **`corp_role` 的 base 分支取不到**：`load_affiliation` 把 `base_id` 置为 `hq_id`（`location.rs:470`），且 HQ 分支先匹配（`session.rs:57`）。
11. **`WarpToStuff` 只认 `item`/`bookmark`/`char`**：其它 kind 记一条 warn 后返回 `None`，调用变成 `ServiceNotFound`（`space.rs:664`、`:536`）。
12. **短距离 warp 变 GotoPoint**：目标在 100 km 内时 destiny 直接去点（`ballpark.rs:425`），服务端同样改成 `Command::Point`，不会出现跃迁演出。
13. **跳跃不校验门的所有权/状态**，只校验"`mapJumps` 里这条门通向那里且在本系且 `groupID=10`"（`space.rs:702`）；门的锁/舰队限制等代码中未见。
14. **出站/跳跃的瞬时窗口**：`send_session_change_from` 先刷新 `Presence`，`add_ship` 后执行（`location.rs:121`/`:122`、`:326`/`:347`），因此存在"世界里已在目的系、Park 里还没有这条船"的极短窗口；相关查询都用 `Option` 兜住，不会崩，但这一瞬间别人看不到该船。
15. **`is_movement` 是白名单**：`SetSpeedFraction/GotoDirection/GotoPoint/Stop/FollowBall/Orbit/WarpToStuff` 之外的运动方法不会被当成移动处理（`space.rs:82`）；`GetFormations` 返回空元组、`GetGangState` 返回 `None`（`:65`、`:74`）。
