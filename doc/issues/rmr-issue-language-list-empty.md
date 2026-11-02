# 客户端 ESC 菜单 Language 标签列表为空

**当前状态**：已修复（多语言阶段 1 完成）。`GetLanguages` 现在读 `languages` 表并返回 `util.Rowset`；`SetLanguageID` 会同步 session、`account."languageID"` 并下发 session change。服务端静态数据已按语言提供 EN/ZH 两套 bulk（ZH 为 `config/localization/server_zh.json` 覆盖层），教程/幻灯片与客户端 UI 文案仍待后续阶段。整体机制与分层方案见 `doc/client/multilanguage-3913.md`。

## 1. 症状

游戏内按 ESC 打开系统菜单，切到 `Language` 标签：两个栏目标题都在（左列 `Language`、右列 `Input Method Editor`），但左列没有任何语言复选框——列表是空的。

- 客户端不弹错误框，只在服务端日志里留下一条客户端回传的堆栈（见第 3 节）。
- 影响面：仅 UI，不影响登录、玩法与数据；`prefs.languageID` 仍是上次会话的值。

## 2. 根因

客户端的语言列表不是本地写死的，登录后要经 RPC 取：

- 入口 `ui/shared/systemmenu.py:577`（`SystemMenu.Language`），`langs = eve.LocalSvc('gameui').GetLanguages()`（`systemmenu.py:588`）。
- `parklife/gameui.py` 的 `GameUI.GetLanguages` 实际字节码是：

  ```python
  if eve.session.userid:
      if not self.languages:
          self.languages = []
          for row in eve.RemoteSvc('languageSvc').GetLanguages():
              self.languages.append([row.languageID, row.languageName, row.translatedLanguageName])
      return self.languages
  else:
      return [['EN','English','English'], ...]   # 未登录时硬编码 10 种
  ```

  注意：反编译基线 `EVE-Online-3913-code/tree/parklife/gameui.py:477` 丢掉了 `if not self.languages: ... RemoteSvc(...)` 这一段（pycdc 反编译残缺），**这处只能以字节码为准**（`tools/client-code/scan.py dis "gameui.py/GameUI/GetLanguages"`）。

- 服务端 `crates/eve-server/src/svc/language.rs:12` 把 `GetLanguages` 返回成
  `Value::List([Value::List(["EN","English","English"])])`，客户端拿到的是普通 list；
  `row.languageID` 触发 `AttributeError`，异常从 `Language()` 抛出，前面画好的标题保留，于是表现为“标签在、列表空”。
- 客户端预期的是 `util.Rowset`（行对象按 header 提供属性访问），即 `crates/eve-server/src/svc/rows.rs` 的 `rowset(header, lines)`。

## 3. 证据步骤

1. `docker compose logs server --tail 3000 | Select-String "GetLanguages" -Context 25,25`：

   ```
   svc=languageSvc method=GetLanguages: ok took=52.322µs
   ...
   File ".../ui/shared/systemmenu.py", line 647, in Language
   File ".../parklife/gameui.py", line 538, in GetLanguages
   AttributeError: 'list' object has no attribute 'languageID'
       row : ['EN', 'English', 'English']
   ```

   说明 RPC 成功、数据形状不对，是 `svc/language.rs` 的返回结构问题，不是网络或鉴权。
2. `docker compose exec -T postgres psql -U rmr -d rmr -c "select * from languages;"` → 11 行（EN/DE/FR/ES/IS/IT/PT/RU/JA/KO/ZH），正是客户端 `row.languageID/languageName/translatedLanguageName` 三列对应的零售表。
3. `python tools/client-code/scan.py dis "gameui.py/GameUI/GetLanguages"` → 确认客户端确实走 `eve.RemoteSvc('languageSvc').GetLanguages()` 且按行属性取值。

## 4. 修复（已执行）

1. `crates/eve-server/src/svc/language.rs`：`GetLanguages` 读官方 `languages` 表并返回 rowset：

   ```rust
   let sql = r#"SELECT "languageID","languageName","translatedLanguageName"
                  FROM "languages" ORDER BY "languageID""#;
   ctx.rowset(&["languageID", "languageName", "translatedLanguageName"], sql, &[]).await
   ```

2. `crates/eve-server/src/conn/language.rs`：新增 `Conn::set_language`，接管
   `authentication.SetLanguageID`（`conn/mod.rs` 在 service dispatch 之前特判，因为要改 session）：
   校验 `languages` 表 → 更新 `Session.language_id` → 写 `account."languageID"` →
   `send_session_change_from` 下发 `languageID` 变更。未知语言保持原值、只回 `None`。
3. 登录（`conn/auth.rs`）：以 `clientinfo.languageID`（客户端 prefs）为准，缺失时取
   `account."languageID"`，再缺失才 `EN`；有变化时写回账户。`account` 查询新增
   `languageID` 列（`crates/eve-server/src/db.rs`）。
4. 语言名修复（`crates/eve-server/src/db.rs:repair_language_names`）：官方转储里
   IS/JA/KO/RU/ZH 的 `translatedLanguageName` 是双重编码乱码。启动时按语言 ID 幂等修复为
   `Íslenska` / `日本語` / `한국어` / `Русский` / `中文`；`db/*.sql.gz` 不动。
5. 客户端要显示本地名时用 `translatedLanguageName or languageName`，因此修复后 11 项都有可读标签。

零售依据：`db/languages.sql.gz` 的 11 行、客户端 `GameUI.GetLanguages` 按
`row.languageID/languageName/translatedLanguageName` 取值的字节码。语言清单没有自造项。

生效方式：改服务端代码 → 重建镜像并重启容器（`docker compose up -d --build server`）；客户端无需改。
重启前先确认 `exefile` 未运行。

## 5. 多语言能力现状（回答“客户端支持多语言吗”）

阶段 1 已闭环：列表能显示 11 种语言、能勾选、session 与 `account."languageID"` 一致。
阶段 3 的静态数据部分也已完成 EN/ZH：服务端启动时构建两套 bulk，登录时按
`clientinfo.languageID` 选一套；缺翻译的单元格回落英文。其余层仍是计划：

- 运行期切换只改 session 与本地消息文件；服务端 bulk 不重拉，**要重登才看到新语言的物品/地名**。
- 教程（`tutorialSvc.GetTutorials/GetTutorialInfo`）、幻灯片
  （`languageSvc.GetTextsForGroup`）仍未按 `languageID` 查库。
- `mlsUtil.Mls.LoadLanguagePack` → `languageSvc.GetMessagesByLanguageID` 在 3913 客户端没有调用点；
  `mls` 只作为 `cfg.evemessages` 的懒加载访问器。
- 零售 3913 没有“同一 ID 的多语言版本”：`db/` 里只有 `languages` 和 `account` 带 `languageID`；
  名称层翻译是本项目用现代本地化表按 3913 英文原文对齐后补的（非零售数据）。
- 客户端 `compiled.code` 仍是单语言构建（当前是中文包）；运行期改 UI 文案不在本阶段范围。
- 本项目看到的中文界面来自 `compiled.code` 的字符串本地化（`tools/localization/`），
  与服务端数据语言是两套机制。

完整的分层方案、数据模型和实施阶段见 `doc/client/multilanguage-3913.md`。

## 6. 验证

已跑通的验证（2026-11-02，本地调试实例 `127.0.0.1:26001`，DB 为现网卷）：

1. `cargo build -p eve-server`、`cargo test -p eve-server`（含 `bulkdata` 与 `i18n` 用例）通过。
2. `fakeclient 127.0.0.1:26001 loctest loctest --no-cache --script <script>`：
   `languageSvc.GetLanguages -> util.Rowset{lines} x11`；`authentication.SetLanguageID "ZH"`
   收到 `SessionChangeNotification`（`languageID "EN" -> "ZH"`）；再发 `"XX"` 无 session change。
   脚本结果 `4 call(s), 4 ok, 0 failed`。
3. `psql` 查 `account`：该账户 `languageID = ZH`；`languages` 11 行，五个乱码名已修复
   （`convert_to(...)` 十六进制可验证 `中文`/`日本語`/`한국어`/`Русский`/`Íslenska`）。
4. `fakeclient ... --lang ZH`：登录 session change 为 `languageID None -> "ZH"`，
   `cached objects: 38/38 decoded`。
5. 服务端 debug 日志：`bulk data ZH: 38 objects, 246911 rows`，且
   `config.BulkData.types` 应用了 15053 条翻译、`config.StaticLocations` 2184 条。
6. 客户端实机验证仍待做（需完全重启客户端后在 ESC → Language 里勾选并重登看名称）。

已修复后客户端侧应看到：ESC → Language 有 11 个复选框；勾选 ZH 后 `prefs.languageID`
与 session 一致；重登后物品/星系名显示中文，客户端 UI 文案仍由当前 `compiled.code` 决定。

## 7. 回滚 / 预防

- 回滚：`git revert` 对应提交并重建镜像。语言名修复是启动时幂等 UPDATE，回滚代码后数据保留修复值；
  若要完全恢复官方转储原值，只能从 `db/languages.sql.gz` 手动重导该表（不推荐）。
- 预防：凡是客户端用 `for row in ...: row.field` 消费的返回值，必须用 `rowset()`（`svc/rows.rs`），不能直接塞 `Value::List`；服务端日志里出现 `AttributeError: 'list' object has no attribute` 即此模式。

## 8. 关联

- 服务端：`crates/eve-server/src/svc/language.rs`、`svc/rows.rs`、`conn/language.rs`、`conn/auth.rs`、`db.rs`、`bulkdata.rs`、`i18n.rs`
- 客户端：`ui/shared/systemmenu.py`、`parklife/gameui.py`、`external/common/script/sys/cfg.py`、`external/common/script/sys/mlsUtil.py`
- `doc/client/client-code-baseline.md`（反编译基线不可全信，结构以字节码为准）
- `doc/client/multilanguage-3913.md`（多语言机制、数据覆盖层与实施阶段）
- `tools/localization/README.md`、`tools/localization/build_server_map.py`（服务端名称层生成器）

## 9. 搜索关键词

语言列表为空、Language 标签、ESC 语言、GetLanguages、languageSvc、AttributeError: 'list' object has no attribute 'languageID'、MlsNotifyCaveats、messages.zh.txt、多语言
