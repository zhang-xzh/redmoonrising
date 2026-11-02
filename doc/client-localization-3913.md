# build 3913 客户端汉化（Red Moon Rising）

把 `M:\EVE-LOCAL\inputs\EVE-Online-3913`（build 3913，2006 年 retail 客户端）的界面
文本换成中文。译名取自 3396210 客户端的本地化表。客户端代码工具在 `tools/client-code/`，
本地化流水线在 `tools/localization/`，生成物在 `tools/localization/artifacts/`。

## 客户端结构

* Python **2.3.3 / Stackless 3.0**（`sys.version` 实测 `2.3.3 Stackless 3.0 051219`），
  解释器内嵌在 `bin/blue.dll`，引擎是 `bin/trinity.dll`。
* `script/compiled.code` 是 `[(模块路径, (marshal 字节, aux)), ...]` 的 protocol-1
  pickle，373 个模块；`script/sys/autoexec.py`、`script/run.py` 等少数文件直接从磁盘
  读取（`script:/` 根），其余都在 `compiled.code` 里。
* 文本分三层：
  * 硬编码 UI 文案 → `compiled.code` 的字符串常量；
  * 登录/连接期静态消息 → `res/common/messages.txt` + `res/common/messages.<lang>.txt`；
  * 物品/技能/星系等名称 → 服务端 bulk；服务端用 `config/localization/server_zh.json`
    覆盖层（由 `tools/localization/build_server_map.py` 生成）提供中文，见
    `doc/client/multilanguage-3913.md`。

## 做法

1. `tools/localization/localize_code.py` 把命中的英文常量改写成 Python `unicode`
   （marshal `u`），输出 `compiled.code.zh`。
2. 客户端 `cache/prefs.ini` 两行（**缺一不可**）：
   ```ini
   languageID=ZH
   defaultEncoding=utf-8
   ```
3. `tools/localization/make_messages_zh.py` 生成 UTF-16LE 的
   `res/common/messages.zh.txt`，覆盖登录界面静态文案（retail 原文件只有 1 条 caveat，
   走的是客户端自带的语言覆盖机制：`cfg.py/__LoadStaticData` 先读 `messages.txt`，
   再按 `prefs.languageID.lower()` 读 `messages.<lang>.txt`）。

## 依据（为什么是 unicode + utf-8）

* 字体：`script:/ui/services/fontsvc.py` 的 `Fonts/GetFallbackFonts` 在
  `prefs.languageID == 'ZH'` 时从 `C:\WINDOWS\Fonts` 选 `simsun.ttc / simkai.ttf /
  simhei.ttf`，按 `FT_ENCODING_UNICODE` charmap 与字形数排序；`cache/Settings/pc.dat`
  的 `fontCache` 已经记录这三款字体。
* 渲染按码点取字形：`CMMeasurer/AddChar` 是 `LookupFB(ord(char), params)`，
  `CMRenderer/AddChar`、`CMGlyphString/Append` 同样逐字符 `ord`。UTF-8 字节串会被
  按字节拆开，必须用 `unicode`。实测 `Fonts.GetTextWidth`（fontsize 12）：
  `u"离开空间站"` = 83，同串 UTF-8 字节 = 96，`"Undock"` = 32。
* 默认编码必须是 `utf-8`：`lib/inifile.py:368` 用
  `sys.setdefaultencoding(prefs.GetValue("defaultEncoding", "cp1252", True))`。
  英文客户端不是 unicode-clean 的，例如 `ui/util/uix.py:1076 MakeBtnGroup` 对按钮名做
  `str()`；默认 cp1252 时中文 unicode 抛
  `UnicodeEncodeError: 'charmap' codec can't encode characters`，改 utf-8 后正常。
* 换成 unicode 常量后仍会崩的三类用法（`localize_code.py` 已过滤）：
  * 类名常量（`BUILD_CLASS`）：py2.3 报 `argument 1 must be string, not unicode`；
  * 字典/下标键与 guid 前缀（如 `exports['state.'+flag]`）：`ValueError: unpack list
    of wrong size`（`nasty.RegisterNamedObject` 按 `.` 切分）；
  * 单 token 标识符（`Channel`、`Event`、`NULL`）：同时是类名/键名。

## 排查过程（2026-11-01）

1. 从会话记录里恢复了上一轮丢弃的 `eveccp.py` / `dis24.py` / `build_map.py` 等脚本。
2. 全量改写后客户端在 `nasty` 导入阶段退出，但 `logs/#errors` 只有一行
   "exception #1"（详情走 logserver，本机没跑起来）。
3. 用客户端自带的启动钩子 `script:/my_autoexec.py`（`autoexec.py` 注释里写明的
   "local crap you want to do on startup"）注入异常镜像，拿到真实 traceback；
   期间确认了：客户端是 py2.3.3、`eve` 不能重复 `import`（会污染模块）、
   `uix.GetText` 在登录阶段不被调用（登录 UI 由 C++ xtriui 绘制）。
4. 修掉类名/键名两类崩溃后，`StartupUI` 正常返回、`l_login` 打开、无异常。
5. 登录界面实测（正常显示环境）中文全部正确，含带参数的
   `UI_LOGIN_UNABLETOCONNECTTO`。

## 现状

* `tools/localization/artifacts/compiled.code.zh`：改写 **1353 条**不同字符串
  （143 个 code object），客户端启动零异常、`StartupUI` 返回、`l_login` 打开。
* `artifacts/messages.zh.txt`：登录/选人界面静态文案约 50 条。
* 登录界面已实测中文（用户名/密码/服务器/连接/版本/客服支持/新闻/补丁信息/
  用户协议/账号管理/播放介绍影片、连接失败提示）。
* **未验收**：`compiled.code` 里的 1353 条（按钮、菜单、窗口标题、工具提示）需要
  进游戏逐界面确认；开发机显示环境（DirectX 9.0 判定低于 9.0b、主窗口只有
  480x307）只能抓到 splash，看不到游戏内 UI。
* 名称层已接入服务端 bulk（EN/ZH 两套，`config/localization/server_zh.json`）；动态 RPC
  （市场/查询/代理人等直接查库的名称）与教程/幻灯片仍未翻译。

## 安装 / 回滚

```bash
# 安装
cp tools/localization/artifacts/compiled.code.zh "<client>/script/compiled.code"
cp tools/localization/artifacts/messages.zh.txt  "<client>/res/common/messages.zh.txt"
# prefs.ini 加两行：languageID=ZH / defaultEncoding=utf-8
```

客户端要完全重启（`.pyj`/`compiled.code` 只在进程启动时载入）。

回滚：`script/compiled.code.vanilla`、`res/common/messages.zh.txt.orig`、
prefs 改回 `languageID=EN` / `defaultEncoding=cp1252`。

## 重新生成

```bash
PY=python  # 3.8+
cd tools/localization

# 1) 3396210 en-us 表（EveJS 仓库的 FsdDump）
python <EveJS>/tools/FsdDump/dump_localization.py \
    --client M:/EVE-LOCAL/inputs/EVE-Online-3396210 --lang en-us --out loc_en.json

# 2) EN→ZH 映射
python build_map.py --en loc_en.json \
    --zh <EveJS>/config/client_localization_fsd_zh.json \
    --client M:/EVE-LOCAL/inputs/EVE-Online-3913/script/compiled.code.vanilla \
    --out ../config/localization/ui_en_zh.json

# 3) 打补丁 + 校验（verify.py 在 tools/client-code/）
python localize_code.py \
    --in  M:/EVE-LOCAL/inputs/EVE-Online-3913/script/compiled.code.vanilla \
    --out artifacts/compiled.code.zh
python ../client-code/verify.py --in M:/EVE-LOCAL/inputs/EVE-Online-3913/script/compiled.code.vanilla

# 4) 静态消息
python make_messages_zh.py --client M:/EVE-LOCAL/inputs/EVE-Online-3913
```

## 已知限制

* 不含空格的单词（按钮/菜单里的单词）没有翻译：这类串在这套代码里同时当
  标识符/键用，实测会崩。以后可以按"使用点"白名单逐个放开。
* HTML/浏览器内容（物品描述、市场页面）来自服务端，需走名称层/服务端本地化。
