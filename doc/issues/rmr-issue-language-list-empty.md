# 客户端 ESC 菜单 Language 标签列表为空

**当前状态**：未修复。根因已定位（服务端返回结构错误），修复方案见第 4 节；本文件只记录现状，代码未改。

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

  注意：反编译基线 `EVE-Online-3913-code/tree/parklife/gameui.py:477` 丢掉了 `if not self.languages: ... RemoteSvc(...)` 这一段（pycdc 反编译残缺），**这处只能以字节码为准**（`tools/localization/scan.py dis "gameui.py/GameUI/GetLanguages"`）。

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
3. `python tools/localization/scan.py dis "gameui.py/GameUI/GetLanguages"` → 确认客户端确实走 `eve.RemoteSvc('languageSvc').GetLanguages()` 且按行属性取值。

## 4. 修复方案（未执行）

把 `languageSvc.GetLanguages` 改成读 `languages` 表并返回 rowset，例如：

```rust
"GetLanguages" => {
    ctx.rowset(
        &["languageID", "languageName", "translatedLanguageName"],
        r#"select "languageID", "languageName", "translatedLanguageName"
             from languages order by "languageID""#,
        &[],
    )
    .await
}
```

要点：

- 复选框标签用的是 `languageName`（German/French/…），不是 `translatedLanguageName`；官方转储里 IS/JA/KO/RU/ZH 的 `translatedLanguageName` 是乱码，不影响列表显示。若要显示本地名，需另行修数据（本任务不做）。
- 零售依据：`db/languages.sql.gz` 的 11 行数据 + 客户端字节码的三列取值方式；不要自造语言清单。
- 生效方式：改 `crates/eve-server` → 重建镜像并重启 `server` 容器；客户端无需改。重启前先确认 `exefile` 未运行。

## 5. 多语言能力现状（回答“客户端支持多语言吗”）

- 框架在：`prefs.languageID`、`res:/common/messages.<lang>.txt`、`cfg.ReloadMessages`（`external/common/script/sys/cfg.py:432-437`）、`fontsvc.py:1026` 对 `ZH` 的字体回退、`authentication.SetLanguageID`。
- 内容不在：`res/common/messages.txt` 是全部英文（20935 字节）；其余 `messages.de/es/fr/it/ja/ko/pt/ru/zh.txt` 只有一条 `MlsNotifyCaveats`（“所选语言并非全部文本可用，缺的用英文”），`messages.is.txt` 也只有 1376 字节。
- `mls` 语言包机制（`mlsUtil.Mls.TR`、`languageSvc.GetMessagesByLanguageID`）在 3913 客户端里**没有任何调用点**，是死代码。
- 结论：零售 3913 只能“切语言开关”，没有翻译文本；本项目看到的中文界面来自 `script/compiled.code` 的字符串本地化（`tools/localization/`），与这套 MLS 机制无关。

## 6. 验证（修复后应做）

1. `cargo build -p eve-server`，重建并重启 `server`。
2. `cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000 --script <断言脚本>` 断言 `languageSvc.GetLanguages` 返回 `util.Rowset` 且 11 行。
3. 完全重启客户端 → ESC → Language，应看到 11 个复选框；服务端日志中 `AttributeError ... languageID` 消失。

## 7. 回滚 / 预防

- 回滚：`git revert` 对应提交并重建镜像。
- 预防：凡是客户端用 `for row in ...: row.field` 消费的返回值，必须用 `rowset()`（`svc/rows.rs`），不能直接塞 `Value::List`；服务端日志里出现 `AttributeError: 'list' object has no attribute` 即此模式。

## 8. 关联

- `crates/eve-server/src/svc/language.rs`、`crates/eve-server/src/svc/rows.rs`
- 客户端：`ui/shared/systemmenu.py`、`parklife/gameui.py`、`external/common/script/sys/cfg.py`、`external/common/script/sys/mlsUtil.py`
- `doc/client/client-code-baseline.md`（反编译基线不可全信，结构以字节码为准）
- `tools/localization/README.md`（中文界面实际来源）

## 9. 搜索关键词

语言列表为空、Language 标签、ESC 语言、GetLanguages、languageSvc、AttributeError: 'list' object has no attribute 'languageID'、MlsNotifyCaveats、messages.zh.txt、多语言
