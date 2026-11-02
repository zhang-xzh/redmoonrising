---
name: rmr-client-code
description: Use when reading or patching the EVE 3913 client's compiled.code, Python views, strings or Chinese localization. Triggers: compiled.code, eveccp, localize, pyo, 本地化
---

# 3913 客户端代码（compiled.code）

规则见 `AGENTS.md`「客户端代码修改」；背景见 `doc/client/client-3913.md`。

## 事实

- 客户端：`M:\EVE-LOCAL\inputs\EVE-Online-3913`（2.10 / build 3913 / Blood，固定不升级）。
- 代码容器：`script\compiled.code`（约 7.9 MB，373 个模块）。
- 零售基线：`script\compiled.code.vanilla`（**永不修改**；当前工作包与它有 143 个模块不同，说明已带改动）。
- 运行时刻意区分：`eve.exe` 是启动器，游戏进程是 `bin\exefile.exe`。

## 容器格式

```text
Python-2 protocol-1 pickle:
  [ (module_path: str, (marshalled_code: str, aux: int)), ... ]
```

每个 blob 是 Python 2.4 方言 marshal code object（4 字节 header、interned string `t`、string ref `R`）。`tools/client-code/eveccp.py` 是权威读写实现，未改动时 round-trip 字节保真。

## 工具

客户端代码工具在 `tools/client-code/`，本地化流水线在 `tools/localization/`（均已纳入版本库）。

| 脚本 | 用途 |
|---|---|
| `tools/client-code/eveccp.py` | 容器 unpickle/pickle + marshal 读写（库） |
| `tools/client-code/dis24.py` / `opcode24.py` | 2.3/2.4 字节码反汇编，判断常量用途 |
| `tools/client-code/scan.py` | 只读扫描：`list` / `grep` / `tree` / `dis` |
| `tools/client-code/verify.py` | 逐模块字节比对 |
| `tools/localization/localize_code.py` | 按 `config/localization/ui_en_zh.json` 改显示文本 |
| `tools/localization/build_map.py` | 从 3396210 的 en-us + zh 构建 EN→ZH 映射 |
| `tools/localization/make_messages_zh.py` | 生成 `res/common/messages.zh.txt` |
| `tools/localization/artifacts/` | `compiled.code.zh`（md5 251dfdef…）、`messages.zh.txt`、`prefs.zh.ini` |

用法见 `tools/client-code/README.md`、`tools/localization/README.md` 与 `doc/client-localization-3913.md`；`tools/` 仍在 `.gitignore`，新增文件要 `git add -f`。

解释器：`C:\Users\zhang\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe`（`python` 不在 PATH）。

```powershell
$py = 'C:\Users\zhang\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe'
cd M:\EVE-LOCAL\redmoonrising\tools\client-code\probes
& $py repack.py <in> <out>
```

## 改写流程

1. 备份：`Copy-Item ...\script\compiled.code ...\script\compiled.code.bak -Force`。
2. 从 `.vanilla` 生成新包（不要在上一次产物上叠加）。
3. 脚本改写 + `check_patch.py`/`verify.py` 校验。
4. 覆盖 `script\compiled.code`。
5. **完全退出并重启客户端**（字节码只在启动时载入），进游戏看效果；证据看 `capture\Gamelogs`。
6. 记录到 `doc/client/`：脚本、映射条目、改动的模块、验证结果。

## 约束

- 只改**显示文本**：类名、字典键、import 名、比较常量、单 token 标识符一律不改（`localize_code.py` 的跳过规则）。
- 显示文本必须是 `unicode`（C++ label 与 fontsvc 按字符码点渲染；字节串会被拆成 UTF-8 字节）。
- `bin\exefile.exe`、`bin\*.dll`、`res\*.stuff` 一律不改。
- 改动必须由脚本可复现；没有版本控制前不要手改。

## 基线仓库

逐模块代码版本管理在独立仓库 `M:\EVE-LOCAL\inputs\EVE-Online-3913-code`（git，参照新版客户端的 `EVE-3396210-code.ccp` 结构）：

- `dist/compiled.code`（零售容器，md5 `36e18ef3…`）+ `dist/manifest.json`（373 个模块的路径、aux、sha256）；
- `tree/<模块>.pyc`（精确载荷，magic `62061`）+ `tree/<模块>.py`（pycdc 反编译，供阅读）；
- `lib/*.py`、`stdlib/**`、`script/run.py`、`script/sys/autoexec.py` 原文；
- `tools/extract_compiled_code.py`（容器→tree）、`tools/build_compiled_code.py`（tree→容器并校验）。

结构性大改（增删模块、改逻辑）改 `tree` 后用 `build_compiled_code.py` 重建容器，细节与验证见 `doc/client/client-code-baseline.md`。

## 触发关键词

compiled.code, compiled.code.vanilla, eveccp, dis24, tools/client-code, localize_code, repack, check_patch, ui_en_zh.json, marshal, pickle, Stackless Python, .pyo, 客户端代码, 本地化, 中文, 字体, 界面文字
