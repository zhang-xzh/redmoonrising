# 3913 客户端 / 数据库溯源工具

回答两个问题：**现在这份客户端和 `db/` 到底是不是 build 3913 的？** 以及**它有没有被悄悄改过？**

`db/*.sql.gz` 是 2006 年那代服务端的 PostgreSQL 运行库转储，不是 CCP 官方 SDE，也没有
build/版本列（`schema_migrations` 是空的）；客户端 `script/compiled.code.vanilla` 目前缺失。
所以“版本一致”只能靠**内容锚点**和**交叉校验**来逼近，这个工具把这两件事固定下来。

## 子命令

| 命令 | 作用 | 依赖 |
|---|---|---|
| `manifest --out FILE` | 给客户端安装目录 + `db/*.sql.gz` 生成 sha256 清单（430 个文件：客户端 218、db 212） | 客户端目录 |
| `manifest --verify FILE` | 重新计算并与清单比对，输出缺失/大小/hash 不一致 | 客户端目录 |
| `snapshot --out FILE` | 直接从 `db/*.sql.gz` 解析行数、内容锚点和 `eveMessages` 键表（不需要 Postgres） | 无 |
| `client-keys` | 从 `script/compiled.code` 字节码提取 `eve.Message('Key')` / `cfg.GetMessage('Key')` / `mls.KEY` 的键 | 客户端 |
| `check --snapshot FILE` | 客户端键 vs `messages.txt` vs `eveMessages`：找出客户端要、但两边都没有的键（数据漂移） | 客户端 + 快照 |

## 用法

```powershell
$PY = 'C:\Users\zhang\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe'
cd M:\EVE-LOCAL\redmoonrising

# 基线（改客户端/DB 前后各跑一次 verify）
& $PY tools\data-provenance\provenance.py manifest --out tools\data-provenance\manifest-3913.json
& $PY tools\data-provenance\provenance.py manifest --verify tools\data-provenance\manifest-3913.json

# 数据库内容锚点
& $PY tools\data-provenance\provenance.py snapshot --out tools\data-provenance\db-snapshot-3913.json

# 客户端 ↔ 数据交叉校验
& $PY tools\data-provenance\provenance.py check --snapshot tools\data-provenance\db-snapshot-3913.json
```

`manifest` 里的客户端路径是绝对路径，`--verify` 时会读清单里的记录；换机器/换客户端目录用
`--client` / `--db` 覆盖。

## 当前基线（2026-11）

- `manifest-3913.json`：430 个文件，客户端 218 + db 212；`manifest --verify` 0 问题。
- `script/compiled.code` sha256 `daa5eae3…`（= 零售原版，md5 `36e18ef3…`）；
  `script/compiled.code.zh-prev-20261101-194509` 是上一版中文包（md5 `251dfdef…`）；
  **`compiled.code.vanilla` 不存在**，重置来源改用 `M:\EVE-LOCAL\inputs\EVE-Online-3913-code\dist\compiled.code`。
- `db-snapshot-3913.json`：13,261 types / max typeID 25,388 / 559 groups / 5,334 systems /
  66 regions / 1,781 messages；有首都舰、无 rigs/contracts/Marauder/T3/Orca，但
  `ramActivities` 里有 `Invention`（客户端无 invention UI）——详见 `doc/data/provenance-3913.md`。
- `check`：客户端 254 个消息键，81 个来自 `messages.txt`、172 个来自 `eveMessages`、
  1 个两边都没有：`NotAtStation`（`ui/services/clonejumpsvc.py`，进游戏会显示 “Message not found”）。

## 设计说明

- **只读**：不写客户端、不写数据库、不改 `db/`，只产出 JSON。
- 客户端键从**字节码**提取，不用反编译 tree（`parklife/gameui.py` 这类模块反编译会丢代码）。
- 只接受“第一个位置参数是常量”的调用：`eve.Message('Key')`、`cfg.GetMessage('Key')`；
  `eve.Message(msgName, {...})`、`'NeoCom' + action`、`onNotFound='raise'` 这类动态/关键字参数不会被误收。
- `mls.X` 只收真正的消息键，排除 `langPacks` / `TR` / `LoadLanguagePack` 这几个属性。
- `snapshot` 直接解析 pg_dump 的 `COPY ... FROM stdin;` 段，不依赖 Docker 容器是否在跑。
