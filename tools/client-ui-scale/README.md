# 3913 客户端 200% UI 缩放（desktopScale）

## 状态

**可用。** 3913 客户端自带 `triui.UILib.desktopScale`，把虚拟桌面缩到窗口的一半即可得到
200% UI。当前实测：

- 登录页（720×460）：`desktopScale 1.0 → 0.5`，虚拟桌面 `720×460 → 360×230`，UI 2×。
- 角色选择 / 空间站（2560×1440）：2× 生效。
- 已知问题：登录页的 `res:/UI/Login/splashunderlay.blue` 是固定尺寸布局，2× 下右侧
  （SERVER/STATUS/EULA/SHOW INTRODUCTION 等）被裁切。下一步修这个页面。

## 原理

`trinity.dll` 的 `triui.UILib` 有一个浮点属性 `desktopScale`（成员偏移 `0x398`，默认
`1.0f`，文档字符串 “Scales virtual desktop area”，字符串地址 `0x102c2564`）。实测：

```
desktopScale = 2.0  ->  desktop 720x460 -> 1440x920   (UI 变小)
desktopScale = 0.5  ->  desktop 720x460 ->  360x230   (UI 2x)
```

即 `desktop.width/height = 窗口尺寸 × desktopScale`。**0.5 就是 200% UI**。

设备/窗口在登录后会按角色设置的分辨率重建，`desktopScale` 会被重置，所以脚本在
登录页加载、角色选择、进站/进空间时各重设一次。

## 安装

把 `my_autoexec.py` 复制到客户端：

```
M:\EVE-LOCAL\inputs\EVE-Online-3913\script\my_autoexec.py
```

`script/sys/autoexec.py` 会在 `script/run.py` 之前执行它。**不需要改
`compiled.code`、`bin\*.dll` 或 `res*.stuff`**，删掉该文件即回滚。

## 脚本做了什么

- 在真正的 `gameui` 服务实例（`__builtin__.sm.services['gameui']`）的类上包一层：
  - `LoadLayers`（登录页）
  - `GoStation` / `GoInflight`（进站/进空间）
  - `OnSessionChanged`（会话切换兜底）
- 每次包层后调用 `_set_scale()`，把 `eve.triapp.uilib.desktopScale` 设为 `0.5`。
- 调试日志写到 `cache:/ui_scale_<pid>_<seq>.txt`。

## 验证

- 登录页：`desktopScale 1.0 → 0.5` 后，虚拟桌面从 720×460 变成 360×230，登录面板明显放大。
- 角色选择 / 空间站：2560×1440 下 UI 为 2×。
- 日志确认每次设备/窗口重建后 `desktopScale` 被重新设为 0.5。

## 已知问题

登录页 `splashunderlay.blue` 固定尺寸，2× 后右侧按钮被裁切（见 `doc/client/3913-4k-ui-scaling.md`）。

## 回滚

删除客户端 `script\my_autoexec.py`，并删除 `cache\ui_scale_*.txt`。
