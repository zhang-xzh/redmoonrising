# 战斗与玩法实现

本文描述 EVE 2.10 / build 3913 服务端当前实际运行的游戏玩法：一场战斗在每 250 ms 脉冲里怎么推进、NPC 与无人机怎么思考、船和 pod 怎么损失、犯罪怎么记、生产与母星怎么落库。公式与数值都来自 `crates/eve-server/src/**` 的常量或数据库列；代码里看不出来的行为明确写"代码中未见"。协议编解码、ballpark/destiny 运动学、dogma 属性计算、bot 经济与 web 面板不在本文范围，见 `doc/platform/implementation-overview.md` 与 `doc/platform/architecture.md`。

## 模块地图

| 文件 | 职责 | 被谁调用 |
|---|---|---|
| `crates/eve-server/src/combat.rs` | 纯战斗数值：伤害分层与抗性、护盾/电容回充、炮台命中与质量、导弹系数、锁定时间、角速度、RNG，以及 `Action`/`Active`/`Fighter` 数据模型和属性 ID 表 | `fight.rs`、`npc.rs`、`drones.rs`、`guard.rs`、`svc/inflight.rs`、`pos.rs`、`losses.rs`、`loot.rs`、bots |
| `crates/eve-server/src/fight.rs` | 单个星系一次脉冲的战斗推进：锁定、模块循环、投射效果、导弹、死亡与掉落回收 | `heartbeat::pulse`（`heartbeat.rs:182`） |
| `crates/eve-server/src/npc.rs` | 星系野生动物：小行星带矿石、海盗 rat 的类型/等级/生成/思考、CONCORD 船型、实体武器模板 | `svc::space::ensure_park` → `npc::load`/`populate`；`fight::step` → `npc::think` |
| `crates/eve-server/src/drones.rs` | 无人机发射、指令、每秒思考、回收与损失 | `svc::space` 的 `ship`/`entity`；`fight::step` → `drones::think`；heartbeat `Job` |
| `crates/eve-server/src/sites.rs` | 任务死亡空间站点：信标、站点 rat、清空回调 | `svc::agent_missions::open_site`/`close_site`/`site_cleared` |
| `crates/eve-server/src/pos.rs` | 玩家建筑在 park 内的状态机、定时器、力场、强化标记 | `heartbeat::pulse`（`pos::step`）、`space` 加载、`fight` 命中 |
| `crates/eve-server/src/svc/starbase.rs` | 发射/锚定/上线/下线/解锚/回收、燃料、强化、主权、`posMgr` | `dogmaIM` 的 Activate/Deactivate、`posMgr`、heartbeat 每分钟任务 |
| `crates/eve-server/src/loot.rs` | 战利品表与 roll、太空货柜的创建/拾取距离/过期/清空 | `fight::deaths`、`losses`、`svc::moves`、`svc::inventory` |
| `crates/eve-server/src/losses.rs` | 船与 pod 损失落库：幸存物品、保险、克隆、技能点、killLog、killmail | heartbeat `Job::Lost`/`Job::BotLost` |
| `crates/eve-server/src/concord.rs` | 侵犯记录、犯罪标记、CONCORD、盗窃判定、`aggressionMgr` | `fight::aggress`、`fight::hit_structure`、`svc::moves`、`fight::step` |
| `crates/eve-server/src/guard.rs` | 母星防御：炮台/导弹/ECM/网子/扰断的选目标与开火 | `fight::step`（`fight.rs:38`）、`pos::load`、heartbeat 每分钟重载 |
| `crates/eve-server/src/svc/moonmining.rs` | 月亮开采、silo、反应堆的每燃料周期生产 | `posMgr`、`starbase::burn_fuel`（`starbase.rs:858`） |
| `crates/eve-server/src/svc/ram.rs` | 制造/时间研究/材料研究/拷贝作业 | `ramProxy` |
| `crates/eve-server/src/svc/reprocessing.rs` | 空间站精炼：收益率、站方抽成、可精炼判定 | `reprocessingSvc` |
| `crates/eve-server/src/heartbeat.rs` | 250 ms 循环、`Out` 通知与 `Job` 队列、每分钟燃料/主权/联盟事务 | `main` |
| `crates/eve-server/src/svc/inflight.rs` | 模块激活/停用入口，把 dogma 属性翻译成 `combat::Action`；锁定目标 | `dogmaIM` 的 `Activate`/`Deactivate`/`AddTarget` |
| `crates/eve-server/src/ballpark.rs` | `Park`/`Ship` 容器：`ships`/`rocks`/`cans`/`structures`/`sites`/`belts`/`missiles`/`watch` | 全部运行时 |

## 每 250ms 脉冲里的战斗

### 1. 脉冲入口与顺序

`heartbeat::pulse`（`heartbeat.rs:172`）在持有 world 锁时遍历所有已加载 park：先对每个 park 跑 `pos::step`（建筑定时器与力场，`pos.rs:446`，**无玩家也跑**）；若 `park.players().next().is_none()` 就跳过，否则 `park.advance(tick)` 后调用 `fight::step`（`heartbeat.rs:178`）；最后 `out.deliver(&w)` 在锁内广播 destiny、发 note，返回 `Job`，由 heartbeat 在锁外用自己的连接执行（`heartbeat.rs:154`、`heartbeat.rs:187`）。因此**纯 NPC 对 NPC、无玩家的系统不进行战斗思考**，母星防御（`guard::step` 在 `fight::step` 内）也只在有玩家的系统开火。

`fight::step` 的顺序固定（`fight.rs:35`）：

1. `locks` 锁定完成/丢失；
2. `cycles` 到期模块循环；
3. `guard::step` 母星防御；
4. `missiles` 到点导弹；
5. `afflict` 汇总网子/扰频/ECM/减锁/扰断/标记；
6. `npc::think`；
7. `drones::think`；
8. `concord::step`；
9. `deaths`（船/建筑死亡）；
10. `loot::expire`；
11. `report`（`OnDamageStateChange` 与玩家仪表）。

### 2. 锁定

玩家入口是 `inflight::add_target`（`svc/inflight.rs:294`）：已锁定直接返回；不能锁自己；跃迁中或已被 ECM 干扰拒绝；数量受 `max_locked` 限制；距离超过 `lock_range()` 拒绝。锁定时间 `40000 / (scanResolution * asinh(signatureRadius)^2)` 秒，钳 0.5–180 秒，参数非法返回 5 秒（`combat.rs:333`）。

`fight::locks`（`fight.rs:51`）每脉冲检查：目标消失（船不在、也不是岩石/建筑）、超出 `lock_range() * 1.1`、自己跃迁、自己被干扰，任一成立即丢锁；`Lock::Pending(ready)` 到期转 `Lock::Locked`。`LOCK_SLACK = 1.1`（`fight.rs:25`）。通知为 `OnTarget("add"/"otheradd"/"lost"/"otherlost")`（`fight.rs:82`、`fight.rs:101`）。

### 3. 模块循环与启停

上游 `svc/inflight.rs`：`Activate(itemID, effectName, target, repeat)` 用 dogma 计算后的属性组装 `combat::Active`（`plan`，`svc/inflight.rs:561`），校验目标（炮/导弹要能打、矿要打岩石且在射程内、投射效果要能上船且在 `optimal + 2*falloff` 内，`svc/inflight.rs:516`），加入 `fight.modules` 并广播 `OnGodmaShipEffect`（自己）与 `OnSpecialFX`（全系统）。`Deactivate` 只立 `stopping`，模块在周期边界停止（`svc/inflight.rs:744`）。

`fight::cycles` 收集 `next_ms <= now` 的模块，逐个 `cycle`（`fight.rs:127`）：

1. 若已跑过至少一轮（`cycles > 0`）且是采矿，先结算**上一轮**矿石（`mine`，`fight.rs:135`）。
2. `stop_reason`（`fight.rs:183`）：`stopping`、船在跃迁、`repeat < 1000 且 cycles > repeat`、弹药不足一次消耗、目标锁丢失、采矿超出 `range * 1.1`（提示距离）、投射模块超出 `optimal + 3*falloff`（无 falloff 时 `optimal * 1.1`）——任一成立即停。`REPEAT_FOREVER = 1000`（`combat.rs:547`）。
3. 扣电容：`cap_need > 0` 时 `capacitor.spend`，不足则以 "Your capacitor is too low to run that module." 停机（`fight.rs:147`）。
4. 扣弹药：`ammo.quantity -= per_cycle`，投 `Job::Ammo` 落库（`fight.rs:155`）。
5. `cycles += 1`；下一次 `next_ms = max(next_ms + duration, now + duration/2)`——迟一拍不算丢轮，长卡顿也不攒轮次（`fight.rs:163`）。
6. 按 `Action` 执行：炮击/导弹/护盾回充/装甲修理/结构修理/电容注入立即生效；采矿与 `Passive` 周期内不做事；其余走 `project`（`fight.rs:165`）。

停机广播 `OnGodmaShipEffect(start=false)`、给玩家一条 `CustomNotify`/`OnRemoteMessage`、全系统 `OnSpecialFX(start=false)`；`Passive` 模块停机还会投 `Job::Refit` 让 dogma 重算属性（`fight.rs:371`）。船离场（进站/跃迁/掉线）时 `stand_down` 停掉所有模块并放弃全部锁定（`fight.rs:810`）。

### 4. 炮台命中与伤害

命中率（`combat.rs:280`）：`chance = 0.5 ^ ((angular * sigRes / (tracking * targetSig))^2 + (max(0, distance - optimal) / falloff)^2)`；`sigRes` 取 `optimal_sig`，为 0 时按 40（`combat.rs:283`）；`falloff <= 0` 且距离超过 optimal 时命中率 0。角速度由相对速度去掉径向分量后除以距离，距离 < 1 m 记 0（`combat.rs:341`）。被 `Action::Disrupt` 时射手的 `optimal`/`tracking` 先乘 `Afflictions` 系数再算（`fight.rs:474`）。

命中质量（`combat.rs:301`）：`roll >= chance` 未命中，`roll < chance + 0.1` 记 `AttackMiss2`（擦边），否则按 `style` 记 1 或 3；命中且 `roll < 0.01` 为 wrecking（质量 6、倍率 3.0）；其余倍率 `0.49 + (1 - roll)`，质量按倍率分档 >1.3→5、>1.1→4、>0.9→3、>0.7→2、否则 1。

伤害是四维数组，顺序 EM(114)、爆炸(116)、动能(117)、热(118)（`combat.rs:14`、`combat.rs:77`）。`Vitals::apply`（`combat.rs:200`）逐层处理：每层 `effective = Σ raw[i] * resonance[layer][i]`，`taken = min(effective, 该层剩余)`（护盾用回充曲线当前值，装甲/结构用 `max - damage`），扣掉后溢出量按 `raw *= 1 - taken/effective` **原样**进入下一层（不再乘下一层抗性）；结构伤害达到 `hull_max` 即 `destroyed`（留 1e-6 容差）。抗性来自护盾 271–274、装甲 267–270、结构 109/111/110/113（`combat.rs:53`、`combat.rs:78`），缺属性按 1.0（`npc.rs:772`）。NPC/无人机的血量、回充、抗性、传感器由 `entity_fighter` 组装（`npc.rs:778`）。

`fight::shoot`（`fight.rs:467`）取目标位置/速度/信号半径（建筑用 `signature`，为 0 退化 `radius`），算角速度与命中率，用两次 `park.rng.unit()` 决定命中与质量，把 `damage * multiplier` 交给 `hit`。导弹由 `launch`（`fight.rs:487`）记录 `impact_ms = now + min(distance/speed, flight_ms)`、`speed = range / flight_ms`，超出 `range` 的 `reaches = false`，到点直接消失（`fight.rs:516`）；系数 `factor = min(1, sig/cloud, (sig/cloud) * aoeVelocity/speed)`（`combat.rs:323`），质量 ≥0.99→3、≥0.5→2、否则 1（`fight.rs:526`）。

`hit`（`fight.rs:544`）把伤害落到船或建筑，记录 `last_attacker = (char_id, ship_id)` 与 `damage_log`（玩家按 char_id、NPC 按 `-type_id` 归类并累计，`fight.rs:557`），给射手发 `OnDamageMessage(AttackHitN/AttackMissN)`、给受害者发带 `R` 后缀的版本（`fight.rs:572`），最后调用 `aggress`。

### 5. 电容与装填

护盾与电容共用 `Charged`（`combat.rs:115`）：`tau = recharge_ms / 5`，`v(t) = (1 + (sqrt(v0/max) - 1) * exp(-(t - t0)/tau))^2 * max`。`spend` 不足时**一点不扣**并返回 false（`combat.rs:156`）；`rescale` 在最大容量变化时保持当前百分比（`combat.rs:166`）。技能/模块改变容量后由 dogma 重算，不在这里做。

装填只是"每周期扣 `per_cycle`"：`Ammo { item_id, type_id, quantity, per_cycle }`（`combat.rs:511`），弹药耗尽时 `stop_reason` 静默停机；晶体等可复用弹药在 `inflight::plan` 里不产生 `burns`（`svc/inflight.rs:578`）。

### 6. 投射效果与状态影响

`project`（`fight.rs:226`）：先按距离做 `falloff_chance(d, optimal, falloff)`（距离 ≤ optimal 恒 1，`falloff <= 0` 为 0，否则 `2^-((d-optimal)/falloff)^2`，`combat.rs:490`）；`Action::Jam` 再叠 `jam_chance`（取目标最强传感器，`strength[kind]/defence` 钳 0–1，`combat.rs:502`），命中时目标收 `OnRemoteMessage("TargetJammedBy")`；结果写入 `running.landed`，但**无论是否命中**，offensive 模块都会 `aggress`（`fight.rs:243`）——开火即犯罪，打空也算；命中后中和/吸血扣目标电容（吸血先取目标再补自己）、远程电容/护盾/装甲直接加减，网子/扰频/ECM/减锁/扰断/标记只登记 `landed`，由 `afflict` 统一施加。

`afflict`（`fight.rs:307`）收集"母星 EW 正在保持"的效果（`guard::holding`）与"本脉冲 `landed && cycles > 0`"的模块效果，聚合成 `Afflictions`：同类多份用 `dogma::stacking_penalised`（最强一份全额，第 n 份乘 `exp(-(n/2.67)^2)`，正负增益分别排序，`dogma.rs:601`）；`scrambled` 是各扰频点数**直接求和**，`jammed` 是任一 ECM 命中即真；网子改 `Ship.stats.max_velocity` 并广播 `SetMaxSpeed`（`fight.rs:343`）；正在对准/跃迁且 `scrambled >= 1.0` 时强制 `Stop`、广播 `Stop`、给玩家 `OnRemoteMessage("WarpScrambled")`（`fight.rs:351`）。

## NPC 与站点

### 1. 星系野生动物加载

`npc::load`（`npc.rs:322`）依次：读 `mapSolarSystems.security` 与 `COALESCE(s.factionID, r.factionID)`（无星系按 1.0/无势力）；`pirates_for` 选海盗团（Guristas 500001/500010、Angel 500002/500011/500015、Blood 500003/500007/500008/500012、Sansha 500019、Serpentis 500004/500009/500014/500020，其它按 `solarSystemID % 5`，`npc.rs:76`）；每团 5 个 hull 组 Angel `[550,575,551,576,552]`、Blood `[557,577,555,578,556]`、Guristas `[562,579,561,580,560]`、Sansha `[567,581,566,582,565]`、Serpentis `[572,583,571,584,570]`（`npc.rs:68`）；从 `invTypes` 取类型并用 `dgmTypeAttributes` 填属性（`npc.rs:435`），过滤条件为赏金 > 0、`HP > 0`、且有武器（`damageMultiplier` 与 `speed` 都 > 0，或 `entityMissileTypeID` 指向的导弹存在，`npc.rs:143`），每类按赏金升序。

矿石是内置 16 种与各自安全下限（`npc.rs:88`：Veldspar/Scordite -1.0、Pyroxeres 0.7、Plagioclase 0.5、Omber/Kernite 0.4、Jaspet/Hemorphite/Hedbergite 0.2，Gneiss 以下到 Mercoxit 0.0），只保留 `security >= floor` 的；CONCORD 类型取 `invTypes.groupID = 301`（`npc.rs:37`、`npc.rs:391`）。

### 2. 小行星带

`populate`（`npc.rs:455`）对每个 group 9 天体建 `Belt`，每带 `8 + rng.below(8)` 块石头：选矿用"两次均匀取小"（`min(rng.below(len), rng.below(len))`）让常见矿更常见；数量 `round(rng.range(2000, 10000) / volume)`（约 2000–10000 m³）；位置在带心 25 km 球内、Y 压扁到 0.2；半径 `min(12000, 800 + 40*cbrt(m³))`（`npc.rs:493`）。采空后从 park 移除并广播 `RemoveBalls`（`fight.rs:664`）。

### 3. rat 生成、等级与赏金

玩家进入带心 `SPAWN_RANGE = 150_000` m 且该带无 rat、`respawn_at` 已过时生成（`npc.rs:26`、`npc.rs:565`）。编制 `plan`（`npc.rs:579`）按安全：≥0.7 → 1–3 护卫；≥0.5 → 2–3 护卫 + 0–1 驱逐；>0 → 1–2 巡洋 + 0–2 驱逐 + 1–2 护卫；>-0.5 → 0–1 战巡 + 2–3 巡洋 + 0–2 护卫；其余 → 1–2 战列 + 1–3 巡洋。同类"第几档"由 `tier`（`npc.rs:608`）按赏金三等份决定：高安取最弱三分之一、低安（>0）取中间、0 及以下取最强；该类为空时回退到更小 hull（`npc.rs:646`）。位置在带心 20 km 球内（Y 压扁 0.2），ID 从 `NEXT_ID = 1_500_000_000` 递增（`npc.rs:42`）。

属性映射：巡航 `entityCruiseSpeed`（≥50），最高速 `clamp(maxVelocity, cruise, cruise*2.5)`，攻击距离 `max(entityAttackRange, maxRange, 5000)`，环绕 `entityFlyRange`（≥1000），锁定距离 = 攻击距离 × 2，信号半径 `max(signatureRadius,10)`、扫描分辨率 `max(scanResolution,50)`（`npc.rs:657`、`npc.rs:778`）。每只 rat 有 `shield_boost`/`armor_repair`（属性 637/636、631/630），思考时护盾 < 75% 或装甲伤害 > 25% 就按 `every_ms` 治疗（`npc.rs:934`）。赏金 = `entityKillBounty`；安全提升参数为 `entitySecurityStatusKillBonus` 与 `entitySecurityMaxGain`（`npc.rs:695`）。

`think_one`（`npc.rs:915`）每 `THINK_MS = 1000` ms：① 目标仍值得打？必须是被看见的船（玩家或 bot），距自己 ≤ `max(aggro_range, 120_000)` 且距自己的带 ≤ `180_000`，或 bot 的 rat 目标在 `max(leash, 160_000)` 内，否则 `disengage` 回带；② 无目标时选最近：bot 按战争/声望（`bots::stance`），敌对或用 `WAR_AGGRO_RANGE = 80_000`、友军跳过、普通玩家用 `aggro_range = max(attackRange*2, 30_000)`（`npc.rs:276`、`npc.rs:973`）；③ 能在 `lock_range()` 内且未被干扰就清旧锁、按 `lock_seconds` 建 `Pending`；④ 距离 > 攻击距离全速追击，否则按 `cruise`（`cruiseSpeed/top` 钳 0.1–1.0）环绕 `fly_range`；⑤ 锁上后把 `brain.weapons` 克隆成 `Active`，首次开火随机延后 0–50% 周期（`npc.rs:1051`）。

击杀（`npc::killed`，`npc.rs:1097`）先问 `sites::rat_killed`，命中站点则投 `Job::SiteCleared`；否则从带移除，带空时 `respawn_at = now + 240_000..480_000`（`RESPAWN_MS`，`npc.rs:28`）。赏金与安全提升在 heartbeat（`heartbeat.rs:274`、`heartbeat.rs:304`）：赏金从 CONCORD（1000125）付到角色钱包（refType 17）；安全等级 `LEAST(maxGain, rating + (10 - rating) * bonus)`，只升不降。

### 4. 死亡空间站点

`sites.rs` 只做三件事：`open`（`sites.rs:49`）放一个 type 25354 的信标 ball（半径 1000 m），用 `npc::spawn_group` 在站点周围生成 rat，全部 `AddBalls` 后插入 `park.sites`；`close`（`sites.rs:63`）按 mission 移除信标与所有 rat 并广播 `RemoveBalls`；`rat_killed`（`sites.rs:76`）删一只，空时返回 `(mission_id, char_id)`，`fight::deaths` 转 `Job::SiteCleared`，`agent_missions::site_cleared` 把任务置 `CLEARED` 并提示玩家。站点强度由任务等级给的安全值决定：`ENCOUNTER_SECURITY = [0.9, 0.6, 0.3, -0.2, -0.8]`（`svc/agent_missions.rs:77`），1 级按 0.9 生成护卫级、5 级按 -0.8 生成战列级；玩家第一次跃迁过去时打开（`open_site`，`svc/agent_missions.rs:753`），同一任务不重复开。

## 无人机

### 1. 控制上限与发射

上限取角色 dogma 属性 `maxActiveDrones`(352)，由 Drones 技能提升；为 0 时提示需要 Drones 技能（`drones.rs:222`）。`ship.Drop`（`drones.rs:102`）逐项校验属于自己、位置本船、flag 87（drone bay）、category 18；堆叠 > 1 时拆出 1 个新物品，否则整件移动并设 singleton。出舱位置在船体半径外 `LAUNCH_CLEARANCE = 150` m 的球面上，随机写入 `entity` 坐标（`drones.rs:149`）。无人机属性 = 类型属性 + 该角色对它的技能计算值（`Loadout::load_with_drones` 后 `with_attributes`，`drones.rs:178`）。

### 2. 指令

`entity` 对象（`drones.rs:268`）：`CmdEngage→Engage`、`CmdMine→Mine{repeat:false}`、`CmdMineRepeatedly→Mine{repeat:true}`、`CmdReturnHome`、`CmdReturnBay`；`CmdAbandonDrone`/`CmdRelinquishControl` 当作 `Idle`；`CmdDelegateControl`/`CmdUnanchor` 明确拒绝。校验（`drones.rs:286`）：Engage 目标必须是"不是自己的、有战斗组件的船"，Mine 目标必须是 `park.rocks` 里的岩石且该无人机有 `miner`；失败按 `{droneID: (CustomError, 原因)}` 返回。

### 3. 每秒思考

`think_one`（`drones.rs:344`）每 1000 ms：① 母船不在则 `controller = None`；目标消失则订单变 `Idle`；单次采矿（`repeat:false`）在"已采过且矿枪已停"后转 `ReturnBay`（`drones.rs:361`）；② 活动状态取 `drone.py` 编号 Idle 0、Combat 1、Mining 2、Departing 4、Departing_2 5（`drones.rs:42`）；③ 运动：Idle 环绕母船 1000 m、Engage 环绕目标 `orbit`、Mine 环绕 `min(orbit,500)`、ReturnHome 跟随母船保持 1000 m、ReturnBay 跟随到 0；④ 清掉不该继续的模块，只保留当前目标的锁，没锁则按 `lock_seconds(scan_res, 目标信号)` 建 `Pending`；⑤ 锁上后按订单启动工具（Mine 用 `miner`，`repeat` 决定 `REPEAT_FOREVER` 还是 0；Engage 用全部 `weapons`），已存在的同 ID 模块不重复加；`OnDroneStateChange` 只在 activity 变化时发，新启模块广播 `OnSpecialFX(start=true)`，航向变化发 `course_entries`。`orbit` 来源：`ORBIT_RANGE > 0` 用它，否则 `ENTITY_FLY_RANGE`（≥500）（`drones.rs:244`）。

### 4. 回收与损失

`ReturnBay` 到母船表面距离 ≤ `DOCK_RANGE = 1500` m 时 `dock`：`fight::detach` 移出 park、广播 `RemoveBalls`、投 `Job::DroneHome`，heartbeat 把物品移回母船 flag 87（`drones.rs:480`、`drones.rs:527`）；`ReturnHome` 到 1.5×1000 m 内转 `Idle` 留在太空；`ship.ScoopDrone`（`drones.rs:488`）要求自己的、距离 ≤ `2500 × 1.25` m，直接进舱。被击毁时 `fight::deaths` 投 `Job::DroneLost`（`fight.rs:740`），`drones::lost` 直接 `txn.destroy(drone_id)`（`drones.rs:543`）——**无人机没有残骸、没有掉落**。

## 损失与掉落

### 1. 死亡判定

`fight::deaths`（`fight.rs:673`）：`hull_max > 0` 且 `hull_damage >= hull_max - 1e-6` 的船进入死亡列表，建筑走 `structure_deaths`（`fight.rs:768`）。死亡时同一 tick 先发 `TerminalExplosion` 再发 `RemoveBalls`，客户端才会播爆炸而非直接消失（`fight.rs:685`）。`detach`（`fight.rs:830`）移出 park，同时让所有锁它的船丢锁、所有瞄它的模块停机、所有追它的导弹失效（`forget`，`fight.rs:843`）。

### 2. 分支

| 对象 | 处理 |
|---|---|
| bot 船 | 播报、`concord::killed`；非 pod 则 `bots::eject` 生成 pod；记录 `park.bot_losses`；有玩家最后一击时按 `mass/1e6 * 15000` ISK 估值（钳 10 000–1 000 000）或已存 `bot_loot` 的幸存部分投 `Job::Loot`；`Job::BotLost` 只写 killLog/killmail |
| NPC rat | `npc::killed`（含站点回调）；有玩家击杀者且不是警察时付赏金 + `loot::roll(bounty, loot_count)`，投 `Job::Bounty` 与 `Job::Loot` |
| 无人机 | `Job::DroneLost`，物品销毁 |
| 玩家船 | `concord::killed`，`Job::Lost` → `losses::handle` |

bot 掉落拆分（`fight.rs:752`）：每件 `(type, n)`，`n <= 8` 时逐件 50% 概率留下，`n > 8` 时按 `round(n * rng.range(0.3, 0.7))` 留下，其余进 killmail 的 "Destroyed items"。

### 3. 玩家船损失（`losses::ship_lost`，`losses.rs:116`）

1. 查 `entity.locationID = 船`（排除角色本身）的物品清单。
2. 每件以 `SURVIVING_SHARE = 0.5` 概率成为幸存者，其余 `destroy` 并记入 killmail。
3. 幸存者 `move_to(loss.system, 0)` 先离开船，再销毁船体。
4. 新建 type 670 的 capsule（太空 flag 0），把 `character_.shipID` 指过去。
5. 幸存物品打包进 `loot::drop_can` 掉在死亡位置，owner 是受害者。
6. `pay_insurance`（`losses.rs:199`）查 `insuranceContracts`，删合同，从系统账户（owner 1）付 `payout` 给投保人（refType 19），通知 `OnAccountChange` 与 `OnRemoteMessage`。
7. `inflight::profile` 读回 capsule 的战斗/运动属性，插入 park 并广播 `AddBalls`，最后 `Move::ShipLost` 把 session 切到新 pod。

保险购买在 `svc/insurance.rs:60`：保费 = 基础价的 5% × n（n=1..6），保额 = `0.4 + 0.1n`（5% 保费保 50%，30% 保 100%），合同 12 周；只能给本站、自己的、已组装且无其他合同的船投保。

### 4. pod 与克隆（`losses::podded`，`losses.rs:240`）

1. 销毁 pod 物品，销毁角色 flag 89（implant）的全部植入体，名字进 killmail。
2. 技能点：`saved` 取该角色所有 clone 物品（group 23）里最大的 `skillPointsSaved`(419)，没有就用 Alpha clone（164）类型上的值，再没有就是 `f64::MAX`；角色 flag 7 与 61 的技能物品 SP 求和，超过 `saved` 的部分从**SP 最多的技能**扣（最多扣到该技能归零），并重算等级（`points_at(stc, level) = stc * 2^(2.5*(level-1))`，`losses.rs:336`）。
3. 唤醒站：clone 记录的家 → 角色 `stationID` → 公司 `stationID`（`medical::home_station`）。
4. 新建 Alpha clone（164）放该站 hangar，`replace_clone` 覆盖旧 clone，角色 `shipID/stationID/solarSystemID/constellationID/regionID` 全改到该站，角色物品 `entity.locationID` 也移进站。
5. `Move::Podded` 把客户端送到站内；若扣了技能点，提示 "clone could not hold everything you knew"。

### 5. 击杀记录与邮件

`losses.rs:456` 拼老 killmail 文本（时间、受害者、联盟、公司、被毁船型、星系、安全、参与者按伤害降序、最后一击标注），`losses.rs:518` 写 `killLog`（时间、受害者角色/公司/联盟、船型、`victimItemID`、星系、`finalBlowID`、总伤害、`isPodKill`）与 `killLogParticipants`（每个 `who > 0` 的参与者：公司/联盟/船型/武器/伤害/最后一击），附 "Destroyed items"，以 EVE 邮件发给受害者与最后一击者（`svc::chat::deliver`，`losses.rs:593`）。

### 6. 掉落与货柜（`loot.rs`）

战利品表惰性加载一次（`OnceLock`）：`invTypes` join `invGroups`，category 7（模块）或 8（弹药），要求 `marketGroupID` 非空且 `basePrice > 0`，按价格升序（`loot.rs:73`）。`roll(bounty, count, rng)`（`loot.rs:102`）：30% 什么都不掉；件数取 `count`（`entityLootCountMin/Max`，为 0 时退化为 1–2）；可负担性为弹药 `price*100 <= max(bounty,1000)`、模块 `price <= 1.5*max(bounty,1000)`；从池里"两次取小"；弹药数量 `portionSize * (20 + rng.below(81))`（20–100 份）。

货柜是 type 23 的真实物品（`entity` 行 + 坐标），内容物是普通 `entity` 子项；can 的 owner 是掉落者，新生成的战利品也归他，从船上搬来的幸存物保留原 owner，flag 0；寿命 `LIFETIME_MS = 2 小时`（`loot.rs:30`），新 park 加载时按"现在 + 2 小时"重新计时（`loot.rs:129`）。拾取要求表面距离（减去双方半径）≤ `TRANSFER_RANGE = 2500 × 1.25`（`loot.rs:165`），`svc::moves` 的 `reachable` 允许拿"够得着的 can 里的任何东西"（`svc/moves.rs:312`）；取走后 `clear_emptied` 查 `entity.locationID = can` 的剩余数量，为 0 就删 can 并广播 `RemoveBalls`（`loot.rs:241`）。到期的 `loot::expire` 移除 can、广播、投 `Job::Scrap`，heartbeat 递归销毁内容物（`loot.rs:269`）。can 的 `owner_id` 只用于盗窃判定，**拾取本身不校验 owner**——够得着就能拿，拿走即归自己（`svc/moves.rs:413`）。

## 犯罪与警察

### 1. 侵犯标记

`concord::aggress`（`concord.rs:87`）在每次命中和每次投射模块开火时调用：

1. 取双方"背后的飞行员"：无人机算 owner，玩家/bot 船算 `char_id`，NPC 返回 None（不参与）；同一人或目标是无人机则直接返回。
2. `fair` 判定：目标是通缉犯、目标最近侵犯过自己或自己公司、目标安全 ≤ `OUTLAW = -5.0`、或双方在战争中（`svc::war::at_war`）。
3. 无论公平与否都写 `watch.aggression[attacker][on_char] = now`；第一次记录时向全系统玩家广播 `OnAggressionChange(system, aggressors)`。
4. 公平或非首次则不追加惩罚。安全 ≥ `HIGH_SEC = 0.45` 时算犯罪：响应延迟 `(5 + (1 - clamp(sec,0.5,1)) * 40) * 1000` ms（0.5 安全约 25 秒、1.0 安全 5 秒），`criminals[char] = (now + 15 分钟, Some(已存在或 now+response))`，并投 `Job::Security { delta: -0.5 * security }`。
5. 低安（`security > 0`，即 0.1–0.4）只投 `Job::Security { delta: -0.1 }`；0.0 及以下不罚。
6. 侵犯记录保留 `AGGRESSION_MS = 15 分钟`，`concord::step` 每脉冲清理过期项（`concord.rs:33`、`concord.rs:253`）。

打建筑走 `aggress_structure`（`concord.rs:123`）：自己的或同公司的不打；记录对公司 `corp_id` 的侵犯；战争中的攻击不算犯罪；其余同玩家侵犯。击杀玩家（`concord::killed`，`concord.rs:155`）：最后一击必须是玩家且不是自己；若目标可打（通缉/先侵犯/outlaw/战争）或星系安全 ≤ 0 不罚；否则 `delta = -weight * max(security, 0.1)`，`weight = 3.0`（pod）或 `1.5`（船）。安全值落库在 `heartbeat::change_security`：`GREATEST(-10, LEAST(10, rating + delta))`（`heartbeat.rs:323`）。

### 2. 盗窃

`is_theft`（`concord.rs:185`）：owner > 0、不是 NPC（`10_000 < id < 100_000_000` 视为 NPC）、不是自己/自己公司、且不是"同玩家公司的公司"——从别人的 can 拿东西就是盗窃。`took_from`（`concord.rs:206`）在 `svc::moves` 每次物品移动后检查来源 can，构成盗窃就把 `(owner, now)` 与 `(owner_corp, now)` 写进侵犯表并广播 `OnAggressionChange`；**盗窃不是犯罪**：不扣安全、不叫警察，只让物主及其公司 15 分钟内可以正当还击。`aggressionMgr.CheckLootRightExceptions` 给客户端"拿这个会不会算偷"的答案（`concord.rs:233`）。

### 3. CONCORD

`concord::step` 到期后 `arrive`（`concord.rs:275`）在罪犯船 5 km 球内生成 `SQUAD = 3` 艘警察船（类型按 `park.wildlife.police` 顺序循环），广播 `AddBalls` 与 `effects.JumpIn`。警察船属性硬编码在 `npc::police_ship`（`npc.rs:712`）：

| 项 | 值 |
|---|---|
| 结构 | `max(HP, 1_000_000)` |
| 抗性 | 三层全 0（免疫伤害） |
| 扫描分辨率 / 传感器 | 5000 / 四类均 1000 |
| 炮 | optimal 250 km、falloff 50 km、tracking 100、sigRes 1，伤害 `[0,0,2500,2500]`，周期 2 s |
| 扰频 | 100 点、5 s 周期、射程 250 km |
| 速度/半径/质量 | `max(maxVelocity,1000)`、`max(radius,50)`、`max(mass,1e6)` |

`hunt`（`concord.rs:298`）：目标只找"罪犯在本星系的、非 pod 的船"（`quarry` 排除 group 29）；锁定固定 1 秒；锁上后启动全部武器；环绕 2500 m；目标不在就 `leave_ms = now + POLICE_LINGER_MS = 30 秒`（`npc.rs:763`）后 `detach` 并 `RemoveBalls`。警察赏金为 0、无掉落（`brain.police.is_none()` 才付赏金，`fight.rs:722`）。

### 4. 母星炮台（`guard.rs`）

炮台属于建筑（`Structure.guard`），由 `pos::load` 按类型组建档案（`guard.rs:113`）：

| 组 | 武器 | 周期 |
|---|---|---|
| 426/430/449（弹/激光/混合哨戒炮） | `Gun { multiplier: max(damageMultiplier,1), gun }` | `speed`，缺省 10 s |
| 417（导弹哨戒） | `Missile` | `missileLaunchDuration`，缺省 10 s |
| 441（网子） | `Web((1 + speedFactor/100) 钳 0.01–1)` | `duration`，缺省 10 s |
| 443（扰频） | `Scramble(max(warpScrambleStrength,1))`，射程 `warpScrambleRange` | 10 s |
| 439（ECM） | `Jam([238,239,240,241])` | 10 s |
| 440（减锁/减分辨） | `Dampen{range: 237, resolution: 565}`（缺省 1） | 10 s |

`search` = `proximityRange`(154)，`switch_ms` = `targetSwitchDelay`(691)；只有自己与所属控制塔都 `fully_online` 才开火（`guard.rs:338`）。目标选择保留旧目标（仍敌对且在 `search` 内），否则取最近的合格目标，新目标要等 `switch_ms` 才能开第一枪（`guard.rs:357`）。敌对判定（`guard.rs:309`）：owner 本人、同公司、同联盟永不攻击；否则按塔的 `Sentry`：战争中、侵犯过本公司或成员（`aggression`）、安全低于阈值（`status`）、是通缉犯（`status_drop`）、声望低于阈值（`standing`）、声望为负（`standing_drop`）。声望来自 `ownerStandings`（heartbeat 每分钟 `refresh_standings`）。

实弹：炮用 `hit_chance` + `turret_shot`，伤害 = `ammo.damage * multiplier * shot.multiplier()`；导弹生成 `Missile` 飞行；非晶体弹药每发 `quantity -= 1` 并投 `Job::StructureAmmo`（晶体组 86 不消耗，`guard.rs:172`、`guard.rs:428`）。EW：先过 `falloff_chance`，ECM 再过 `jam_chance`，`landed` 由 `afflict` 施加到船上（`guard.rs:415`、`guard.rs:435`）。

## 生产与采集

### 1. 采矿（玩家与采矿无人机）

矿枪在 `inflight::plan` 里变成 `Action::Mining { amount: miningAmount, range: maxRange }`（`svc/inflight.rs:631`）。每个周期结束（下一周期开始时）结算：表面距离必须 ≤ `range * 1.1`；`units = floor(amount / rock.volume)` 钳到 `[0, rock.quantity]`；扣减岩石并投 `Job::Ore`（`fight.rs:633`）。落库时按货舱剩余容积折算 `fits`，装不下就停激光并提示 "cargo hold is full"（`heartbeat.rs:232`）。无人机采矿把矿装进**控制者的船**，母船不在则本次不采（`fight.rs:640`）。

### 2. 月亮开采与反应（`svc/moonmining.rs`）

数据库没有"某颗卫星含什么"的表，实现按 `moonID` 确定性抽取（`moon_materials`，`moonmining.rs:62`）：① 种子 `moon_id ^ 0x6d6f_6f6e` 用 `combat::Rng`；② 材料数 0/1/2/3 种，权重 `COUNTS = [30,40,20,10]`（`moonmining.rs:41`）；③ 每份按基础价分五档 2/8/16/64/256 ISK，权重 `TIERS = [45,25,15,10,5]`（`moonmining.rs:39`），安全 > 0 时最高档降一档（256 档只在 0 及以下出现），从该档随机取一种并去重；④ 结果只取决于 moonID 与安全，不会变。`GetMoonForTower` 只在塔 state ∈ {3,4,5} 时返回材料表（`moonmining.rs:105`）。

每个 harvester 用 `provisionType` 指定采哪种材料（必须是该月有的），silo 指定存哪种（受 `cargoGroup`(629) 限制），改类型会删掉旧类型的 `posLinks`（`moonmining.rs:313`）。反应堆运行"放在它里面的那个反应物品"，其 group 必须在该堆的 `reactionGroup1/2`(842/843) 里，输入输出来自 `invTypeReactions`（`moonmining.rs:155`、`moonmining.rs:243`）。**每支付一个燃料周期跑一轮**（`starbase.rs:858`）：先 harvester 把产量送进连接的 silo，再反应堆检查每个输入够不够、每个输出有没有空间，全满足才扣输入、加输出（`moonmining.rs:415`）。产量 `units(t, batches) = batches * moonMiningAmount(t)`（缺省 1），harvester 实际取 `min(月批次数, harvesterQuality)`（`moonmining.rs:436`、`moonmining.rs:447`）；silo 容量 = `capacity * (1 + controlTowerSiloCapacityBonus/100)`（`moonmining.rs:171`）。手工放入也受限：silo 只能放 `cargoGroup` 内的、且只能是设定那一种（未设定时只能放已有种类）；反应堆只能放一个反应（`moonmining.rs:188`）。

### 3. 制造与研究（`svc/ram.rs`）

作业在一条装配线上跑，先报价（`quoteOnly=1`）再安装（`quoteOnly=0`），安装时按 `authorizedCost` 校验价格没涨（`ram.rs:535`）。时间（`plan`，`ram.rs:609`）：

| 活动 | 单轮时间 | 技能折扣 |
|---|---|---|
| 制造（1） | `productionTime - pl/(1+pl) * productivityModifier`（PE 为负时 `productionTime - (pl-1)*modifier`） | Industry 每级 -4% |
| 时间研究（3） | `researchProductivityTime` | Research 每级 -5% |
| 材料研究（4） | `researchMaterialTime` | Metallurgy 每级 -5% |
| 拷贝（5） | `researchCopyTime * clamp(licensedRuns,1,maxProductionLimit)/maxProductionLimit` | Science 每级 -5%（代码注释说明是自选） |

总时间 = 单轮 × 线体倍率（`baseTimeMultiplier * detail.timeMultiplier`）× 角色倍率 × runs，超过 `MAX_DAYS = 30` 天拒绝（`ram.rs:523`）；开始时间 `max(now, line.nextFreeTime)`，结束时间写回 `nextFreeTime` 占线（`ram.rs:657`、`ram.rs:591`）。

材料（`ram.rs:638`）：浪费率 `wasteFactor/100 / (1+ME)`（ME ≥ 0），ME < 0 时 `base * (1-ME)`（`ram.rs:378`）；线体材料倍率 = `materialMultiplier * detail.materialMultiplier`，制造再乘 `(1 + 浪费率)`；生产技能倍率 = `1.25 - 0.05 * ProductionEfficiency`；基础消耗 `round(quantity * line_material) * runs`，实际 `round(quantity * 材料倍率 * 技能倍率) * runs`，差额进 `wasteMaterials`；`damagePerJob >= 1` 整件消耗，`0 < damagePerJob < 1` 的是工具，每次作业磨损 `damagePerJob * runs`（小数按概率取整），要求至少有 `quantity` 件（`ram.rs:550`）。

槽位（`ram.rs:757`）：制造 `1 + MassProduction + AdvancedMassProduction`，其它活动共用 `1 + LaboratoryOperation + AdvancedLaboratoryOperation`。距离（`ram.rs:780`）：同站直接允许，否则必须同 region，按 `REACH = [-1,0,5,10,20,50]`（SupplyChainManagement 用于制造、ScientificNetworking 用于其它）允许 0/5/10/20 跳，5 级不限。费用 = `costInstall + costPerHour * ceil(小时)`，从角色付给线 owner（refType `55 + activity`，`ram.rs:562`、`ram.rs:663`）。安装时蓝图移到 `flagFactoryBlueprint`；交付时造物按 `portionSize * runs` 放回站内 hangar，研究累加 `productivityLevel`/`materialLevel`，拷贝生成 `runs` 份带 `licensedProductionRunsRemaining = licensedRuns` 的拷贝蓝图（`ram.rs:848`）；取消只退蓝图，材料不退。

### 4. 精炼（`svc/reprocessing.rs`）

收益率（`terms`，`reprocessing.rs:94`）：`combined = min(1, stationYield + 0.375 * (1 + 0.02*Refining) * (1 + 0.04*RefineryEfficiency))`，非矿石再乘 `(1 + 0.05*ScrapmetalProcessing)` 并仍钳到 1。站方抽成 `tax = max(0, reprocessingStationsTake - 0.0075 * 对该站所属公司的声望)`（`reprocessing.rs:129`）。

逐个物品（`quotes`，`reprocessing.rs:217`）：只处理自己的、在站 hangar 或本站自己船里的、且至少有一个 `portionSize` 的物品（当前驾驶的船不参与）。每种材料 `total = perPortion * portions`，`recovered = floor(total * yield)`，`station = floor(recovered * tax)`，`client = recovered - station`，`unrecoverable = total - recovered`；执行时不足一份的余量保留，整件销毁前把容器内容物移进 hangar，矿物按类型合并入 hangar（`reprocessing.rs:289`）。可精炼判定沿用客户端规则：有 activity 6 材料，且不是信用点/书签/矿物/rookie ship/蓝图/反应物（`reprocessing.rs:149`）。

## POS 与主权

### 1. 状态与定时器

状态值照 `playerOwned.py`（`pos.rs:34`）：0 未锚定、1 已锚定、2 上线中、3 强化中、4 在线、5 运行中。每步时长来自类型属性 `anchoringDelay`(556)、`onliningDelay`(677)、`unanchoringDelay`(676)，毫秒 × 10 000 换成 FILETIME tick（`pos.rs:378`）。时间戳只记录"这一步何时开始"（`stateTimestamp`），客户端自己走表；`starbaseSpeedup` 通过**回填开始时间**加速：`timer_start(now, delay) = now - delay + delay/speedup`（`pos.rs:63`），两端对"还剩多久"因此一致。

`pos::step`（`pos.rs:446`）每脉冲：按需升起/降下/重调力场（`reconcile_field`，`pos.rs:481`）；护盾回到 25% 以上时清除 `reinforce_asked`；到期步骤收尾——`ONLINING`/`REINFORCED → ONLINE`，`UNANCHORED` 完成时松开塔绑定并广播 `SetBallFree(true)`；随后广播 `OnSlimItemChange` 并投 `Job::Structure` 落库。

### 2. 锚定

`starbase::anchor`（`starbase.rs:194`）：

1. 必须"自由"（未锚定且解锚定时已结束），否则 `AlreadyUnanchoring`。
2. 需该塔的 `deployAnchor` 权限，且距建筑 ≤ `CONFIGURE_RANGE = 5000 * 1.25` m。
3. 锚点距自己船 ≤ `ANCHOR_REACH = 30_000` m，否则 `CantAnchorTooDistant`。
4. 星系安全 ≥ `CONCORD_ANCHOR_LIMIT = 0.8` 直接 `CantAnchorConcordRestriction`；类型带 `anchoringSecurityMax`(1032) 时还要低于该值。
5. 控制塔（group 365）找 100 km 内最近且未被别的塔占用的卫星（`CantAnchorNoMoonNearby`/`CantAnchorMoonAlreadyHasControlTower`）；其它建筑找射程（`maxStructureDistance`(650)）内已固定的塔，owner 必须一致、塔必须在线（`CantAnchorRequireTower`/`CantAnchorStructureOwnerBad`/`CantTowerNotOnline`）。

写 `posStructures.state=1`、`stateTimestamp=timer_start(now, anchoringDelay)`、`controlTowerID`、`moonID`，更新 `entity` 坐标，广播 `SetBallPosition` 与 `SetBallFree(false)`。权限 `allowed`（`starbase.rs:663`）：owner 永远可以；否则按塔的 deploy 列：2 = 公司或联盟成员，1 = 公司成员，0 = 公司成员且有 StarbaseConfig 或 Director 角色。

### 3. 上线、下线与燃料

`online`（`starbase.rs:327`）要求已锚定完成、未强化、有 `deployOnline` 权限且在配置距离内；控制塔检查"一个周期燃料"是否齐全（`CantOnlineTowerLacksResources`）并在上线时先扣掉这一周期（`consume` 写 `lastFuel = now`）；非塔建筑要检查所属塔在线、CPU/电网余量够、且塔有对应目的的燃料（`draw_from_tower`，`starbase.rs:362`）。上线写入 `ONLINING` + `timer_start(now, onliningDelay)`，由 `pos::step` 到期转 `ONLINE`。`offline`（`starbase.rs:405`）把该建筑及所有子结构置 `ANCHORED`、清空时间戳（`take_offline`，`starbase.rs:542`）。强化中的塔及子结构不能做任何状态变更（`CantPerformTowerReinforced`，`starbase.rs:563`）。解锚要求已锚定完成、无子结构固定在塔上、塔的货舱为空（`CantUnanchorTowerStructuresPresent`/`CantUnanchorContainerNotEmpty`），然后 `UNANCHORED` + `timer_start(now, unanchoringDelay)`；完成后可被 `ship.Scoop` 收回（距离 ≤ 2500 m，`starbase.rs:447`）。

燃料表（`Fuel::of`，`starbase.rs:730`）取 `invControlTowerResources` 中该塔类型、满足 `minSecurityLevel`、且 `factionID` 与该星系（系统/星座/区域）势力一致的资源。每周期 `burn(power_load, cpu_load)`（`starbase.rs:761`）：

| purpose | 消耗量 |
|---|---|
| 1（online） | 全额 `quantity` |
| 2（power grid） | `quantity * 电网负载率` |
| 3（CPU） | `quantity * CPU 负载率` |
| 4（reinforce） | 不参与常规消耗 |

再乘 `factor`：联盟在该星系拥有主权时为 `SOVEREIGN_FUEL = 0.75`，否则 1（`starbase.rs:68`）。周期长度 `posControlTowerPeriod`(722)，缺省 1 小时（`starbase.rs:71`）。heartbeat 每分钟 `burn_fuel`（`starbase.rs:817`）：到期塔只要缺任何一种燃料就整体离线（连同子结构），否则扣料、写 `lastFuel`、跑一轮月亮生产。

### 4. 强化（reinforce）

1. `fight::hit_structure`（`fight.rs:598`）在塔被击中后看护盾：`< REINFORCE_BELOW = 0.25`、未强化、未申请过、且塔 `fully_online`，就置 `reinforce_asked` 并投 `Job::Reinforce`。
2. `starbase::reinforce`（`starbase.rs:587`）按 purpose 4 算每周期锶需求 `ceil(quantity * factor) max 1`，可用周期数 = 各资源 `held / 每周期` 的最小值。
3. 没有锶则只写日志，塔保持可被继续打；有锶则一次性烧掉 `periods` 份，`state = REINFORCED`，`stateTimestamp = now + periods * posControlTowerPeriod`。
4. 强化期间 `invulnerable()` 为真，任何伤害被忽略（`fight.rs:602`），所有状态操作被拒；到期由 `pos::step` 转回 `ONLINE`。

建筑被击毁时（`fight.rs:768`、`starbase::lost:633`）：爆炸 + `RemoveBalls`，连同货舱内容删除 `entity` 与 `posStructures` 行；若是塔，子结构置回 `ANCHORED`、`controlTowerID = NULL` 并广播新 slim。攻击塔还会把 `(tower, 攻击者)` 记进 `park.tower_alarms`（上限 64 条），供 bot 防御逻辑取用（`fight.rs:621`）。

### 5. 主权

`posMgr.SetTowerClaim` 写 `claim` 与 `claimSince = NULL`（`starbase.rs:1021`），`GetTowerClaim` 读回。heartbeat 每分钟 `sovereignty(claim_delay_secs)`（`starbase.rs:909`、`heartbeat.rs:163`）：① 对 `claim = 1`、state ∈ {2,3,4,5} 且 `claimSince IS NULL` 的塔写 `now`，对不满足条件的清空；② 只统计 `claimSince <= now - delay` 且星系 `factionID IS NULL` 的塔；③ 按星系、联盟计数；④ `sovereign()`（`starbase.rs:989`）取声明数**严格最多**的联盟，并列时若现任者也在并列者中则保留、否则变无主；⑤ 变化写 `mapSolarSystems.allianceID`，多于 10 个变化只汇总日志。

配置项是 `game.starbaseSpeedup`（`rmr.yml:38`，`RMR_STARBASE_SPEEDUP`，默认 1）与 `game.sovClaimDelaySeconds`（`rmr.yml:41`，`RMR_SOV_CLAIM_DELAY`，默认 518 400 秒 = 6 天，对应客户端"最长六天"）。注意 YAML 键名是 `sovClaimDelaySeconds`，不是 `sovClaimDelay`。

## 与数据库的交互

| 表 | 读/写 | 用途 |
|---|---|---|
| `entity` | 读写 | 一切真实物品：船、pod、无人机、货柜及内容物、建筑、技能物品；`locationID`/`flag`/`quantity`/`ownerID`/坐标 |
| `entity_attributes` | 读写 | 物品级属性：技能点与等级（pod 损失时改） |
| `invTypes` / `invGroups` | 读 | 名称、体积、半径、质量、category/group 判定 |
| `dgmTypeAttributes` | 读 | 类型属性：HP、抗性、伤害、射程、周期、建筑延迟、燃料周期 |
| `mapSolarSystems` / `mapRegions` / `mapConstellations` | 读；主权写 `allianceID` | 安全等级、势力、主权归属、燃料 faction 过滤 |
| `invControlTowerResources` | 读 | 母星每周期燃料与锶需求（purpose 1/2/3/4） |
| `posStructures` | 读写 | 状态、时间戳、控制塔、卫星、护盾/装甲/结构伤害、`lastFuel`、`claim`/`claimSince`、sentry 设置、`provisionType` |
| `posLinks` | 读写 | 月亮生产链（source → type → destination） |
| `invTypeReactions` | 读 | 反应的输入/输出 |
| `TL2MaterialsForTypeWithActivity` | 读 | 制造材料与工具（activity 1）、精炼产物（activity 6） |
| `invBlueprintTypes` / `invBlueprints` | 读；研究/拷贝写 | 蓝图基础数据与个体 ME/PE/剩余授权 |
| `ramAssemblyLines` / `ramAssemblyLineTypes` / `ramAssemblyLineStations` / `...DetailPerGroup` / `...DetailPerCategory` | 读写 | 装配线、线体倍率与费用、`nextFreeTime` |
| `ramJobs` | 读写 | 作业记录、开始/结束时间、交付状态 |
| `staStations` | 读 | 站效率、站方抽成、站所属公司/星系/区域 |
| `insuranceContracts` | 读写 | 保险购买与理赔（理赔后删除） |
| `killLog` / `killLogParticipants` | 写 | 击杀日志与参与者伤害 |
| `character_` | 读写 | 安全等级、余额、当前船、所在站/星系、公司 |
| `corporation` / `alliances` | 读 | 公司/联盟归属（killmail、权限、炮台敌我） |
| `chrNPCStandings` / `ownerStandings` | 读 | 精炼税折扣 / 母星炮台声望阈值（每钟重载） |
| `market_journal` | 写 | 钱包流水：赏金（17）、保险（19）、作业费（56–60） |
| `agtCharMissions` | 读写 | 任务状态；站点清空时置 `CLEARED` |

## 已知限制/未实现行为

- **无玩家系统不战斗**：`fight::step` 只在有玩家的 park 里调用（`heartbeat.rs:178`），bot 之间、NPC 之间、母星防御都只在玩家所在星系发生。
- **无人机**：不支持 `CmdDelegateControl`（明确拒绝）；`CmdAbandonDrone`/`CmdRelinquishControl` 只是变回 Idle，仍属原主；被毁无残骸、无掉落；同时只有一个订单、一个工作目标。
- **NPC**：只有海盗 rat 与 CONCORD；没有 faction navy、officer/commander 特殊掉落；赏金固定为类型的 `entityKillBounty`，不按伤害分配。
- **站点**：只实现代理人遭遇战站点（信标 + 一组 rat）；代码中未见加速轨道、多层死亡空间或可交互建筑（`map::deadspace_complex_map` 返回空表）。
- **POS**：没有燃料块机制，只有 `invControlTowerResources` 的传统燃料；没有跳跃桥、跳跃引擎、诱导力场玩法（`svc/map.rs:7` 的 `TYPE_CYNOSURAL_FIELD` 只用于地图统计既有物品）、跳跃干扰；力场只做小球碰撞与 harmonic 通行；被击毁不掉残骸，货舱内容一并删除。
- **主权**：只在 `factionID IS NULL` 的星系生效；规则是"声明塔数量最多"，代码中未见 TCU/IHub、主权区块与升级。
- **制造/研究**：代码注释明确列出未支持项——公司作业、母星阵列与实验室、发明（无 activity 8 数据）、声望折扣、修改装配线价格（`ram.rs:33`）；拷贝时间 5%/级是自选规则，客户端未说明。
- **精炼**：不模拟矿石专属技能（如 Veldspar Processing），只算 Refining、Refinery Efficiency、Scrapmetal Processing（`reprocessing.rs:9`）。
- **月亮**：数据库没有卫星矿物表，矿物由 `moonID` 确定性派生（`moonmining.rs:12`），同一 moonID 在任何星系结果相同，且无法从零售数据校正。
- **战斗数值**：只实现炮/导弹/护盾/装甲/结构/电容/网子/扰频/ECM/减锁/扰断/标记；没有立体炸弹、跃迁干扰场、其它电子战；伤害只有四类。
- **锁定**：`Lock` 只有 Pending/Locked 两态，没有锁定失败或锁定队列；同时锁定数只由 `maxLockedTargets` 决定。
- **掉落**：战利品只从市场价格表挑模块与弹药，不读 rat 专属掉落表；玩家船幸存率固定 50%，与船型、伤害来源无关。
- **犯罪**：没有通缉/赏金猎杀系统；pod 击杀安全惩罚只按星系安全系数，不区分受害者身份。
- **克隆**：pod 损失后一律给 Alpha clone；没有 clone 分级自动降级逻辑，只有 `medical` 服务里的手动更换。
