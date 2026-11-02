# 3913 客户端

本项目的唯一客户端：EVE Online **2.10 / build 3913 / codename Blood**（2006），目录 `M:\EVE-LOCAL\inputs\EVE-Online-3913`，**固定不升级**。

## 版本与进程

`boot.ini`：

```ini
[main]
version=2.10
build=3913
codename=Blood
role=client
aid=0
show_patch_notes=1
```

- 根目录 `eve.exe` 是启动器；真正跑游戏的是 `bin\exefile.exe`（32 位，DirectX 9）。
- `logserver.exe` 是客户端的本地日志服务。
- 判断“客户端是否在运行”看 `exefile` 进程（`Get-Process exefile`）。

## 目录布局

| 路径 | 内容 |
|---|---|
| `bin\` | `exefile.exe`、`blue.dll`（Stackless Python + 引擎绑定）、`destiny.dll`、`trinity.dll`、`audio.dll`、`NetClient.dll` 等原生模块 |
| `script\` | `compiled.code`（客户端 Python 代码容器）、`compiled.code.vanilla`（零售原样备份）、`run.py` |
| `lib\` | Python 支撑模块，源码与字节码并存：`autoexec.py`、`bluepy`、`ccp_exceptions`、`importutil.py`、`inifile`、`log`、`nasty`、`rdebug.py`、`slprofile`、`socket`、`triPickle.py` |
| `stdlib\` | 标准库与第三方（`ClientCookie`、`Crypto`、`PIL`、`xml`、`_xmlplus`、`ZSI`、`encodings`、`email`）的 `.pyo` |
| `res\` | 资源：`res.stuff`、`resCelestialTextures.stuff` 等（二进制包，只读不改） |
| `cache\` | 运行时缓存 |
| `capture\` | 客户端输出：`Gamelogs`、`Chatlogs`、`Portraits`、`Screenshots` —— **验证客户端行为的证据来源** |
| `logs\` | 客户端日志 |
| `wwwroot\` | 内置浏览器页面 |

## 启动

```powershell
# 一键：起服务端 + 等 26000 + 拉起客户端（脚本在仓库根，客户端目录保持只读）
M:\EVE-LOCAL\redmoonrising\Play.bat

# 只起服务端
M:\EVE-LOCAL\redmoonrising\Play.bat --no-client
```

`Play.bat` 由客户端目录的 `Launch-EVE-RMR.bat` 迁移而来（后者已删除）：先 `docker compose up -d` 并等 `127.0.0.1:26000` 就绪（最多 5 分钟），再设 `USERDOMAIN=CENTRAL`（显示 CCP 内部 "Local Servers" 登录项）并启动 `eve.exe`。客户端目录可用环境变量 `RMR_CLIENT_DIR` 覆盖，默认 `M:\EVE-LOCAL\inputs\EVE-Online-3913`。

## 客户端代码：`script\compiled.code`

自定义容器格式（不是 ZIP、不是普通 pyc）：

```text
Python-2 protocol-1 pickle:
  [ (module_path: str, (marshalled_code: str, aux: int)), ... ]
```

- 373 个模块，按 `script:/eve/...` 一类路径索引；每个 blob 是 marshal code object（interned string `t`、string ref `R` 等）。客户端运行时是 Python **2.3.3 / Stackless 3.0**，`eveccp.py` 按 2.3/2.4 方言读写。
- 当前大小 7,926,678 字节；`compiled.code.vanilla` 7,930,596 字节（零售原样）。两者有 **143/373 个模块不同**——即当前包已带本地化改动。
- 当前客户端 `script\compiled.code` 与 `tools/localization/artifacts/compiled.code.zh` **完全一致**（md5 `251dfdefbfa6eda204821afbf3dec74e`），即仓库里的产物就是客户端在用的包。
- 读写的权威实现：`tools/client-code/eveccp.py`（round-trip 字节级保真，可改字符串常量）；它同时是“格式即文档”的来源。

### 工具链（`tools/client-code/` 代码工具 + `tools/localization/` 本地化，均已纳入版本库）

| 脚本 | 作用 |
|---|---|
| `tools/client-code/eveccp.py` | 容器 unpickle/pickle、marshal 读写；库 |
| `tools/client-code/dis24.py` / `opcode24.py` | Python 2.3/2.4 字节码反汇编（判断常量是显示文本还是结构数据） |
| `tools/client-code/scan.py` | 只读扫描：`list` / `grep PAT [const\|name]` / `tree MODULE` / `dis MODULE/FUNC` |
| `tools/client-code/verify.py` | 逐模块 `loads`/`dumps` 字节比对 |
| `tools/localization/localize_code.py` | 按映射表把显示字符串改成中文 `unicode`；跳过类名、字典键、import 名、比较常量、单 token 标识符 |
| `tools/localization/build_map.py` | 从 3396210 的 en-us + zh 本地化构建 EN→ZH 映射 `config/localization/ui_en_zh.json`（约 2457 条） |
| `tools/localization/make_messages_zh.py` | 生成 `res/common/messages.zh.txt`（UTF-16LE + BOM + CRLF） |
| `tools/localization/build_server_map.py` | 从同一对本地化表 + 3913 `db/` 英文原文生成服务端覆盖层 `config/localization/server_zh.json`（表/列/主键 → 中文） |
| `tools/localization/exclude.json` | 已知会破坏客户端、需精确排除的字符串（当前为空） |
| `tools/localization/artifacts/compiled.code.zh`、`artifacts/messages.zh.txt`、`artifacts/prefs.zh.ini` | 当前构建产物；按 README 覆盖到客户端 |

- 客户端字符串映射只有一份：仓库根 `config/localization/ui_en_zh.json`（`build_map.py` 默认输出、`localize_code.py` 默认读取）；服务端名称层是另一份 `config/localization/server_zh.json`（`build_server_map.py`）。
- 诊断/复现脚本在 `tools/client-code/probes/`（`repack.py`、`check_patch.py`、`stats.py`、`analyze.py`、`probe*.py` 等，已入库）；作参考用，权威流程仍是上表的正式脚本与 README。
- 用法与流程的权威说明：`tools/client-code/README.md`、`tools/localization/README.md`、`doc/client-localization-3913.md`。

运行解释器：`C:\Users\zhang\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe`（`python` 不在 PATH）。

### 改写流程

1. 备份当前包：`Copy-Item script\compiled.code script\compiled.code.bak`。
2. 以 `.vanilla` 为基线生成补丁包（不要叠加在上一次产物上）；产物写进 `tools/localization/artifacts/`。
3. 用 `localize_code.py` 等脚本生成，`verify.py` 校验字节保真，再检查目标模块的字符串。
4. 覆盖 `script\compiled.code`（以及 `res\common\messages.zh.txt`、`prefs.ini` 的 `languageID=ZH`），**完全退出并重启客户端**（字节码只在进程启动时载入）。
5. 进客户端看实际界面；证据看 `capture\Gamelogs`。
6. 记录到 `doc/client/`，写清改了什么、脚本、映射条目、产物 md5。

### 硬约束

- `compiled.code.vanilla` 永不修改；`bin\exefile.exe`、`bin\*.dll`、`res\*.stuff` 不改。
- 只改**显示文本**，不改结构数据（类名、字典键、import、比较常量、单 token 标识符）；`localize_code.py` 的跳过规则即为此，`exclude.json` 兜底。
- 改动必须由脚本可复现；手改 `compiled.code` 视为破坏版本化流程。
- 缺口：`tools/` 仍在 `.gitignore` 里，新增工具文件要 `git add -f`；结构性大改前的逐模块代码版本管理见 `doc/client/client-code-baseline.md`（独立基线仓库 `M:\EVE-LOCAL\inputs\EVE-Online-3913-code`：`dist/compiled.code` + `tree/*.pyc` + `tree/*.py`）。
