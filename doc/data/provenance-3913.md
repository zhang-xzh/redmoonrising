# 3913 客户端与数据库溯源

`db/*.sql.gz` 是 2006 年那代服务端的 **PostgreSQL 运行库转储**，不是 CCP 官方 SDE，也没有
build/版本列；客户端 `script/compiled.code.vanilla` 目前缺失。所以“数据是不是 build 3913
这一版”没有签名可查，只能靠内容锚点和客户端交叉校验。本页记录当前能确认的结论、证据和复跑方式；
工具在 `tools/data-provenance/`（`provenance.py` + 基线 JSON）。

## 结论

- **数据是 2006 年（RMR/Blood 前后）的运行库**：13,261 types、5,334 星系、66 区域，有首都舰，
  没有 rigs/contracts/Marauder/T3/Orca。
- **但没有证据证明它是 build 3913 那一刻的快照**：没有版本表，dump 是近年用 PostgreSQL 16.15
  重新导出的；另有两处与客户端不一致（见下）。
- **客户端侧反而是确定的**：`boot.ini` 写死 `version=2.10 / build=3913 / codename=Blood`，
  `messages.txt` 的 `ReleaseSubtitle=Red Moon Rising`，字节码里没有 rig/contract/invention。
- 使用规则：**数据当“RMR 时代快照”用；凡与客户端冲突，以客户端字节码/行为为准**，并在相关文档
  写明取值来源。

## 为什么不能直接确定

- `schema_migrations` 为空（0 行），`eveConstants` 没有 version/build 项。
- `db/*.sql.gz` 头是 `PostgreSQL 16.15` + `\restrict` 标记（2024+ 的 `pg_dump`），说明是
  **近年重新导出**的产物，不是 2006 原件；中间是否被修补过，文件本身证明不了。
- `db/` 还是“运行库”：除了静态表，还有 `character_`（11 万）、`corporation`（4,291）、
  `market_orders`（57.8 万）、`bots`（10 万）、`cacheLocations` 等；这些是模拟器/运行数据，
  不属于静态数据。

## 内容锚点（`db-snapshot-3913.json`）

| 表 | 行数 | | 标记 | 值 |
|---|---|---|---|---|
| `invTypes` | 13,261 | | `capital_groups`（Titan/Dread/Carrier） | 3 |
| `invGroups` | 559 | | `titan_types` | 4 |
| `invCategories` | 21 | | `command_ships` | 8 |
| `dgmAttributeTypes` | 987 | | `rig_groups` | **0** |
| `dgmEffects` | 1,671 | | `marauder_types`（Golem/Paladin/Vargur/Kronos） | **0** |
| `invBlueprintTypes` | 2,394 | | `blackops_types` | **0** |
| `mapSolarSystems` | 5,334 | | `jumpfreighter_types` | **0** |
| `mapRegions` | 66 | | `t3_types`（Tengu 等） | **0** |
| `staStations` | 5,042 | | `orca_rorqual` | **0** |
| `agtAgents` | 10,270 | | `contract_tables` | **0** |
| `eveMessages` | 1,781 | | `invention_activity` | **1** |
| `ramActivities` | 9 | | `max_type_id` / `max_solar_system_id` | 25,388 / 30,005,334 |

- 有：Titan/Dreadnought/Carrier（Avatar/Erebus/Leviathan/Naglfar、Archon/Nidhoggur/Nyx…）、
  Command Ships、Exhumers（Hulk/Mackinaw/Skiff）、海盗战列、Branch/Deklein/Venal/Tenal/Cache/
  Detorid 等区域 → **RMR（2005-12）之后**。
- 没有：Rigs、Contracts、Marauder、Black Ops、Jump Freighter、T3、Orca/Rorqual、
  Sisters 船 → **2007 年之前**。
- **异常点**：`ramActivities` 里有 `Invention`（activityID 8，published=1），但 3913 客户端
  字节码里没有任何 invention UI/逻辑。可能是上线前预种的数据，也可能这份 DB 来自稍晚的快照或混合来源。

## 客户端锚点

- `boot.ini`：`version=2.10 / build=3913 / codename=Blood`；`res/common/messages.txt`：
  `ReleaseSubtitle=Red Moon Rising`。
- 字节码扫描（`tools/localization/scan.py` + 本工具）：没有 `rigSlot`/`rigs`、没有
  contracts 系统、没有 invention；`messages.txt` 里的 `ReleaseSubtitle` 与 `boot.ini` 同代。
- `script/` 下现有文件：`compiled.code`（零售原版，sha256 `daa5eae3…`，md5 `36e18ef3…`）、
  `compiled.code.zh-prev-20261101-194509`（上一版中文包，7,926,678 字节，md5 `251dfdef…`）、
  `run.py`；**`compiled.code.vanilla` 不存在**。

## 交叉校验（`check`）

客户端 `compiled.code` 里按字节码提取到 **254 个消息键**（`eve.Message('Key')` /
`cfg.GetMessage('Key')` / `mls.KEY`，只收常量第一个参数）：

| 来源 | 命中 |
|---|---|
| `res/common/messages.txt` | 81 |
| `db/eveMessages` | 172 |
| 两边都没有 | **1**：`NotAtStation`（`ui/services/clonejumpsvc.py`） |

- `NotAtStation` 是真实的漂移：客户端调用 `eve.Message('NotAtStation')`，但 `messages.txt` 与
  `eveMessages` 都没有这个键；触发时客户端会显示 `Message not found::Message: 'NotAtStation'`。
  这是“客户端与这份数据不是严格同一快照”的直接证据。
- 反向：`eveMessages` 有 1,609 个键没有被客户端字面引用——服务端可以主动发消息键，属于正常，
  不构成版本证据。

## 工具与基线

```powershell
$PY = 'C:\Users\zhang\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe'
& $PY tools\data-provenance\provenance.py manifest --out tools\data-provenance\manifest-3913.json
& $PY tools\data-provenance\provenance.py manifest --verify tools\data-provenance\manifest-3913.json
& $PY tools\data-provenance\provenance.py snapshot --out tools\data-provenance\db-snapshot-3913.json
& $PY tools\data-provenance\provenance.py check --snapshot tools\data-provenance\db-snapshot-3913.json
```

- `manifest-3913.json`：430 个文件（客户端 218 + db 212），每个带 size + sha256；当前 `--verify`
  0 问题。
- `db-snapshot-3913.json`：上表的行数、标记和 1,781 个 `messageID`。
- 工具只读：不写客户端、不写数据库、不改 `db/`。

## 使用规则

- 改客户端（`compiled.code`、`messages.zh.txt`）或改 `db/` 前后各跑一次 `manifest --verify`，
  确认只有预期文件变化。
- 新增/翻译数据后跑 `check`，避免把客户端不认识的键（或缺失的键）带进游戏。
- 数据来源写进相关文档时，注明“RMR 时代快照、无 build 证明”；与客户端冲突时以客户端为准。
- `NotAtStation` 目前**保留现状**（未补数据、未改客户端）；要么在 `eveMessages`/`messages.txt`
  补这个键，要么改 `clonejumpsvc` 的调用，二者都要按功能修改流程落文档。

## 缺口与后续

- **补回 `compiled.code.vanilla`**：从 `M:\EVE-LOCAL\inputs\EVE-Online-3913-code\dist\compiled.code`
  （sha256 与零售原版一致）复制回客户端并纳入 manifest，避免下次重置无基线。
- 想要更强的版本判定，需要 3913 的官方静态数据基线（不存在公开 SDE）；剩下的只能逐项内容比对
  （客户端常量 ↔ DB ID、协议字段、消息键），本工具已覆盖消息键这一层。
