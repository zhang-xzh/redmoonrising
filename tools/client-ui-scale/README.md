# 3913 客户端 UI 缩放（desktopScale）

## 状态

**可用。** 当前行为：

- **登录页 100%**（不裁切）。
- **角色选择 / 空间站 / 空间 200%**。
- 4K / 2560×1440 都适用；`desktopScale=0.5` = 200%，`1.0` = 原始。

## 原理

`trinity.dll` 的 `triui.UILib` 有浮点属性 `desktopScale`（成员偏移 `0x398`，默认 `1.0f`，
文档字符串 “Scales virtual desktop area”，字符串地址 `0x102c2564`）。

实测 `desktopScale` 是乘数：

```
desktopScale = 2.0  ->  desktop 720x460 -> 1440x920   (UI 变小)
desktopScale = 0.5  ->  desktop 720x460 ->  360x230   (UI 2x)
```

即 `desktop.width/height = 窗口尺寸 × desktopScale`。**0.5 就是 200% UI**。

登录页使用固定尺寸的 `res:/UI/Login/splashunderlay.blue`，2× 会裁掉右侧按钮，所以登录页
保持 `1.0`；角色选择、进站、进空间时设 `0.5`。设备/窗口在会话切换时会重建，
`desktopScale` 会重置，因此每个入口都重设一次。

## 安装

把 `my_autoexec.py` 复制到客户端：

```
M:\EVE-LOCAL\inputs\EVE-Online-3913\script\my_autoexec.py
```

`script/sys/autoexec.py` 会在 `script/run.py` 之前执行它。**不需要改
`compiled.code`、`bin\*.dll` 或 `res*.stuff`**，删掉该文件即回滚。

## 脚本做了什么

在真正的 `gameui` 服务实例（`__builtin__.sm.services['gameui']`）的类上包一层：

| 方法 | 缩放 | 时机 |
|---|---|---|
| `LoadLayers` | 1.0 | 登录页加载后 |
| `GoLogin` | 1.0 | 回登录页 |
| `GoCharacterSelection` | 0.5 | 角色选择前后 |
| `GoStation` | 0.5 | 进站前后 |
| `GoInflight` | 0.5 | 进空间前后 |
| `OnSessionChanged` | 0.5 / 1.0 | 按 `session.stationid`/`solarsystemid` 判断 |

调试日志：`cache:/ui_scale_<pid>_<seq>.txt`。

## 验证

- 登录页：`desktopScale 1.0`，`desktop=720x460`，完整不裁切。
- 角色选择：2560×1440 下日志 `GoCharacterSelection:pre` 设为 0.5，`desktop=1280x720`，
  UI 2×。
- 空间站/空间：`GoStation` / `GoInflight` 同样设 0.5。

## 回滚

删除客户端 `script\my_autoexec.py`，并删除 `cache\ui_scale_*.txt`。
