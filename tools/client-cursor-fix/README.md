# 3913 鼠标光标修正（d3d9 代理）

## 问题

`desktopScale=0.5`（200% UI）后，游戏窗口内鼠标移动变慢 / 变粗，登录器 100% 时正常。
原因是 3913 的 `triui` 硬件光标使用缩放后的虚拟桌面坐标；在 2560×1440 窗口、
`desktopScale=0.5` 时，光标位置和鼠标物理位置不一致，手感明显不同。

另外，4K 面板 + Windows 150% 缩放下，3913 的 `exefile.exe` 默认 DPI-unaware，Windows
会把窗口和鼠标再虚拟化 1.5×，需要同时设为 DPI-aware。

## 修复

`bin\d3d9.dll` 代理：

- 转发 `Direct3DCreate9` 到系统 `d3d9.dll`。
- hook `IDirect3D9::CreateDevice`。
- 用 `VirtualProtect` 原位替换 `IDirect3DDevice9::SetCursorPosition`（vtable index 11）：
  不再使用游戏传入的虚拟坐标，而是 `GetCursorPos` + `ScreenToClient` 取真实客户区坐标，
  再调用原函数。UI 命中测试仍用虚拟坐标，不受影响。

配合 DPI 感知（见 `doc/client/3913-4k-ui-scaling.md`）：

```
HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers
    M:\EVE-LOCAL\inputs\EVE-Online-3913\bin\exefile.exe = "~ HIGHDPIAWARE"
```

实机日志（`bin\cursor_fix.log`）：

```
SetCursorPosition game=(2249,1195) raw=(689,377) flags=0x00000000
```

用户确认鼠标手感恢复正常。

## 安装

1. 把 `d3d9.dll`、`cursor_fix.ini` 复制到客户端 `bin\`。
2. 设置上面的 DPI 注册表值。
3. **完全重启客户端**（DLL 只在进程启动时加载）。

`cursor_fix.ini`：

```
[cursor_fix]
enabled=1
```

## 回滚

删除客户端 `bin\d3d9.dll`、`bin\cursor_fix.ini`、`bin\cursor_fix.log`，并删除 DPI 注册表值。
没有改 `compiled.code` / `res*.stuff` / 原有的 `bin\*.dll`。

## 构建

```
build.bat
```

需要 VS x86 工具链；输出 `d3d9.dll`。`d3d9.def` 导出未修饰的 `Direct3DCreate9`。
