# 3913 客户端 4K / 200% UI 缩放

## 结论（当前状态）

3913 **自带 UI 全局缩放开关**：`triui.UILib.desktopScale`。把虚拟桌面设成窗口的一半即可
得到 200% UI：

```python
eve.triapp.uilib.desktopScale = 0.5   # 200%
eve.triapp.uilib.desktopScale = 1.0   # 原始
```

- 720×460 窗口实测：`desktopScale 1.0 → 0.5` 时 `desktop 720×460 → 360×230`，登录 UI 2×。
- 2560×1440 下角色选择、空间站 UI 2× 生效。
- 设备/窗口在登录后按角色分辨率重建，`desktopScale` 会重置；需要在每次重建后重设。
- **已知问题**：登录页 `res:/UI/Login/splashunderlay.blue` 是固定尺寸布局，2× 下右侧
  （SERVER / STATUS / EULA / SHOW INTRODUCTION）被裁切，待单独修。

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

- `LoadLayers`（登录页）
- `GoStation` / `GoInflight`（进站 / 进空间）
- `OnSessionChanged`（会话切换兜底）

每次包层后把 `eve.triapp.uilib.desktopScale` 设为 `0.5`。调试日志在
`cache:/ui_scale_<pid>_<seq>.txt`。

## 验证

- 登录页：`desktopScale 1.0 → 0.5`，`desktop=720x460 → 360x230`，登录面板明显放大。
- 角色选择 / 空间站（2560×1440）：UI 2×。
- 日志确认设备/窗口重建后 `desktopScale` 被重新设为 0.5。

## 已知问题：登录页裁切

登录页使用 `res:/UI/Login/splashunderlay.blue`（固定尺寸的 `mainarea/toparea/bottomarea`），
2× 后内部按钮仍按原像素排，右侧超出窗口被裁。修法二选一：

1. 登录页保持 `desktopScale=1.0`，只在角色选择/进站后设 `0.5`（最简单，登录页不放大但不裁）。
2. 把 `splashunderlay` 及其子布局按 2× 放大（需要改 `.blue` 资源或登录页代码）。

## 回滚

删除客户端 `script\my_autoexec.py`，并删除 `cache\ui_scale_*.txt`。没有改
`compiled.code` / `bin\*.dll` / `res*.stuff`。
