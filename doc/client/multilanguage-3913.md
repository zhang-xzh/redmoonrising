# build 3913 多语言方案（Red Moon Rising）

面向 3913 客户端的多语言改造计划。当前状态是“只有零售框架、没有实现”：ESC → Language 列表为空，
`authentication.SetLanguageID` 在 RMR 里是空实现，服务端静态数据只有英文，客户端 `compiled.code`
是单语言构建。本文记录零售机制、当前缺口和分阶段方案；未实现的部分明确标为“计划”。

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
- `crates/eve-server/src/svc/login.rs:24` 的 `SetLanguageID` 目前返回 `Value::None`，不改 session、
  不写 `account."languageID"`、不发 session change。运行期切换因此不会更新服务器。
- `crates/eve-server/src/svc/language.rs:12` 的 `GetLanguages` 返回普通 `Value::List`，客户端按行属性
  取值时抛 `AttributeError: 'list' object has no attribute 'languageID'`，所以列表为空。这是
  `doc/issues/rmr-issue-language-list-empty.md` 记录的现象。
- 静态数据在服务端启动时构建成一份全局 `BulkData`（`crates/eve-server/src/bulkdata.rs:141-143`），
  `entries` 以 `config.BulkData.types` 这类 key 索引，**没有语言维度**，所有会话共享。登录时通过
  `config.BulkData.*` 一次性下发（`crates/eve-server/src/bulkdata.rs:44-129`），客户端缓存，切换语言
  不会重新请求。
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
  `translatedLanguageName` 在官方转储里是乱码，客户端用 `translatedLanguageName or languageName`，
  直接开放列表会显示乱码标签。

结论：零售 3913 没有“同一 ID 的多语言版本”可返回；切换语言最多改变本地消息文件和 ZH 字体回退。
多语言内容需要本项目自行补齐，并明确标为非零售数据。

## 3. 分层方案

| 层 | 数据来源 | 切换是否即时 | 方案 |
|---|---|---|---|
| 客户端硬编码文案 | `compiled.code` 字符串 | 否（进程启动时载入） | 按语言生成多份 `compiled.code`，启动器选一份；长期再考虑改成消息 ID |
| 客户端消息 | `res/common/messages.<lang>.txt` | 是 | 扩充翻译文件；`cfg.ReloadMessages` 已支持 |
| 服务端静态数据 | 登录时 `config.BulkData.*` | 否（重登才取） | 服务端按语言构建/缓存 bulk，重登生效 |
| 服务端动态数据 | 教程、幻灯片、任务等 RPC | 是 | handler 读 `session.languageID`，按语言查询 |
| 玩家生成内容 | 角色/军团/联盟名 | 不翻译 | — |

关键约束：

- UI 消息必须在本地 `messages.<lang>.txt`，因为 `cfg.__LoadStaticData` 会用本地文件覆盖服务端
  `eveMessages`。
- 静态 bulk 没有运行期刷新路径；切换语言后必须重登，或另做客户端补丁重新拉取（不推荐）。
- `compiled.code` 的文案是编译期写死的；运行期切换 UI 语言不在本阶段范围。

## 4. 实施阶段

### 阶段 0：定位与文档

- 把“语言列表为空”从独立缺陷改归入本计划：保留
  `doc/issues/rmr-issue-language-list-empty.md` 的现象、根因和修复步骤，状态改为“计划中（多语言阶段 1）”，
  并链接本文。
- 本文作为多语言主题文档，登记到 `doc/knowledge-inventory.md`。

### 阶段 1：会话闭环

目标：列表能显示、能勾选、状态一致，服务器和客户端都知道新语言。

1. `crates/eve-server/src/svc/language.rs`
   - `GetLanguages` 改成 `rowset()`，读 `languages` 表：

     ```sql
     SELECT "languageID","languageName","translatedLanguageName"
       FROM languages ORDER BY "languageID"
     ```

   - 处理 `translatedLanguageName` 乱码：修 IS/JA/KO/RU/ZH 五行数据，或让客户端回退到
     `languageName`。
2. `crates/eve-server/src/conn/mod.rs`
   - 在 `character.SelectCharacterID` 特判处（`conn/mod.rs:242`）加
     `authentication.SetLanguageID` 特判，交给 conn 处理，因为要改 session。
3. 新增 `crates/eve-server/src/conn/language.rs`
   - 校验语言 ID 是否在 `languages` 表；
   - 更新 `Session.language_id`；
   - 更新 `account."languageID"`；
   - 用 `send_session_change_from(&before)` 下发 change（`conn/mod.rs:400-410`）。
4. `crates/eve-server/src/conn/auth.rs:87`
   - 明确登录语言来源。建议 `clientinfo.languageID`（客户端 prefs）为准，登录时写回
     `account."languageID"`；`SetLanguageID` 再更新两者。这样 `prefs`、session、account 一致。
5. 验证：`fakeclient` 断言 `GetLanguages` 是 rowset 且 11 行；`SetLanguageID("ZH")` 后 session change
   含 `languageID=ZH`，数据库已更新。

### 阶段 2：客户端消息层（即时生效）

1. 扩充 `res/common/messages.<lang>.txt`，至少覆盖客户端实际用到的 `eveMessages` key；中文可先生成
   全量，其他语言按需。
2. 可选客户端补丁：`SystemMenu.CheckBoxChange` 只在 `langID != 'EN'` 时 `ReloadMessages`，
   切回 EN 不会恢复英文；要完整就改成始终调用 `cfg.ReloadMessages(langID)`。
3. 字体：ZH 已有 `fontsvc.GetFallbackFonts` 的 simsun/simkai/simhei 回退；RU/JA/KO 要实测字形覆盖，
   必要时扩 `fontsvc` 或随客户端带字体。
4. 本层切换后立即生效，不需要重登。

### 阶段 3：服务端静态数据（重登生效）

这是工作量最大的一层。

1. 翻译存储：优先用文件覆盖层 `config/localization/server_<lang>.json`，不动官方 `db/`。
   结构按“表 + 列 + 主键”索引：

   ```json
   {
     "invTypes": {
       "typeName": { "587": "…" },
       "description": { "587": "…" }
     },
     "invGroups": { "groupName": { "25": "…" } }
   }
   ```

   服务端启动时加载到内存，查不到回落英文。数据量大时再考虑 Postgres
   `translation(languageID, tableName, keyID, columnName, text)` 表；现有卷不会重跑 `db/` 初始化，
   需要单独的应用脚本。
2. `crates/eve-server/src/bulkdata.rs`：把单一 `BulkData` 改成按语言懒构建（EN 启动时构建，其他语言
   首次登录/切换时构建并缓存）；`init_vals()` 和 `GetCachableObject`（`svc/login.rs`）按当前 session
   的 `language_id` 选版本。必须保证每个语言版本的 checksum 不同，否则客户端重登不会重取。
3. 范围：先做名称类 `invTypes.typeName/description`、`invGroups`、`invCategories`、
   `invMetaGroups`、区域/星座/星系/空间站名、`billTypes`、`ram*`、`channelTypes`、`units`、
   `races`、`bloodlines`；玩家生成名字不翻。
4. 生效方式：重登客户端。

### 阶段 4：教程 / 幻灯片 / 动态文本（即时生效）

- `crates/eve-server/src/svc/tutorial.rs`：`GetTutorials` / `GetTutorialInfo` 使用传入的
  `languageID`（或 `ctx.session.language_id`），查对应语言数据。
- `crates/eve-server/src/svc/language.rs` 的 `GetTextsForGroup`：按 `languageID` 查。
- 任务文本：如果服务端直接拼字符串，按语言替换；如果发的是 messageID + args，走阶段 2 的本地消息文件。
- 客户端已按语言分 key 缓存教程/幻灯片，切换后新打开的窗口会重新请求。

### 阶段 5：客户端 UI 文案（可选，最后做）

`compiled.code` 的文案是编译期写死的，运行期无法切换。两个方向：

- 推荐：按语言生成多份 `compiled.code`（`compiled.code.en` / `.zh` / …），启动器按语言选一份；
  ESC 切换后提示“重启客户端以应用界面语言”。最贴合零售结构。
- 长期：把可翻译的 UI 文案迁到 `messages.<lang>.txt`，用 message ID 查表。能运行期切换，但几千条
  字符串，还要避开标识符/键名，风险和工作量都大。

## 5. 数据模型对比

| 方案 | 优点 | 缺点 |
|---|---|---|
| JSON 覆盖层（推荐先做） | 不动 `db/`、不需迁移现有卷、可 diff、可只翻一部分 | 数据量大时内存/启动时间增加；改文件要重启服务端 |
| Postgres 翻译表 | SQL join、单一大表、便于统计 | 现有卷不会重跑 `db/` 初始化，需要应用脚本；表结构变更 |
| 每语言列（`typeName_zh`） | 查询简单 | 11 种语言列爆炸，schema 改动大 |
| 每语言表（`invTypes_zh`） | 隔离清楚 | 重复数据多，维护成本高 |

## 6. 验证矩阵

| 场景 | 预期 |
|---|---|
| 新账号登录 EN | 列表 11 项，EN 勾选 |
| 切到 ZH | `SetLanguageID` 成功，session change 更新，本地 `messages.zh.txt` 生效 |
| 重开 ESC 菜单 | ZH 仍勾选 |
| 登录后切 DE 再重登 | 服务端 bulk 为 DE，类型名/地点名变；客户端 UI 文案仍按构建语言 |
| 缺翻译的 key | 回落英文，不报错 |
| 非法 languageID | 拒绝或保持原值，不写库 |
| 客户端缓存 | 不同语言 checksum 不同，重登能重取 |
| 教程/幻灯片 | 切换后新打开的内容使用新语言；已打开的窗口保持旧内容 |

命令：

```powershell
cargo build -p eve-server
cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000 --script <断言脚本>
docker compose exec -T postgres psql -U rmr -d rmr -c "select \"languageID\" from account where \"accountID\"=1;"
docker compose logs server --tail 100
```

## 7. 风险与约束

- 客户端本地消息覆盖服务端 `eveMessages`：UI 消息必须走本地文件，不要在服务端翻译 `eveMessages` 后
  期待生效。
- bulk 按语言构建会成倍增加内存/启动时间：用懒构建 + 缓存，先只做 EN/ZH 两种语言验证。
- 客户端 bulk 缓存按 checksum/版本失效；语言内容不同必须产生不同 checksum，否则重登不会重取。
- `compiled.code` 文案编译期写死：UI 语言只能按构建切换，或大改消息化。
- `SetLanguageID` 是 session 变更，必须走 conn 层；`Ctx.session` 是只读的，服务 handler 改不了。
- `translatedLanguageName` 官方转储乱码：开放列表前必须修数据或改客户端回退。
- 官方 `db/*.sql.gz` 保持不动；翻译数据单独放 `config/localization/`，并在文档标为非零售补齐。
- 客户端 `SetLanguage` 通过 `uthread.new` 异步执行，UI 不等待；session change 可能稍晚到达，属正常。

## 8. 关联

- 客户端：`ui/shared/systemmenu.py`、`parklife/gameui.py`、`external/common/script/sys/cfg.py`、
  `external/common/script/sys/sessions.py`、`external/common/script/sys/mlsUtil.py`、
  `ui/services/tutorialsvc.py`、`ui/services/slides.py`、`ui/services/fontsvc.py`
- 服务端：`crates/eve-server/src/svc/language.rs`、`svc/login.rs`、`svc/tutorial.rs`、
  `conn/auth.rs`、`conn/mod.rs`、`session.rs`、`bulkdata.rs`、`svc/rows.rs`
- 数据：`db/languages.sql.gz`、`db/account.sql.gz`、`db/eveMessages.sql.gz`
- 文档：`doc/client-localization-3913.md`（单语言汉化流水线）、
  `doc/issues/rmr-issue-language-list-empty.md`（列表为空现象）、`doc/client/client-code-baseline.md`
