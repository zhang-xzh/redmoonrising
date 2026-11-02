# AGENTS 详细参考（按需读取）

> 从 `AGENTS.md` 拆出的详细操作参考（worktree 命令、数据卷操作细节、异常归档模板、skill 规范等）。规则本体在 `AGENTS.md`，本文件只在执行对应任务时读取，避免常驻上下文。命令按 PowerShell 写（本工作区 shell 是 PowerShell 5.1）。

## worktree 详细（创建/清理/并发合并/边界/验证）

## 如何创建与使用

- 先同步 `plus`，再以它为起点建 worktree 并检出任务分支：

  ```powershell
  cd M:\EVE-LOCAL\redmoonrising
  git fetch                       # 有远端时
  git checkout plus
  git pull                        # 有远端时
  git worktree add -b <前缀>/<功能>-$env:OPENCODE_SESSION_ID M:\EVE-LOCAL\worktrees\wt-rmr-<功能> plus
  ```

- worktree 目录一律放在**仓库之外**（`M:\EVE-LOCAL\worktrees\`），不得放进仓库内，否则会成为仓库里的未跟踪文件。
- 每个对话的 opencode 会话以其 worktree 路径为 `workdir`；所有 git 命令在各自 worktree 内执行。
- 首次构建要各自 `cargo build`（`target/` 默认在 worktree 内）；想省时间可设共享 `CARGO_TARGET_DIR`，但并发编译会抢锁。

## 并发合并

- 合并仍在主工作区进行：切回 `plus` → 同步 → `git merge --no-ff <任务分支>`；按上文“串行合并”循环处理，不要假设自己的分支基线仍是最新。
- 收尾清理（该分支已合并、worktree 干净后）——**只删 worktree 目录，分支保留**：

  ```powershell
  git worktree remove M:\EVE-LOCAL\worktrees\wt-rmr-<功能>
  git worktree prune
  ```

## 不隔离的部分（关键）

- **端口与运行时**：26000（游戏）、8080（web）、5432（Postgres）整机唯一；同一时刻只能起一套 `rmr-server`/`rmr-postgres`。worktree 只隔离代码/构建，**不隔离容器、卷与数据库**。
- **数据库共享**：`pgdata` 卷里是同一套角色数据；并行改代码可以，但不要让多个对话同时重启/重播种数据库。
- 严格遵守“客户端在运行时禁止重启服务端”：任一 worktree 对话要重启 server 前，先确认 `exefile` 没在跑。

## 验证

- `git worktree list` 应列出主工作区 + 各对话 worktree，且每个 worktree 的分支互不相同。
- 在各 worktree 内 `git branch --show-current` 应返回各自的任务分支。

## 客户端代码仓库（未来：3913 `compiled.code`）

- 3913 客户端代码的逐模块基线在独立 git 仓库 `M:\EVE-LOCAL\inputs\EVE-Online-3913-code`（见 `doc/client/client-code-baseline.md`）；本仓库只保留代码工具（`tools/client-code/`，已入库）与本地化流水线（`tools/localization/`），两者不要互相覆盖。
- 建立仓库后的目标布局（与 3396210 仓库同一套策略）：
  - `tree\` = 解包出的 `script/`（模块路径 → marshal blob），权威且字节精确。
  - `patches\` = 改写脚本/安装器（只用 `tools/client-code/*.py` 与 `tools/localization/*.py`）。
  - `dist\compiled.code` = 打好的原包；`main` = 零售基线，`plus` = 开发主线。
- 建仓库前的大改一律先手工备份 `compiled.code`：

  ```powershell
  Copy-Item M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code `
            M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code.bak -Force
  ```

- worktree 命令（仓库建成后）：

  ```powershell
  git -C M:\EVE-LOCAL\inputs\EVE-3913-code.ccp worktree add -b <前缀>/<功能>-$env:OPENCODE_SESSION_ID M:\EVE-LOCAL\worktrees\wt-client-<功能> plus
  ```

## 存档数据操作详细（Postgres 卷）

## 如何访问

Docker Desktop 的命名卷不在宿主机路径上，宿主机工具不能按路径直接写卷；一律通过容器：

1. 交互式 SQL：`docker compose exec postgres psql -U rmr -d rmr`
2. 单条查询：`docker compose exec postgres psql -U rmr -d rmr -c "SELECT count(*) FROM \"account\";"`
3. 备份到宿主：`docker compose exec -T postgres pg_dump -U rmr -d rmr | Out-File -Encoding utf8 backup.sql`
4. 从宿主恢复：`Get-Content -Encoding UTF8 backup.sql | docker compose exec -T postgres psql -U rmr -d rmr`
5. 单文件进出：`docker cp` / `docker compose cp`。

## 当前状态（compose 与数据）

- `docker-compose.yml`：`postgres:16-alpine`（容器 `rmr-postgres`，卷 `pgdata`，初始化目录 `./db` 只读）+ `server`（镜像 `rmr-server`，容器 `rmr-server`，挂载 `./rmr.yml` 只读，`RMR_DATABASE` 指向服务名 `postgres`）。
- `db/*.sql.gz`（212 个文件）只在**卷为空**时导入一次；之后改 `db/` 不影响已有卷。
- 重置数据库（**破坏性，先让用户确认**）：

  ```powershell
  docker compose down
  docker volume rm rmr_pgdata         # 卷名 = compose 项目名 + _pgdata（compose 里 name: rmr 时是 rmr_pgdata）
  docker compose up -d
  ```

- 服务端自身还会在 `RMR_DUMP_DIR`（容器内 `/app/dumps`）落无法解码的帧，用于排查协议问题。

## 异常归档正文模板（doc/issues/<name>.md 必填小节）

正文必须包含以下小节，且命令/路径可复制直接执行：

1. **症状** —— 报错原文、错误码、复现步骤、影响面（游戏内 / 服务器 / 数据）。
2. **根因** —— 为什么发生，涉及的具体文件与函数（`file_path:line`）。
3. **诊断步骤** —— 定位用的具体命令（`docker compose logs server --tail 100`、`psql` 查询、`fakeclient` 复现、客户端 `capture\Gamelogs` 片段）。
4. **修复步骤** —— 具体改动（文件、命令、SQL、卷内路径），遵守 `AGENTS.md` 的“存档数据操作规则”。
5. **验证** —— 修复后如何确认异常消失。
6. **回滚 / 预防** —— 出问题时如何回退，以及如何避免复发。
7. **关联** —— 相关文档、commit、日志位置。
8. **触发关键词** —— 报错原文、错误码、组件名、中英文症状词，供按症状检索与自动加载后精确定位。

## 能力 skill 的 SKILL.md 规范

只有能力/操作方法才新建独立 skill；异常一律不做 skill。

```markdown
---
name: <简述>
description: Use when <用途/触发，英文优先，≤~180 字符>。Triggers: <最关键 3-6 个触发词>
---

# <标题>

正文（工作流、命令、坑）
```

- `name` 必须与目录名一致；`description` 随 skill 目录在**每次请求**全量加载，是固定开销的最大头，必须极简（≤ ~180 字符）；放不下的完整触发词写进正文 `## 触发关键词`。
- 每次新增/改 skill 后，确保 `name`/目录名一致，并提醒用户重启 opencode 使新 skill 生效。
