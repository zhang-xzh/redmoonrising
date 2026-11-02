# 3913 客户端代码基线仓库

零售 3913 客户端 Python 代码的独立版本管理基线：`M:\EVE-LOCAL\inputs\EVE-Online-3913-code`
（自己的 git 仓库，不属于 RMR workspace）。用途是给客户端代码一个可 diff、可回溯、
可重建容器的工作副本，替代此前只有 `tools/client-code/` + `tools/localization/` 脚本的状态。

## 来源与权威性

| 项 | 值 |
|---|---|
| 来源 | `M:\EVE-LOCAL\_archive\backup\EVE-Online-3913`（零售原样安装，`boot.ini` = 2.10 / 3913 / Blood） |
| 代码容器 | `script\compiled.code`，7,930,596 字节，373 个模块 |
| md5 | `36e18ef3105d956c200b2e811525efb8`，与现役客户端 `script\compiled.code.vanilla` 完全一致 |
| 基线仓库首个提交 | `e890771 Import EVE 3913 client code baseline` |

现役客户端 `script\compiled.code`（md5 `251dfdef…`）是本地化后的包，与 `.vanilla` 有 143 个模块不同；
基线一律以零售包为准，不从工作包复制。

## 远程与分支策略

仓库有独立远程 `gogs` = `http://10.10.10.1:3001/zhangxzh/EVE-Online-3913-code.git`
（Gogs 私有仓库，凭据由 Windows 凭据管理器提供），分支策略与 `EveJS` 一致：

| 分支 | 角色 |
|---|---|
| `main` | 零售基线，只含 `e890771 Import EVE 3913 client code baseline`；只作对照与重置，不开发、不合入任务分支 |
| `plus` | 开发主分支，本地默认检出，所有任务分支的合入目标 |
| `<前缀>/<功能>-<sessionid>` | 单任务分支，前缀 `feat/`、`fix/`、`doc/`、`chore/`，`<sessionid>` 取对话 id；合入后保留 |
| `archive/…` | 归档分支，只读保留 |

开工从最新 `gogs/plus` 建任务分支（任务体量大或并行时用独立 `git worktree`），完成后
`git merge --no-ff` 回 `plus`，再 `git push gogs plus` 与分支本身；`main` 只推基线。
仓库内 `AGENTS.md` 是这套流程的强制版本，`README.md` 的「远程与分支」小节是操作摘要。

## 目录结构

参照新版客户端仓库 `M:\EVE-LOCAL\inputs\EVE-3396210-code.ccp`（`dist/` + `tree/` + `tools/`）：

| 路径 | 内容 |
|---|---|
| `dist/compiled.code` | 零售容器原件，重建与比对的唯一字节来源 |
| `dist/manifest.json` | 373 条：原始模块路径、`tree` 相对路径、`aux`、大小、sha256、反编译工具 |
| `tree/<模块>.pyc` | 逐模块精确载荷：Python 2.4 pyc 头（magic `6df20d0a` = 62061，mtime 归零）+ marshal |
| `tree/<模块>.py` | 反编译源码，仅供阅读/diff（372 个模块） |
| `tree/_decompile_failures.txt` | 反编译不完美的模块：`<文件>\t<状态>\t<工具>` |
| `tree/…/sessions.py.dis` | 两个反编译器都失败的模块改用 pycdas 反汇编 |
| `lib/*.py` | 客户端 `lib\*.py` 原文 11 个（`importutil`、`nasty`、`log`、`socket`、`bluepy` 等） |
| `stdlib/**` | 客户端 `stdlib\**` 原文 502 个（Python 2.4 标准库 + PIL/Crypto/ZSI/ClientCookie/xml） |
| `script/run.py`、`script/sys/autoexec.py` | 启动脚本原文 |
| `tools/extract_compiled_code.py` | 容器 → `tree/` + manifest |
| `tools/build_compiled_code.py` | `tree/` → 容器，并核对能否还原 |

路径映射只做两件事：`script:/` 前缀去掉；`script:/../../common/script/…`（54 个共用模块）
落成 `external/common/script/…`（避免 `..` 出现在仓库里）。反向还原不靠猜路径，一律按
`dist/manifest.json` 的 `module`↔`tree` 对应关系。

## 反编译现状

容器里只有 Python 2.4 marshal 字节码，`.py` 是生成物，因此**权威产物是 `tree/*.pyc` 与
`dist/compiled.code`**，源码只用于阅读。373 个模块的当前结果：

- 368 个由 Decompyle++（`pycdc`）产出：其中 339 个无警告，29 个带 `Warning: Stack history…`
  等告警（个别片段可能缺失或走样，清单见 `tree/_decompile_failures.txt`）；
- 4 个 pycdc 失败/不可信，回退 `uncompyle6`；
- 1 个（`external/common/script/sys/sessions.py`，pycdc 报 circular reference）两个反编译器都失败，
  只留 `.py.dis` 反汇编。

`uncompyle6` 单独跑只有 254/373 成功，所以以 pycdc 为主。工具版本：pycdc（`zrax/pycdc` 源码
`cmake -G Ninja` 构建，magic 表含 2.4/62061）、`uncompyle6 3.9.3`（Python 3.11 下运行）。

## 操作

```powershell
cd M:\EVE-LOCAL\inputs\EVE-Online-3913-code

# 重新导出 tree/ 与 manifest（需要 pycdc 可执行文件；不传则退回 uncompyle6）
python tools/extract_compiled_code.py --pycdc <path>\pycdc.exe

# 只导出 .pyc，不反编译
python tools/extract_compiled_code.py --no-decompile

# 校验 tree/ 能否完整还原 373 个模块（三元组比对）
python tools/build_compiled_code.py

# 生成新容器
python tools/build_compiled_code.py --out dist/compiled.code.rebuilt
```

`build_compiled_code.py` 用 manifest 里的 sha256 校验每个 `.pyc` 载荷，再按原顺序比对
`(module, marshal, aux)` 三元组与 `dist/compiled.code`；一致即证明 `tree/` 完整。重建出的
pickle 与零售原件**字节不同**（不复刻原件的 pickle memo 编码），语义一致；要逐字节原件就
用 `dist/compiled.code`。

改代码的完整链路：改 `tree` → `build_compiled_code.py --out …` → 覆盖客户端
`script\compiled.code`（先备份）→ **完全退出并重启客户端** → 进游戏验证。客户端本地化仍走
`tools/client-code/`（`eveccp.py`）与 `tools/localization/`（`localize_code.py`），本仓库只做基线对照，两者不要互相覆盖。

## 验证记录

- `tools/build_compiled_code.py`：`verified 373 modules against compiled.code`，重建 7,928,628 字节。
- 首次提交后抽查 git blob 与零售文件字节：`stdlib/os.py`、`stdlib/xml/dom/minidom.py`、
  `lib/bluepy.py`、`script/run.py`、`script/sys/autoexec.py`、`dist/compiled.code` 全部 `MATCH`。
- 仓库 `.gitattributes` 用 `* -text` 关掉 EOL 归一化，保证提交内容与零售字节一致
  （否则 `stdlib/**` 的 CRLF 会被改成 LF）。

## 边界与回滚

- 只含代码，不含 `bin\*.dll`、`exefile.exe`、`res*.stuff`、`res\**`、`script\ui\css\*`、
  `script\sys\strings.txt` 等资源与数据。
- 底座固定 build 3913，不得与 3396210 混用；新版客户端的 `code.ccp` 结构只作参照。
- 回滚：直接删掉 `M:\EVE-LOCAL\inputs\EVE-Online-3913-code` 即可，不影响客户端目录、
  `compiled.code.vanilla` 与 RMR 仓库；需要重建时按本文「操作」从 `_archive\backup` 的零售包重跑。
