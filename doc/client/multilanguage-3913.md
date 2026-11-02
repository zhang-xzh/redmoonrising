# build 3913 多语言方案（Red Moon Rising）

面向 3913 客户端的多语言改造记录。当前状态：

- **已实现**：ESC → Language 列表（`languages` 表 11 行，`util.Rowset`）、
  `authentication.SetLanguageID`（改 session、写 `account."languageID"`、发 session change）、
  五个乱码语言名的启动修复、服务端静态数据的 EN/ZH 两套 bulk（ZH 走
  `config/server-i18n/server_zh.json` 覆盖层，其余语言回落英文）。
- **未实现**：教程/幻灯片按语言查库、动态 RPC 返回名称的翻译、其他语言覆盖层、
  多份 `compiled.code` 的 UI 文案切换（客户端当前是中文单语言包）。

本文记录零售机制、当前实现和剩余阶段；未实现的部分明确标为“计划”。

客户端汉化流水线（把英文字符串改成中文并重新打包 `compiled.code`）见
`doc/client-localization-3913.md`；本文只讨论运行期多语言与服务器数据语言。

## 1. 目标与边界

目标：

- ESC → Language 能列出 `languages` 表的 11 种语言，能勾选、能持久化。
- 切换后，客户端的本地消息、教程、幻灯片、服务端静态名称/描述按所选语言显示；缺翻译时回落英文。
- 语言状态在客户端 `prefs`、服务器 session、`account."languageID"` 三处一致。

非目标：

- 不翻译玩家生成内容（角色名、军团名、联盟名、聊天、邮件）。
- 不把现代 EVE（3396210 等）的类型/属性/市场数值当成本项目的取值依据。翻译文本可以参考现代
  本地化表，但条目必须按 3913 的 `messageID` / `typeID` 对齐；数值与名称以 3913 客户端和 `db/` 为准。
- 不在本阶段做客户端 UI 文案的运行期热切换（`compiled.code` 在进程启动时载入，见第 3 节）。

## 2. 零售机制与当前状态

### 2.1 语言列表与切换链路（客户端字节码为准）

- `SystemMenu.Language` 通过 `eve.LocalSvc('gameui').GetLanguages()` 取列表，每项显示
  `translatedLanguageName or languageName`，勾选条件是 `languageID == eve.session.languageID`。
- 勾选后 `SystemMenu.CheckBoxChange` 的 `config == 'language'` 分支：

  ```python
  langID = checkbox.data['value']
  uthread.new(eve.LocalSvc('gameui').SetLanguage, langID)
  if langID != 'EN':
      cfg.ReloadMessages(langID)
      eve.Message('MlsNotifyCaveats')
  ```

- `GameUI.SetLanguage`：

  ```python
  if key in self.GetLanguageIDs():
      eve.RemoteSvc('authentication').SetLanguageID(key)
      prefs.languageID = key
  ```

  它只改 `prefs.languageID`，不改 `eve.session.languageID`；后者只能由服务器下发的 session change 更新。

- `cfg.ReloadMessages(langID)` → `Config.__LoadStaticData(langID)`：先读
  `res:/common/messages.txt`，再按 `langID.lower()` 读 `res:/common/messages.<lang>.txt`。
  纯本地文件，无 RPC。

- 登录时 `machoNet.MachoNetService.Authenticate` 把 `prefs.GetValue('languageID','EN')` 写进
  `clientinfo['languageID']`；客户端 `Session.GetDefaultValueOfAttribute('languageID')` 也回退到同一个 pref。
- `GameUI.OnSessionChanged` 遇到只含 `languageID` 的 session change 直接 `return`，不重建 UI。

验证命令：

```powershell
$PY='C:\Users\zhang\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe'
& $PY tools\client-code\scan.py dis "script:/ui/shared/systemmenu.py/SystemMenu/CheckBoxChange"
& $PY tools\client-code\scan.py dis "script:/parklife/gameui.py/GameUI/SetLanguage"
& $PY tools\client-code\scan.py dis "script:/../../common/script/sys/cfg.py/Config/ReloadMessages"
& $PY tools\client-code\scan.py dis "script:/../../common/script/sys/cfg.py/Config/__LoadStaticData"
& $PY tools\client-code\scan.py dis "script:/parklife/gameui.py/GameUI/OnSessionChanged"
```

### 2.2 服务器会话与数据下发

- 登录时 `crates/eve-server/src/conn/auth.rs:87` 从 `clientinfo.languageID` 取一次，存进
  `Session.language_id`；`crates/eve-server/src/session.rs:10-15` 把 `languageID` 列进 `PERSIST_VARS`，
  `change_from` 会把它作为 session change 发出。
- `crates/eve-server/src/conn/language.rs` 的 `Conn::set_language` 接管
  `authentication.SetLanguageID`（`conn/mod.rs` 在 dispatch 前特判，因为要改 session）：校验
  `languages` 表、更新 `Session.language_id`、写 `account."languageID"`、
  用 `send_session_change_from` 下发 `languageID` 变更。未知 ID 保持原值。登录路径在
  `conn/auth.rs` 以 `clientinfo.languageID` 为准，缺失时用账户值，再缺失才 `EN`。
- `crates/eve-server/src/svc/language.rs` 的 `GetLanguages` 读 `languages` 表并返回
  `util.Rowset`（11 行，三列 `languageID/languageName/translatedLanguageName`）。客户端按行属性
  取值，普通 `Value::List` 会抛 `AttributeError`，见 `doc/issues/rmr-issue-language-list-empty.md`。
- 静态数据现在是 `BulkSet`：英文 `BulkData` 加每个 `server_<lang>.json` 构建的一份翻译版
  （`crates/eve-server/src/bulkdata.rs`、`main.rs`），`Ctx.bulk` 与登录 init vals 按
  `session.language_id` 选版本（`BulkSet::for_lang`，未知/缺翻译语言回落英文）。
  各语言 bulk 的文本不同，checksum 也不同；客户端登录时按 init vals 里的版本重新取。
- 切换语言仍**不会**让已登录客户端主动重拉 bulk：客户端已缓存的对象继续用旧语言，重登才换成新语言。
- `config.BulkData.messages` 来自 `eveMessages`（当前库 1781 行，英文）。客户端 `cfg.GotInitData`
  先加载服务端版本，最后调用 `Config.__LoadStaticData()` 用本地 `messages.txt` +
  `messages.<lang>.txt` 覆盖。**本地消息文件永远赢**，所以 UI 消息不能在服务端翻译。

### 2.3 语言相关的服务器接口

客户端显式传 `languageID` 的 RPC 只有：

- `tutorialSvc.GetTutorials(languageID)`
- `tutorialSvc.GetTutorialInfo(tutorialID, languageID)`
- `languageSvc.GetTextsForGroup(textGroup, languageID)`（幻灯片文本）

它们都是用到时才请求，参数来自 `eve.session.languageID`。客户端缓存按语言分 key：
`tutorialSvc.tutorials[languageID]`、`tutorialInfos[(tutorialID, languageID)]`，所以 session 语言更新后
会自然重新请求。

`mlsUtil.Mls.LoadLanguagePack` → `languageSvc.GetMessagesByLanguageID` 在 3913 客户端没有调用点；
`mls` 全局对象只作为 `cfg.evemessages` 的懒加载访问器（`Mls.__getattr__`）。

RMR 现状：`tutorialSvc` 忽略 `languageID`（`crates/eve-server/src/svc/tutorial.rs`），
`languageSvc.GetTextsForGroup` 返回空 rowset（`crates/eve-server/src/svc/language.rs`）。

### 2.4 零售数据现状

- `res/common/messages.de/es/fr/it/ja/ko/pt/ru/zh.txt` 每个只有一条 `MlsNotifyCaveats`，
  内容就是“并非全部文本都有该语言，缺的用英语”；`messages.is.txt` 约 1.3 KB。
- `db/` 里只有 `languages` 和 `account` 两张表带 `languageID`；`tutorials`、`tutorial_pages`、
  `eveMessages` 都没有语言列。
- `languages` 表 11 行（EN/DE/FR/ES/IS/IT/PT/RU/JA/KO/ZH）；IS/JA/KO/RU/ZH 的
  `translatedLanguageName` 在官方转储里是双重编码乱码。服务端启动时
  `db::repair_language_names` 幂等修成 `Íslenska` / `日本語` / `한국어` / `Русский` / `中文`，
  `db/*.sql.gz` 保持原样。

结论：零售 3913 没有“同一 ID 的多语言版本”可返回；切换语言最多改变本地消息文件和 ZH 字体回退。
多语言内容需要本项目自行补齐，并明确标为非零售数据。名称层按 3913 英文原文从现代本地化表
（3396210）对齐，属于“非零售补齐”，未匹配的行保持英文。

## 3. 分层方案与当前状态

| 层 | 数据来源 | 切换是否即时 | 当前状态 |
|---|---|---|---|
| 客户端硬编码文案 | `compiled.code` 字符串 | 否（进程启动时载入） | 单语言构建（当前中文包）；计划按语言出多份，启动器选 |
| 客户端消息 | `res/common/messages.<lang>.txt` | 是 | 零售框架已支持；翻译文件按需扩充（阶段 2） |
| 服务端静态数据 | 登录时 `config.BulkData.*` | 否（重登才取） | **已实现** EN + `server_<lang>.json` 覆盖层；当前只有 ZH |
| 服务端动态数据 | 教程、幻灯片、任务等 RPC | 是 | 未实现（阶段 4） |
| 玩家生成内容 | 角色/军团/联盟名 | 不翻译 | — |

关键约束：

- UI 消息必须在本地 `messages.<lang>.txt`，因为 `cfg.__LoadStaticData` 会用本地文件覆盖服务端
  `eveMessages`。
- 静态 bulk 没有运行期刷新路径；切换语言后必须重登，或另做客户端补丁重新拉取（不推荐）。
- `compiled.code` 的文案是编译期写死的；运行期切换 UI 语言不在本阶段范围。

## 4. 实施阶段

### 阶段 0：定位与文档（完成）

`doc/issues/rmr-issue-language-list-empty.md` 已记录现象与根因，状态为已修复，并链接本文。

### 阶段 1：会话闭环（完成）

1. `crates/eve-server/src/svc/language.rs`：`GetLanguages` 读 `languages` 表并返回
   `util.Rowset`（11 行，三列）。
2. `crates/eve-server/src/conn/language.rs`：`Conn::set_language` 接管
   `authentication.SetLanguageID`（`conn/mod.rs` dispatch 前特判）：校验 `languages` 表、
   改 `Session.language_id`、写 `account."languageID"`、下发 session change。未知 ID 保持原值。
3. `crates/eve-server/src/conn/auth.rs`：登录语言以 `clientinfo.languageID` 为准，
   缺失时取 `account."languageID"`，再缺失才 `EN`；变化时写回账户。
4. `crates/eve-server/src/db.rs::repair_language_names`：启动时幂等修复 IS/JA/KO/RU/ZH 的
   双重编码语言名，官方 `db/` 不动。

验证见第 6 节。

### 阶段 2：客户端消息层（计划，即时生效）

1. 扩充 `res/common/messages.<lang>.txt`，至少覆盖客户端实际用到的 `eveMessages` key；中文可先生成
   全量，其他语言按需。
2. 可选客户端补丁：`SystemMenu.CheckBoxChange` 只在 `langID != 'EN'` 时 `ReloadMessages`，
   切回 EN 不会恢复英文；要完整就改成始终调用 `cfg.ReloadMessages(langID)`。
3. 字体：ZH 已有 `fontsvc.GetFallbackFonts` 的 simsun/simkai/simhei 回退；RU/JA/KO 要实测字形覆盖，
   必要时扩 `fontsvc` 或随客户端带字体。
4. 本层切换后立即生效，不需要重登。

### 阶段 3：服务端静态数据（完成 EN/ZH，重登生效）

1. **翻译存储**：JSON 覆盖层 `config/server-i18n/server_<lang>.json`，结构为
   “表 → 列 → 主键 → 文本”：

   ```json
   {
     "invTypes": {
       "typeName": { "587": "裂谷级" },
       "description": { "587": "…" }
     },
     "invGroups": { "groupName": { "25": "…" } }
   }
   ```

   不是每个文件都要全量；缺的单元格回落英文。服务端在启动时读取目录里所有
   `server_<lang>.json`（`crates/eve-server/src/i18n.rs`），目录由
   `server.localization` / `RMR_LOCALIZATION` 指定，默认 `config/server-i18n`；
   `docker-compose.yml` 把它只读挂进容器。
2. **每语言 bulk**：`crates/eve-server/src/bulkdata.rs` 的 `BulkSet`
   持有英文 `BulkData` 和每个覆盖层构建的翻译版；`translate()` 按
   “bulk 对象 → 官方表”（如 `config.BulkData.types` → `invTypes`）替换覆盖层命中的字符串列，
   主键是每行的第一列。`init_vals()` 和 `GetCachableObject`（`svc/login.rs`）按
   `session.language_id` 选版本（`BulkSet::for_lang`），未知/无覆盖层语言回落英文。
   各语言文本不同，checksum 自然不同，客户端重登会重新取。
3. **覆盖范围**：`invTypes`（typeName/description）、`invGroups`、`invCategories`、
   `invMetaGroups`、`dgmAttributeTypes`、`dgmEffects`、`billTypes`、`ramAssemblyLineTypes`、
   `ramActivities`、`ramCompletedStatuses`、`eveRoles`、`eveFlags`、`chrRaces`、`chrBloodlines`、
   `eveStatistics`、`eveUnits`、`channelTypes`、`eveStaticLocations`（星系/空间站名）。
   玩家生成名字不翻；`config.BulkData.messages` 不翻（本地消息文件优先）。
4. **数据生成**：客户端仓库的 `tools/localization/build_server_map.py`
   （`M:\EVE-LOCAL\inputs\EVE-Online-3913-code\tools\localization\build_server_map.py`）读取 3396210 的
   `loc_en.json` + `client_localization_fsd_zh.json`，按 **3913 英文原文精确匹配**
   （名称再做大小写去空白匹配），写 `config/server-i18n/server_zh.json`。
   当前产物 1.18 MB、19534 条文本：13261 个类型里 9193 个 `typeName`、5862 条 `description`；
   559 个组里 483 个 `groupName`；11261 个静态地点里 2184 个名字。
   匹配是“原文相同才翻”，不是按 ID 猜测，所以改过文案的条目不翻、保持英文。

   **译文来源（可复现）**：

   - 英文侧：`M:\EVE-LOCAL\EveJS\tools\FsdDump\dump_localization.py`
     从 `M:\EVE-LOCAL\inputs\EVE-Online-3396210` 导出 `--lang en-us`，得到
     messageID → 英文（默认落在 `%TEMP%\opencode\loc_en.json`，可用 `RMR_LOC_EN` 覆盖）。
   - 中文侧：`M:\EVE-LOCAL\EveJS\config\client_localization_fsd_zh.json`，
     同一 3396210 客户端的 messageID → 中文。
   - 两个文件按 messageID 配对成“英文原文 → 中文”；生成器再拿 3913 `db/*.sql.gz` 里的英文原文
     去查这张表。3396210 只提供**译文文本**，类型/属性/市场数值一律仍以 3913 `db/` 为准。
   - 默认路径写死在 `build_server_map.py` 顶部（`EN_JSON` / `ZH_JSON`），换机器时用
     `--en` / `--zh` 显式指定。
5. **生效方式**：改覆盖层→重启服务端（无需重建镜像，目录是挂载的）；改代码→重建镜像。
   语言在客户端重登后生效。
6. **成本**：启动时多构建一套 bulk；实测 EN 2.6s / ZH 2.5s、各 2.0 MB，
   内存与启动时间约为单语言的 2 倍。

### 阶段 3b：动态返回的名称（计划）

名称不只出现在 bulk：`config` / `lookup` / `market` / `agentMissions` 等服务直接查
`invTypes.typeName`、`mapSolarSystems.solarSystemName`、`staStations.stationName` 等。
这些需要按 `session.language_id` 套同一份覆盖层（或按语言查库），并按调用点逐一接线。
在那之前，只有登录 bulk 覆盖的部分（物品/组/地点等）会显示中文。

### 阶段 4：教程 / 幻灯片 / 动态文本（计划，即时生效）

- `crates/eve-server/src/svc/tutorial.rs`：`GetTutorials` / `GetTutorialInfo` 使用传入的
  `languageID`（或 `ctx.session.language_id`），查对应语言数据。
- `crates/eve-server/src/svc/language.rs` 的 `GetTextsForGroup`：按 `languageID` 查。
- 任务文本：如果服务端直接拼字符串，按语言替换；如果发的是 messageID + args，走阶段 2 的本地消息文件。
- 客户端已按语言分 key 缓存教程/幻灯片，切换后新打开的窗口会重新请求。

### 阶段 5：客户端 UI 文案（计划，最后做）

`compiled.code` 的文案是编译期写死的，运行期无法切换。两个方向：

- 推荐：按语言生成多份 `compiled.code`（`compiled.code.en` / `.zh` / …），启动器按语言选一份；
  ESC 切换后提示“重启客户端以应用界面语言”。最贴合零售结构。
- 长期：把可翻译的 UI 文案迁到 `messages.<lang>.txt`，用 message ID 查表。能运行期切换，但几千条
  字符串，还要避开标识符/键名，风险和工作量都大。

## 5. 数据模型与产物

采用 JSON 覆盖层（阶段 3 已落地）：

| 项 | 位置 |
|---|---|
| 覆盖层文件 | `config/server-i18n/server_zh.json`（每个语言一份，按 `server_<lang>.json` 识别） |
| 生成器 | 客户端仓库 `tools/localization/build_server_map.py`（读 3913 `db/*.sql.gz` 与 3396210 本地化表） |
| 加载/选择 | `crates/eve-server/src/i18n.rs`、`bulkdata.rs`（`BulkSet`、`translate`） |
| 配置 | `rmr.yml` 的 `server.localization` / `RMR_LOCALIZATION`，默认 `config/server-i18n` |
| 容器 | `docker-compose.yml` 只读挂载 `./config/server-i18n:/app/config/server-i18n` |

未选其他方案的原因：Postgres 翻译表要迁移现有卷（`db/` 只在空卷初始化一次）；
每语言列/表会让 schema 和官方数据一起膨胀。JSON 覆盖层可 diff、可只翻一部分、不改官方 `db/`。

## 6. 验证矩阵与实测

| 场景 | 预期 / 实测 |
|---|---|
| 新账号登录 | `GetLanguages` 为 `util.Rowset`、11 行；session change `languageID -> EN` |
| 切到 ZH | `SetLanguageID` 返回 None，session change `"EN" -> "ZH"`，`account."languageID"` 写 ZH |
| 非法 languageID | 无 session change、账户不变、只 warn |
| 登录 `--lang ZH` | 38 个 cached object 全部解码；debug 日志显示 `config.BulkData.types` 替换 15053 条 |
| 缺翻译的单元格 | 保持英文，不报错 |
| 教程/幻灯片 | 仍为英文（阶段 4 未做） |

命令：

```powershell
cargo build -p eve-server
cargo test -p eve-server
cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000 --no-cache --script <脚本>
cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000 <user> <pass> --lang ZH
docker compose exec -T postgres psql -U rmr -d rmr -c 'select "languageID" from account where "accountID"=1;'
docker compose logs server --tail 100 | Select-String "bulk data|localization|language"
```

`fakeclient` 的 `--lang <ID>` 把该 ID 写进 clientinfo 的 `languageID`，用于无头验证语言选择。

## 7. 风险与约束

- 客户端本地消息覆盖服务端 `eveMessages`：UI 消息必须走本地文件，不要在服务端翻译 `eveMessages` 后
  期待生效。
- 每种语言多一套 bulk，内存/启动时间线性增加；当前只有 EN/ZH，新增语言前先看启动耗时。
- 客户端 bulk 缓存按 checksum/版本失效；语言内容不同必须产生不同 checksum，否则重登不会重取。
- `compiled.code` 文案编译期写死：UI 语言只能按构建切换，或大改消息化。
- `SetLanguageID` 是 session 变更，必须走 conn 层；`Ctx.session` 是只读的，服务 handler 改不了。
- 语言名修复是服务端启动时的幂等 UPDATE；官方 `db/*.sql.gz` 不动，重播种卷会恢复乱码并由启动修复再改回。
- 名称层翻译来自 3396210 的本地化表，按 3913 英文原文对齐，属**非零售补齐**；未匹配项保持英文，
  不臆造译文。
- 客户端 `SetLanguage` 通过 `uthread.new` 异步执行，UI 不等待；session change 可能稍晚到达，属正常。

## 8. 关联

- 客户端：`ui/shared/systemmenu.py`、`parklife/gameui.py`、`external/common/script/sys/cfg.py`、
  `external/common/script/sys/sessions.py`、`external/common/script/sys/mlsUtil.py`、
  `ui/services/tutorialsvc.py`、`ui/services/slides.py`、`ui/services/fontsvc.py`
- 服务端：`crates/eve-server/src/svc/language.rs`、`svc/login.rs`、`svc/tutorial.rs`、
  `conn/auth.rs`、`conn/language.rs`、`conn/mod.rs`、`session.rs`、`bulkdata.rs`、`i18n.rs`、`db.rs`、`svc/rows.rs`
- 数据：`db/languages.sql.gz`、`db/account.sql.gz`、`db/eveMessages.sql.gz`
- 工具：客户端仓库 `tools/localization/build_server_map.py`、`config/server-i18n/server_zh.json`
- 文档：`doc/client-localization-3913.md`（单语言汉化流水线）、
  `doc/issues/rmr-issue-language-list-empty.md`（列表为空现象）、`doc/client/client-code-baseline.md`
