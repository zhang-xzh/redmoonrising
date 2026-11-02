# 3913 客户端 4K / 200% UI 缩放
> 客户端工具、补丁与本地化流水线已迁至独立仓库 `M:\EVE-LOCAL\inputs\EVE-Online-3913-code`；
> 本文中的 `tools/...`、`config/localization/...` 均相对该仓库根目录。

## 结论（当前状态）

3913 **自带 UI 全局缩放开关**：`triui.UILib.desktopScale`。把虚拟桌面设成窗口的一半即可
得到 200% UI：

```python
eve.triapp.uilib.desktopScale = 0.5   # 200%
eve.triapp.uilib.desktopScale = 1.0   # 原始
```

- 720×460 窗口实测：`desktopScale 1.0 → 0.5` 时 `desktop 720×460 → 360×230`，UI 2×。
- 当前行为：**登录页 100%，角色选择 / 空间站 / 空间 200%**。
- 设备/窗口在登录后按角色分辨率重建，`desktopScale` 会重置；需要在每次重建后重设。
- 登录页 `res:/UI/Login/splashunderlay.blue` 是固定尺寸布局，2× 会裁切右侧按钮，因此
  登录页保持 `1.0`，只在角色选择/进站/进空间时设 `0.5`。

## 机制

- `trinity.dll` 的 `triui.UILib` 有浮点属性 `desktopScale`（成员偏移 `0x398`，默认
  `1.0f`，文档字符串 “Scales virtual desktop area”，字符串 `0x102c2564`）。
- 实测 `desktopScale` 是**乘数**：`desktop.width/height = 窗口尺寸 × desktopScale`。
  所以 `0.5` 得到一半虚拟桌面 = 2× UI；`2.0` 会让 UI 变小。
- 这是 3913 零售代码里唯一现成的全局 UI 缩放机制；不是现代 carbonui 的
  `dpiScaling`，但语义足够做 200%。
- 现代客户端（TQ / 晨曦 / 曙光 / 3396210）用的是
  `carbonui/primitives/desktop.py` 的 `dpiScaling` + `UpdateUIScaling`，与 3913 无关。

## 实现

脚本：`tools/client-ui-scale/my_autoexec.py` → 客户端 `script\my_autoexec.py`。

`script/sys/autoexec.py` 在 `script/run.py` 之前执行 `script:/my_autoexec.py`，所以不需要
改 `compiled.code`、`bin\*.dll` 或 `res*.stuff`。

脚本在真正的 `gameui` 服务实例（`__builtin__.sm.services['gameui']`）的类上包一层：

| 方法 | 缩放 | 时机 |
|---|---|---|
| `LoadLayers` | `1.0` | 登录页加载后 |
| `GoLogin` | `1.0` | 回登录页 |
| `GoCharacterSelection` | `0.5` | 角色选择前后 |
| `GoStation` | `0.5` | 进站前后 |
| `GoInflight` | `0.5` | 进空间前后 |
| `OnSessionChanged` | `0.5` / `1.0` | 按 `session.stationid`/`solarsystemid` 判断 |

调试日志在 `cache:/ui_scale_<pid>_<seq>.txt`。

## 验证

- 登录页：`LoadLayers:post` 设 `1.0`，`desktop=720x460`，完整不裁切。
- 角色选择：2560×1440 下 `GoCharacterSelection:pre` 设 `0.5`，`desktop=1280x720`，UI 2×。
- 空间站 / 空间：`GoStation` / `GoInflight` 设 `0.5`，UI 2×。
- 日志确认设备/窗口重建后 `desktopScale` 被重新设置。

## 登录页处理

登录页使用 `res:/UI/Login/splashunderlay.blue`（固定尺寸的 `mainarea/toparea/bottomarea`），
2× 后内部按钮仍按原像素排，右侧超出窗口被裁。当前做法是**登录页保持 `desktopScale=1.0`**，
只在角色选择、进站、进空间时设 `0.5`：

- 登录页完整显示，不裁切（100%）。
- 角色选择 / 空间站 / 空间 200%。

如果以后要把登录页也做成 200%，需要缩放 `splashunderlay` 及其子布局（改 `.blue` 资源或
登录页代码），不是 `desktopScale` 一行能解决的。

## 鼠标精度 / DPI 感知

这台机器是 4K 面板 + Windows 150% 缩放（`AppliedDPI=144`，逻辑桌面 2560×1440，
物理 3840×2160）。3913 的 `exefile.exe` 没有 DPI manifest，默认是 **DPI-unaware**，
Windows 会把 2560×1440 的窗口和鼠标坐标整体虚拟化 1.5×。再叠加 `desktopScale=0.5`
的 2×，游戏内鼠标实际按 **3 个物理像素/步** 走，所以明显比桌面（1 物理像素）粗糙，
画面也被 Windows 二次拉伸。

修复（注册表，可逆，不改客户端文件）：

```
HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers
    M:\EVE-LOCAL\inputs\EVE-Online-3913\bin\exefile.exe = "~ HIGHDPIAWARE"
```

设置后实测进程 `GetProcessDpiAwareness = 2`（per-monitor aware），窗口按物理像素创建，
Windows 不再做 1.5× 拉伸。之后在游戏内把 **WINDOW SIZE 设为 3840×2160**（或 fullscreen），
`desktopScale=0.5` 就是真正的 4K 200%，鼠标量化降到 2 物理像素/步。

剩余的 2 像素/步来自 200% UI 缩放本身：`triui` 的硬件光标位置仍在虚拟桌面坐标上。
已用 `tools/client-cursor-fix/` 的 `d3d9.dll` 代理修正：hook
`IDirect3DDevice9::SetCursorPosition`，用 `GetCursorPos` + `ScreenToClient` 的真实客户区
坐标设置硬件光标（UI 命中测试仍用虚拟坐标）。实机日志：

```
SetCursorPosition game=(2249,1195) raw=(689,377) flags=0x00000000
```

用户确认鼠标手感恢复正常。安装：`bin\d3d9.dll` + `bin\cursor_fix.ini`，完全重启客户端；
回滚：删除这两个文件并删除上面的 DPI 注册表值。

回滚：删除上面的 registry 值。

## 启动时 DirectX 版本提示

Windows 10/11 的 `d3d9.dll` 是 10.0.x；3913 的 `script/sys/autoexec.py` 里
`GetDXVersion()` 只认 4.x/5.x，10.x 会落到 `(9, 0, "")`，于是 `CheckDXVersion()` 弹出：

```
DirectX 9.0 detected but this application needs 9.0b
Try continue with old DirectX version?
```

修复：版本判断改为 `d3d9 >= Long(4, 9, 0, 904)` → 9.0c，
`d3d9 >= Long(4, 9, 0, 902)` → 9.0b，不再限定主版本号。补丁与说明见
`tools/client-dx-version-fix/`；安装后完全重启客户端，回滚用
`script/sys/autoexec.py.bak-rmr`。

## 回滚

删除客户端 `script\my_autoexec.py`，并删除 `cache\ui_scale_*.txt`。没有改
`compiled.code` / `bin\*.dll` / `res*.stuff`。
