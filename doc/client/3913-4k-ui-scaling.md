# 3913 客户端 4K / 200% UI 缩放：可行性分析

本文记录 2026-11-01 一次会话的分析结论：**没有修改客户端**，只回答“2006 年的 build 3913
客户端能不能在 4K 显示器上做 200% UI 放大、可以怎么做”。

## 结论

| 项目 | 3913（2.10 / 2006）现状 |
|---|---|
| 4K 分辨率 | **支持**。分辨率列表直接来自 DX9 的 `EnumAdapterModes`，3840×2160 可选 |
| UI 200% 缩放 | **不存在任何机制**，需要额外实现 |
| 不改客户端的最优解 | **1080p + 整数 2× 放大**：UI 正好 200%，像素清晰（方块感而非模糊） |

4K 下的问题不是分辨率，而是 **UI 全部按固定像素排版**：屏幕面积变 4 倍，窗口与字体仍是
1024×768 时代的像素尺寸，看起来只有 1/4 大。

## 事实依据

### 1. 分辨率枚举是完整的

`script:/ui/services/devicesvc.py` 的 `GetAdapterResolutionsAndRefreshRates` 遍历
`eve.triapp.tridev.EnumAdapterModes(adapter, format)` 返回的 `Width/Height/RefreshRate`，
没有分辨率上限表。4K 可以进游戏，只是 UI 小。

### 2. UI 是固定像素的 triui

- `script:/ui/control/base.py`：UI 基类是 C++ 的 `triui.UISprite` / `xtriui.QuickDeco`。
- `script:/ui/control/window.py` 的 `DockWindow.Setup`：窗口 `left/top/width/height` 直接写
  像素，标题栏 `fontsize=10`，缩放角与按钮 `7/17/15` 像素，底板是
  `res:/UI/Component/wnd_underlay.blue`。
- `script:/ui/control/ulabel.py`：文字按 `fontSize` 参数走 `_PyFreeTypeP.dll` 渲染。
- `script/compiled.code` 共 **373 个顶层模块 / 11,589 个代码对象**，其中 7,530 个在 `/ui/`
  （207 个 UI 模块）。

### 3. 没有 DPI / UI 缩放

- `compiled.code`、`blue.dll`、`trinity.dll` 里都搜不到 `uiScale` / `dpiScaling` / `UIScale`。
- 对比现代客户端：`carbonui/services/device.py`（`GetUIScalingOptions` / `SetUIScaleValue`）
  与 `carbonui/primitives/desktop.py`（`dpiScaling` / `UpdateUIScaling`）就是那套实现；
  3913 没有对应物。

### 4. 可用的注入点（未使用，仅记录）

- `script/sys/autoexec.py` 在启动时执行 `script:/my_autoexec.py`（如果存在），随后才执行
  `script/run.py`。该文件是纯 `.py` 源码，由客户端自己的 Python 运行时编译，删掉即回滚。
- `script/compiled.code` 可用 `tools/client-code/eveccp.py` 读写（Python 2.3 marshal，
  magic `0A0DF23B`），`dis24.py` / `repack.py` 已经验证可字节级往返。
- `trinity.dll` 的 `triui` 模块有一个运行时属性 `desktopScale`，描述为
  “Scales virtual desktop area”（字符串 `0x102c2564`），同对象在渲染路径里把
  `[+0x398]` / `[+0x39c]` 当作 X/Y 乘数。**语义未实测**；如果可写且确实缩放虚拟桌面，
  就可能是一行代码的开关，但也可能只是只读统计量。

## 可选方案（成本从低到高）

### 方案 A：不改客户端，1080p + 2× 整数放大（推荐先用）

- 游戏内选 **1920×1080 全屏**，显卡驱动开 **Integer Scaling / 整数缩放**
  （NVIDIA 控制面板 → 调整桌面尺寸和位置 → 缩放模式“整数”、执行缩放“GPU”；AMD/Intel 类似）。
- 1920×1080 → 3840×2160 正好 2×，UI 正好 200%，每个像素变 2×2 方块，不模糊。
- 或窗口化 1920×1080 + Magpie（开源）/ Lossless Scaling（Steam）做 2× 整数放大到 4K 全屏。
- 成本：几分钟；风险：0；回退：改回分辨率。缺点：3D 是 1080p 渲染。

### 方案 B：4K 3D + UI 单独 2×（渲染层，中等）

- 写 `d3d9.dll` 代理，或 hook `trinity.dll` 的 UI 绘制阶段：UI 渲染到 1920×1080 的 RT，
  再 2× 合成到 3840×2160。
- 3D 维持 4K，UI 200%，不改 Python 与资源；但要识别 triui 的 UI pass（无源码，较脆），
  文字与图标本质是 1× 像素放大，会软。

### 方案 C：Python 层补一套 dpiScaling（原生清晰，工作量最大）

1. 用 `script/my_autoexec.py` 注入，不改 `compiled.code`。
2. 给 UI 基类（`xtriui.QuickDeco` / `xtriui.DockWindow` / `triui.UISprite` / `UIWindow` /
   `UIContainer`）统一加 `scale=2`：`left/top/width/height/pos/absolute*` ×2、`fontSize` ×2、
   `uilib.desktop.width/height` ÷2、鼠标坐标 ÷2。
3. 逐个处理直接算像素的地方：`ui/control/window.py`（`Position` / `CheckWndPos` /
   `StartScale` / `Scaling` / `EndScale`）、`ui/services/windowsvc.py`（`BorderSnap`）、
   `ui/control/ulabel.py`（`Layout` / `DoResize`，文本测量最易出问题）、
   `ui/inflight/bracket.py`（3D→2D 投影）、菜单/提示/下拉/滚动条/`systemmenu`。
4. 资源：`resui.stuff` 的 UI 贴图只有 1×（图标、边框、按钮），放大后会糊；要完全清晰需
   重制 2× 贴图并重建 `resui.stuff`。

- 字体由 `_PyFreeTypeP` 按新 `fontSize` 重新栅格化，**文字能保持清晰**。
- 工作量：原型 1–3 天能“看起来 200%”，完整可用以周计；风险在 hit-test、文本测量、滚动、
  窗口吸附、IME、bracket 投影。

### 方案 D：改 `trinity.dll`（最干净、最难）

- 在 C++ 里给 UI 渲染加全局 2D 变换、鼠标映射、字体尺寸；没有源码，需要逆向 + hook。
- 先验证 `triui.desktopScale`（10 分钟实验）：
  ```python
  import triui
  print dir(triui)            # 看有没有 desktopScale
  triui.desktopScale = 2.0    # 或 (2.0, 2.0)
  ```
  如果 UI 整体放大，方案 D 退化成一行代码；如果只读或值不变，就只是统计量。

## 建议顺序

1. **方案 A 顶着用**（今天就能 200%，零风险）。
2. 想要 4K 原生 3D 时，**先验证 `triui.desktopScale`**（不改文件，删 `my_autoexec.py` 即回滚）。
3. 验证不成立，再在 **B（UI 软但改动小）** 与 **C（清晰但工期长）** 之间选。

## 验证要点

- 3840×2160 下逐项看：窗口像素尺寸是否正好 2×、文字清晰度、点击/拖拽是否对位、
  窗口最小尺寸与吸附、bracket/右键菜单/提示框、登录与角色选择、中文 IME。
- 客户端行为的证据入口：`capture\Gamelogs`、`capture\Chatlogs`、`logs\#errors b3913 *.txt`。
- 回滚：删除 `script\my_autoexec.py`；若改过 `compiled.code`，用 `compiled.code.vanilla` 覆盖。

## 本次会话实际改动

- **没有修改 3913 客户端**（`compiled.code`、`lib\*.pyo`、`bin\*`、`res\*.stuff` 均未动）。
- 没有实测 `triui.desktopScale`；没有落盘任何客户端补丁。
- 分析用的临时脚本只存在于 `M:\EVE-LOCAL\_scratch\`，不属于本仓库。
