# 数据库

角色、物品、军团、市场等全部持久化在 PostgreSQL 里；表结构来自 2006 年零售数据库转储。

## 布局

| 项 | 值 |
|---|---|
| 服务 | `postgres:16-alpine`（容器 `rmr-postgres`） |
| 库 / 用户 / 密码 | `rmr` / `rmr` / `rmr` |
| 命名卷 | `pgdata`（`/var/lib/postgresql/data`） |
| 初始化脚本 | `./db`（只读挂到 `/docker-entrypoint-initdb.d`） |
| 宿主端口 | 5432 |
| 连接串 | `postgres://rmr:rmr@127.0.0.1:5432/rmr`（容器内用服务名 `postgres`） |

`db/*.sql.gz` 共 212 个文件，每表一个（`account`、`character_`、`invItems`、`staStations`、`agtAgents`、`crpNPCCorporations`、`mapSolarSystems`、`bot*` 等），`00_shared.sql.gz` 负责共享对象。**它们只在卷为空时导入一次**。

## 常用查询

```powershell
docker compose exec postgres psql -U rmr -d rmr -c "SELECT \"accountID\",\"accountName\",\"role\",\"banned\" FROM \"account\" LIMIT 20;"
docker compose exec postgres psql -U rmr -d rmr -c "SELECT count(*) FROM \"character_\";"
docker compose exec postgres psql -U rmr -d rmr -c "\dt" | Select-Object -First 40
```

字段名沿用零售：`account` 表用 `"accountID"`、`"accountName"`、`"password"`、`"role"`、`"banned"`（见 `crates/eve-server/src/db.rs:21`）。SQL 里大小写敏感列名必须加双引号。

## 备份 / 恢复

```powershell
# 备份整个库到宿主（PowerShell 重定向默认 UTF-16，必须指定编码）
docker compose exec -T postgres pg_dump -U rmr -d rmr | Out-File -Encoding utf8 M:\EVE-LOCAL\_scratch\rmr-backup.sql

# 恢复
Get-Content -Encoding UTF8 M:\EVE-LOCAL\_scratch\rmr-backup.sql | docker compose exec -T postgres psql -U rmr -d rmr
```

## 重置（破坏性）

清卷会**删除所有角色与角色资产**，只有确实要回到初始转储时才做，且先让用户确认：

```powershell
docker compose down
docker volume ls | Select-String pgdata          # 确认卷名（compose 项目名 + _pgdata；name: rmr 时是 rmr_pgdata）
docker volume rm rmr_pgdata
docker compose up -d
docker compose logs server --tail 50             # 确认重新导入完成、无 ERROR
```

## 版本与溯源

`db/*.sql.gz` 是 2006 年那代服务端的运行库转储，**不是官方 SDE，也没有 build/版本列**
（`schema_migrations` 为空，dump 是近年用 PostgreSQL 16.15 重新导出的）。内容锚点显示它是
RMR/Blood 前后的数据，但不能证明就是 build 3913；详见
[`doc/data/provenance-3913.md`](provenance-3913.md)。

- 改 `db/` 或客户端前后各跑一次 `tools/data-provenance/provenance.py manifest --verify`
  （基线 `tools/data-provenance/manifest-3913.json`）。
- 数据与客户端冲突时以客户端字节码/行为为准；新增数据后用 `provenance.py check` 核对消息键。

## 修改表结构的规则

- 零售转储表结构是权威；新增列/表必须给出理由与零售依据，并同步更新本文档与相关代码。
- 迁移脚本不要塞进 `db/`（只在空卷生效）：写成一次性 SQL，经容器执行，并记录到本文档相关主题。
- 数据改动（补数据、修角色）走 `psql` 且在文档里留下可复现的 SQL。

存档数据的操作边界见 `AGENTS.md`「存档数据操作规则」；详细命令见 `AGENTS-DETAIL.md`。
