# EVE 3913 客户端本地化流程

把 2006 年 retail 客户端 `EVE-Online-3913`（build 3913，Python 2.3.3 + Stackless 3.0）
的界面文本换成中文，译名取自 3396210 客户端的本地化表。底层的容器读写、反汇编与校验
工具在 `tools/client-code/`，本目录只放本地化专用的映射、改写与产物。

完整说明（依据、现状、限制）：`doc/client-localization-3913.md`。

## 文件

| 文件 | 用途 |
|---|---|
| `build_map.py` | 3396210 en-us + zh 本地化表 → EN→ZH 映射 `config/localization/ui_en_zh.json` |
| `build_server_map.py` | 同一对本地化表 + 3913 `db/*.sql.gz` 英文原文 → 服务端覆盖层 `config/localization/server_zh.json` |
| `localize_code.py` | 把命中的英文常量改写成 Python `unicode` 字面量（含 `exclude.json` 排除表） |
| `make_messages_zh.py` | 生成 `res/common/messages.zh.txt`（UTF-16LE + BOM + CRLF） |
| `exclude.json` | 已知会破坏运行、需要跳过的字符串（当前为空） |
| `artifacts/compiled.code.zh` | 当前产出的客户端包（1353 处改动，md5 `251dfdefbfa6eda204821afbf3dec74e`） |
| `artifacts/messages.zh.txt` | 当前产出的静态消息文件 |
| `artifacts/prefs.zh.ini` | `prefs.ini` 需追加的设置 |

映射表只有一份：仓库根 `config/localization/ui_en_zh.json`（约 2457 条）。

`artifacts/compiled.code.zh` 直接覆盖客户端 `script/compiled.code`
（原版备份 `compiled.code.vanilla`）；`messages.zh.txt` 覆盖 `res/common/messages.zh.txt`；
`prefs.ini` 加 `languageID=ZH`、`defaultEncoding=utf-8`。客户端需完全重启后生效。

## 常用流程

```bash
PY=python   # 3.8+，或 .venv 或系统 Python 均可

# 1) 从 3396210 客户端导出 en-us 表（EveJS 仓库 tools/FsdDump）
python <EveJS>/tools/FsdDump/dump_localization.py \
    --client M:/EVE-LOCAL/inputs/EVE-Online-3396210 --lang en-us --out loc_en.json

# 2) 生成 EN→ZH 映射（默认写到 config/localization/ui_en_zh.json）
python build_map.py --en loc_en.json \
    --zh <EveJS>/config/client_localization_fsd_zh.json \
    --client M:/EVE-LOCAL/inputs/EVE-Online-3913/script/compiled.code.vanilla

# 3) 改写 + 字节校验（verify.py 在 tools/client-code/）
python localize_code.py \
    --in  M:/EVE-LOCAL/inputs/EVE-Online-3913/script/compiled.code.vanilla \
    --out artifacts/compiled.code.zh
python ../client-code/verify.py --in M:/EVE-LOCAL/inputs/EVE-Online-3913/script/compiled.code.vanilla

# 4) 静态消息
python make_messages_zh.py --client M:/EVE-LOCAL/inputs/EVE-Online-3913
```

## 服务端名称层（`build_server_map.py`）

客户端包只改界面常量；物品、组、星系/空间站等名称来自服务端 bulk，走独立覆盖层：

```bash
python build_server_map.py \
    --en loc_en.json \
    --zh <EveJS>/config/client_localization_fsd_zh.json \
    --db M:/EVE-LOCAL/redmoonrising/db \
    --out M:/EVE-LOCAL/redmoonrising/config/localization/server_zh.json
```

- 输出结构：`表 → 列 → 主键 → 中文`，例如 `{"invTypes":{"typeName":{"587":"裂谷级"}}}`。
- 匹配只用 3913 行的**英文原文**（名称再做大小写/空白归一）；原文改过的行不翻，保持英文，
  不按现代 typeID 猜测。
- 覆盖表清单写在脚本 `TABLES`（类型/组/分类/属性/效果/账单/制造/种族/血统/单位/频道/静态地点等）；
  玩家生成名字不在内。
- 服务端启动时由 `RMR_LOCALIZATION`（默认 `config/localization`）读取所有 `server_<lang>.json`，
  构建对应语言的 bulk；改文件后重启服务端、客户端重登生效。详细机制见
  `doc/client/multilanguage-3913.md`。

## 改写规则（`localize_code.py`）

只改写“显示用”的常量，避开结构用途：

* 参与 `COMPARE_OP` 比较的常量；
* `BUILD_CLASS` 的类名（py2.3 会报 `argument 1 must be string, not unicode`）；
* 用于 `BINARY_SUBSCR` / `STORE_SUBSCR` / `DELETE_SUBSCR` 的键、`IMPORT_NAME` 的模块名；
* `res:/`、`script:`、`::`、`< > { } % \`、`=` 等出现过的串；
* **单 token 单词**（`Cargo`、`ShipMaintenanceBay`、`NULL`、`state.` 之类），
  它们同时是标识符/字典键/guid 前缀。

实测仍会坏的写进 `exclude.json`（按字符串精确匹配）。

## 验证

装入客户端后，`logs/#errors b3913 *.txt` 应为空或只有已知条目；`logs/history.txt` 末尾有
`STARTUP [pid]` 且进程存活即启动通过。再进游戏确认按钮/菜单文本。
