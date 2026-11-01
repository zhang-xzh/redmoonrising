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
# 客户端目录内：设 USERDOMAIN=CENTRAL 才会显示 CCP 内部 "Local Servers" 登录项
M:\EVE-LOCAL\inputs\EVE-Online-3913\Launch-EVE-RMR.bat

# 或一键：起服务端 + 等 26000 + 拉起客户端
M:\EVE-LOCAL\redmoonrising\Start-RMR.bat
```

`Launch-EVE-RMR.bat` 会先探测 `127.0.0.1:26000`，没监听就提示先起服务端。

## 客户端代码：`script\compiled.code`

自定义容器格式（不是 ZIP、不是普通 pyc）：

```text
Python-2 protocol-1 pickle:
  [ (module_path: str, (marshalled_code: str, aux: int)), ... ]
```

- 373 个模块，按 `script:/eve/...` 一类路径索引；每个 blob 是 Python 2.4 方言的 marshal code object（interned string `t`、string ref `R` 等）。
- 当前大小 7,926,678 字节（2026-11-01 写入）；`compiled.code.vanilla` 7,930,596 字节（零售原样）。两者有 **143/373 个模块不同**——即当前工作包已经带本地化等改动。
- 读写的权威实现：`tools/localization/eveccp.py`（round-trip 字节级保真，可改字符串常量）；它同时是“格式即文档”的来源。

### 工具链（`tools/localization/`，本地未跟踪）

| 脚本 | 作用 |
|---|---|
| `eveccp.py` | 容器 unpickle/pickle、marshal 读写；库 |
| `dis24.py` | Python 2.4 字节码反汇编（判断常量是显示文本还是结构数据） |
| `localize_code.py` | 按映射表把显示字符串改成中文 `unicode`；跳过类名、字典键、import 名、比较常量、单 token 标识符 |
| `repack.py` | 解包 → 重打包（不改内容时用于验证字节保真） |
| `check_patch.py` | 检查补丁里的 unicode 常量与映射命中 |
| `verify.py` / `probe*.py` / `scan.py` / `stats.py` / `analyze.py` / `build_map.py` / `module_strings.py` / `findstr.py` / `opcode24.py` / `auxcheck.py` | 映射构建、扫描、统计与校验的辅助脚本 |
| `config/localization/ui_en_zh.json` | 英文 → 中文显示文本映射（`build_map.py` 生成） |
| `exclude.json`（若存在） | 精确排除的危险字符串 |

运行解释器：`C:\Users\zhang\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe`（`python` 不在 PATH）。

### 改写流程

1. 备份当前包：`Copy-Item script\compiled.code script\compiled.code.bak`。
2. 以 `.vanilla` 为基线生成补丁包（不要叠加在上一次产物上）。
3. 用 `localize_code.py` 等脚本生成，`check_patch.py`/`verify.py` 校验。
4. 覆盖 `script\compiled.code`，**完全退出并重启客户端**（`.pyc` 只在进程启动时载入）。
5. 进客户端看实际界面；证据看 `capture\Gamelogs`。
6. 记录到 `doc/client/`，写清改了什么、脚本、映射条目。

### 硬约束

- `compiled.code.vanilla` 永不修改；`bin\exefile.exe`、`bin\*.dll`、`res\*.stuff` 不改。
- 只改**显示文本**，不改结构数据（类名、字典键、import、比较常量、单 token 标识符）；`localize_code.py` 的跳过规则即为此，`exclude.json` 兜底。
- 改动必须由脚本可复现；没有版本控制前不要原地手改。
- 缺口：3913 还没有独立客户端代码仓库；`tools/` 被 `.gitignore` 忽略。大改前先把代码与工具纳入版本控制（分支策略同服务端仓库）。
