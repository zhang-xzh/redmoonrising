# EVE 3913 客户端汉化工具

把 2006 年 retail 客户端 `EVE-Online-3913`（build 3913，Python 2.3.3 + Stackless 3.0）
的界面文本换成中文。译名来自 3396210 客户端的本地化表。

完整说明（依据、现状、限制）：`doc/client-localization-3913.md`。

## 文件

| 文件 | 作用 |
|---|---|
| `eveccp.py` | 读写 `script/compiled.code`（protocol-1 pickle + Python 2.3 marshal），逐字节 round-trip |
| `dis24.py` / `opcode24.py` | Python 2.3 字节码反汇编（判断常量的用途） |
| `scan.py` | 只读扫描：`list` / `grep PAT [const\|name]` / `tree MODULE` / `dis MODULE/FUNC` |
| `build_map.py` | 3396210 en-us + zh 本地化表 → 常量 EN→ZH 映射 `ui_en_zh.json` |
| `localize_code.py` | 把命中的常量改写成 Python `unicode`（字体链路需要码点） |
| `make_messages_zh.py` | 生成 `res/common/messages.zh.txt`（UTF-16LE + BOM + CRLF） |
| `verify.py` | 逐模块 `loads/dumps` 字节比对 |
| `ui_en_zh.json` | 生成物：英文常量 → 中文（当前 2457 条） |
| `exclude.json` | 已知会崩、需要跳过的字符串（当前为空） |
| `artifacts/compiled.code.zh` | 当前打好的客户端包（1353 条，md5 `251dfdefbfa6eda204821afbf3dec74e`） |
| `artifacts/messages.zh.txt` | 当前打好的静态消息文件 |
| `artifacts/prefs.zh.ini` | `prefs.ini` 必须加的两行 |

`artifacts/compiled.code.zh` 可直接覆盖客户端 `script/compiled.code`
（原版备份 `compiled.code.vanilla`）；`messages.zh.txt` 覆盖 `res/common/messages.zh.txt`；
`prefs.ini` 加 `languageID=ZH`、`defaultEncoding=utf-8`。客户端需完全重启。

## 重新生成

```bash
PY=python   # 3.8+；仓库 .venv 或系统 Python 均可

# 1) 从 3396210 客户端导出 en-us 表（EveJS 仓库 tools/FsdDump）
python <EveJS>/tools/FsdDump/dump_localization.py \
    --client M:/EVE-LOCAL/inputs/EVE-Online-3396210 --lang en-us --out loc_en.json

# 2) 生成 EN→ZH 映射
python build_map.py --en loc_en.json \
    --zh <EveJS>/config/client_localization_fsd_zh.json \
    --client M:/EVE-LOCAL/inputs/EVE-Online-3913/script/compiled.code.vanilla \
    --out ui_en_zh.json

# 3) 打补丁 + 字节校验
python localize_code.py \
    --in  M:/EVE-LOCAL/inputs/EVE-Online-3913/script/compiled.code.vanilla \
    --out artifacts/compiled.code.zh
python verify.py --in M:/EVE-LOCAL/inputs/EVE-Online-3913/script/compiled.code.vanilla

# 4) 静态消息
python make_messages_zh.py --client M:/EVE-LOCAL/inputs/EVE-Online-3913
```

## 过滤器（`localize_code.py`）

只改写"像句子"的常量，且跳过结构性用途：

* 被 `COMPARE_OP` 比较的常量；
* `BUILD_CLASS` 的类名（否则 py2.3 报 `argument 1 must be string, not unicode`）；
* 紧邻 `BINARY_SUBSCR` / `STORE_SUBSCR` / `DELETE_SUBSCR` 的键、`IMPORT_NAME` 的模块名；
* `res:/`、`script:`、含 `::`、`< > { } % \`、`=`、换行的串；
* **不含空格的单词**（`Cargo`、`ShipMaintenanceBay`、`NULL`、`state.` 这类在这套代码里
  经常同时是标识符/字典键/guid 前缀，实测会崩）。

实测仍会出问题的串写进 `exclude.json`（字符串列表，按内容精确匹配）。

## 验证

安装后启动客户端，`logs/#errors b3913 *.txt` 不应新增文件；`logs/history.txt` 出现
`STARTUP [pid]` 且进程存活即算通过；进游戏后逐界面确认按钮/菜单中文。
