# 3913 启动时 DirectX 版本提示修复

## 问题

Windows 10/11 的 `d3d9.dll` 版本是 **10.0.x**，而 3913 的
`script/sys/autoexec.py` 里 `GetDXVersion()` 只识别 4.x / 5.x：

```python
if Hiword(d3d9) == 4 and d3d9 >= Long(4, 9, 0, 902): ...
if Hiword(d3d9) == 5 and d3d9 >= Long(5, 3, 1, 902): ...
```

10.x 两个条件都不满足，`ver` 停在 `(9, 0, "")`，`CheckDXVersion()` 就弹出：

```
DirectX 9.0 detected but this application needs 9.0b
Try continue with old DirectX version?
```

## 修复

把版本判断改成只看数值，不再限定主版本号：

```python
if d3d9 >= Long(4, 9, 0, 904):
    ver = (9, 0, "c")
elif d3d9 >= Long(4, 9, 0, 902):
    ver = (9, 0, "b")
```

10.0.x ≥ 4.9.0.904，因此报告 9.0c，不再弹窗。

补丁：`autoexec.py.patch`。

## 安装

1. 备份客户端 `script\sys\autoexec.py`（当前已备份为 `autoexec.py.bak-rmr`）。
2. 应用 `autoexec.py.patch`，或手动把那 5 行替换成上面的 6 行。
3. **完全重启客户端**。

`autoexec.py` 是纯 `.py` 源码，不属于 `compiled.code`；不需要重建容器。

## 验证

- 启动 `bin\exefile.exe`，不再出现 “Try continue with old DirectX version?”。
- 直接进入登录页；`logs\history.txt` 有 STARTUP，没有相关弹窗。

## 回滚

把 `script\sys\autoexec.py.bak-rmr` 覆盖回 `script\sys\autoexec.py`，重启客户端。
