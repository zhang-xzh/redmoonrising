# EVE 3913 客户端代码工具

处理 2006 年 retail 客户端 `EVE-Online-3913`（build 3913，Python 2.3.3 + Stackless 3.0）
的 `script/compiled.code`：容器格式、字节码反汇编、常量扫描与重打包校验。**与翻译无关**，
本地化流水线见 `tools/localization/`。

## 容器格式

`script/compiled.code` 是 Python protocol-1 pickle，内容为
`[(module_path:str, (marshalled_code:str, aux:int)), ...]`；每个 blob 是 2.3 方言的
marshal code object（4 字节 header 字段、interned string `t`、string ref `R`、字符串常量
为 `str` 而非 `unicode`）。`eveccp.py` 是权威读写实现，未改动时 round-trip 字节保真。

## 文件

| 文件 | 用途 |
|---|---|
| `eveccp.py` | 读写容器与 marshal code object（`unpickle_container` / `pickle_container` / `loads` / `dumps`），可改写字符串常量 |
| `opcode24.py` | Python 2.3 字节码操作码表 |
| `dis24.py` | 反汇编器，输出 `(offset, opname, arg, value)` 行 |
| `scan.py` | 只读扫描：`list` / `grep PAT [const\|name]` / `tree MODULE` / `dis MODULE/FUNC` |
| `verify.py` | 逐模块 `loads`/`dumps` 字节比对，确认重打包无损 |
| `probes/*.py` | 早期诊断/统计脚本（`analyze.py`、`auxcheck.py`、`check_patch.py`、`findstr.py`、`module_strings.py`、`probe*.py`、`repack.py`、`stats.py`），作参考用 |

## 用法

```powershell
$PY = 'C:\Users\zhang\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe'
$CCP = 'M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code'

# 列出模块
& $PY tools\client-code\scan.py list

# 搜常量 / 搜函数名
& $PY tools\client-code\scan.py grep "Cargo" const
& $PY tools\client-code\scan.py grep "GetLanguages" name

# 反汇编某个函数
& $PY tools\client-code\scan.py dis "gameui.py/GameUI/GetLanguages"

# 校验重打包字节保真
& $PY tools\client-code\verify.py --in $CCP
```

脚本默认读 `M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code`，可用参数覆盖。
只读脚本（`scan.py`、`probes/*`）不会写客户端目录；任何写操作前先备份原文件。

## 相关文档

- 客户端布局与本地化流程：`doc/client/client-3913.md`、`doc/client-localization-3913.md`
- 逐模块反编译基线仓库：`doc/client/client-code-baseline.md`
- 本地化流水线：`tools/localization/README.md`
