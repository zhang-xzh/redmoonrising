# Red Moon Rising（RMR）工作区规则

面向 EVE Online 2.10 / build 3913（2006，codename **Blood**）的 machoNet 服务端，Rust workspace：

- `crates/eve-marshal`：EVE marshal 编解码（含客户端共享字符串表）。
- `crates/eve-proto`：LLV 版本握手、machoNet 帧、包与地址。
- `crates/eve-server`：服务端本体（连接/服务/ballpark/bots/web）。

客户端固定为 `M:\EVE-LOCAL\inputs\EVE-Online-3913`（启动器 `eve.exe`，真正的游戏进程是 `bin\exefile.exe`；**永不升级**）；游戏端口 **26000**，web 面板 **8080**。上游仓库 `origin` = `github.com/pixelcatburglar/redmoonrising`。

本文件对本工作区内全部开发强制生效；详细操作（worktree 命令、数据卷操作、异常模板、skill 规范）见 `AGENTS-DETAIL.md`，只在执行对应任务时读取。

---

# 每任务独立 worktree（强制且唯一）

**开发主分支是 `plus`。每个任务从新分支开始，完成后合并回 `plus`；禁止直接在 `plus` 上开发。任务开工一律用独立 git worktree 检出任务分支——worktree 是唯一开工方式，全面禁止在主工作区或任何主 checkout 里直接 `git checkout -b` / `git switch -c` 创建分支。**

- 两条长期分支：
  - `plus` = 开发主分支（任务分支合入目标），主工作区 `M:\EVE-LOCAL\redmoonrising` 固定检出它。
  - `main` = 上游/零售基线（跟踪 `origin/main`），只用于对照与重置，不承载任务开发、不合入任务分支。
- **开工（唯一方式）**：
  1. `git fetch`（有远端时）→ 主工作区 `git checkout plus` → `git pull`（有远端时）。
  2. `git worktree add -b <前缀>/<功能>-$env:OPENCODE_SESSION_ID M:\EVE-LOCAL\worktrees\wt-rmr-<功能> plus`。
  3. 之后所有开发都在该 worktree 目录内进行（session `workdir` 指向它）。
- **禁止事项**：不得用 `git checkout -b` / `git switch -c` 在已有目录里建分支；不得在主工作区改动文件做任务；不得为开工在已有 checkout 内切分支。
- 命名：`<前缀>/<功能>-<sessionid>`；前缀 `feat/`、`fix/`、`doc/`、`chore/`；`<功能>` 简短英文；`sessionid` 取当前对话 id（本地插件 `.opencode/plugins/session-id.js` 注入环境变量 `$OPENCODE_SESSION_ID`）。
- 分支只承载本任务改动；同一任务多步改动留在同一分支、同一 worktree。
- 完成后：worktree 内提交干净（无未提交内容）→ 回主工作区 `git checkout plus` → 同步 `plus` → `git merge --no-ff <分支>` → 解冲突并提交。**合并后保留分支、不删除**；只 `git worktree remove` 清理目录。
- 合前若 `plus` 已前进，先把分支 rebase/merge 到最新 `plus`。
- 禁止带未提交改动切分支；禁止跨任务复用同一分支；禁止同一分支被两个 worktree 同时检出。

## 并发合并（多对话同时开工）

git 对分支引用加锁、更新原子，**不存在真正的同时合并**：同一目标分支的并发合并只有一个成功，其余会报 `cannot lock ref` / non-fast-forward，须 `git fetch` 后重试。多对话并行按**串行合并**处理：每次都走「同步 `plus` → rebase/merge 最新 `plus` → 合并 → 提交」的完整循环。同文件同区域是文本冲突（人工解），不同区域可能是语义冲突（git 不提示，自行验证）。

## worktree 不隔离的部分

- **端口与运行时共享**：26000（游戏）、8080（web）、5432（Postgres）是整机唯一的，多个 worktree 不能同时起 server。要跑服务端前先确认没有别的 RMR 实例在跑。
- **数据库共享**：Docker 命名卷 `pgdata` 与 `rmr-postgres` 容器是全局的，所有 worktree 共用同一套角色数据。并行改代码可以，但不要让多个对话同时重启/重置数据库。
- **构建产物**：Rust `target/` 默认在各 worktree 内，首次构建要重新编译；可显式共享 `CARGO_TARGET_DIR` 省时间，但要接受并发编译锁等待。

---

# 完成即自动提交（强制）

**每次完成一次修改（代码/文档/配置/脚本/skill），收尾时自动 `git commit`，不等用户说“提交”。**

- 仓库根 `M:\EVE-LOCAL\redmoonrising`；git 命令在**当前 worktree 目录**执行。
- 一次修改完成即提交，不攒着；同一会话的多步改动可合并为一个提交。
- 提交前看 `git status` / `git diff` / `git log --oneline -10`，只 stage 本次有意改动；绝不提交密钥、日志、`dumps/`、`target/`、临时产物；不 `--force`、不建空提交。
- 提交信息：简短英文祈使句（`Add ...` / `Fix ...` / `Allow ...`），一句话说清改了什么。
- 提交后报告短 hash 与摘要；**不自动 push**（除非明确要求）；提交失败另起新提交、不 amend。
- `.gitignore` 仍写着 `tools/`、`target/`、`crates/eve-server/web/node_modules/`；但客户端本地化流水线与产物已用 `git add -f` 纳入版本库（`tools/localization/`、`config/localization/`）。该目录下**新增**文件默认仍被忽略，需显式 `git add -f`。

---

# 异常处理与归档（强制）

**每处理一种已定位/已解决的客户端或服务器异常，必须归档成一篇文档并在索引登记一行；正文 + 索引都落盘才算完成。**

- 正文 `doc/issues/<name>.md`（写成当前状态）；索引 `doc/issues/INDEX.md` 表格加一行（文档路径 + 症状/触发词一句话）。
- 一种异常 = 一篇文档 + 一行。判定“不同异常”依据：不同错误码 / 报错原文 / 触发条件 / 根因；同根因的不同表象合并为一篇，同类复现则**更新**已有文档与索引，不新建重复项。
- 命名：`rmr-issue-<英文简述>.md`（小写连字符），例 `rmr-issue-llv-build-mismatch.md`。
- **异常一律不做 skill**（skill 的 description 每请求全量加载，只增固定开销）；异常只落文档。
- 正文必填小节见 `AGENTS-DETAIL.md`「异常归档正文模板」。处理异常前先读 `doc/issues/INDEX.md` 按症状/报错检索，有则更新、无则新建。

---

# 功能修改必须有记录（强制）

**任何功能/行为修改都必须落盘到仓库文档，且写成“当前状态”，不是变更流水账。**

- 范围：`crates/**` 代码、`rmr.yml` 配置项、`db/` 静态数据、客户端代码补丁（`script/compiled.code`）、`tools/` 工具链与脚本，及任何对外行为改动。
- 方法：综合进**相关主题** `doc/<领域>/<文档>.md`（目录与放置约定见 `doc/README.md`），删除已被取代的旧内容，使文档描述“现在是什么样”；不追加 `> 2026-xx-xx 更新` 之类的流水账。
- 一个改动 = 写入/更新对应主题文档；无合适文档则新建并在 `doc/knowledge-inventory.md` 登记一行；同主题多次改动持续更新同一文档。
- 记录须含：改了什么/为什么、涉及文件与函数（`file_path:line`）、当前生效的配置/数值、生效方式（`rmr.yml` + 重启容器 / 服务端代码重建镜像 / 客户端补丁完全重启客户端）、验证与回滚。

---

# 零售版本优先（绝对第一优先级）（强制）

**一切修复、补全与实现，一律以零售版本（2006 年官方 build 3913 客户端及其数据）的实际内容为绝对第一优先级。**

- 存在“零售原状”与“自造/近似/占位”两种做法时，**无条件采用零售原状**。
- 零售权威来源只认这几处：
  - 客户端代码与数据：`M:\EVE-LOCAL\inputs\EVE-Online-3913\script\compiled.code`（当前工作包，**已非原样**）、`script\compiled.code.vanilla`（零售原样备份，权威基线）、`lib\*.pyo` / `stdlib\**`、`res\*.stuff`、`boot.ini`（`version=2.10 / build=3913 / codename=Blood`）。
  - 数据库：`db/*.sql.gz`（212 个官方表转储），客户端协议与字段以表结构为准。
  - 客户端行为：`eve.exe` 自带逻辑与 `capture\Gamelogs`、`capture\Chatlogs` 的实际输出；服务端代码里由反汇编得来的格式注释（如 `crates/eve-server/src/destiny.rs`、`ballpark.rs`）即是这条线的产物。
- 自造内容仅作临时缺口填补，且须在确认零售无对应后才可用，并在文档中写明缺口与获取途径；不得臆造冒充零售。
- 数值、名称、分组、掉落、行为一律可追溯到上述来源；记录中写明“零售依据”（文件 / 表 / 条目 ID / 反汇编地址）。
- 现代 EVE（如 3396210 客户端、everef 数据集）**不能**直接当成本项目的取值依据：二十年里类型、属性、市场与 UI 都变过；只可作思路参照，取值一律回到 3913 客户端与 `db/`。

---

# 仔细验证修改内容（强制）

**任何改动都必须经过实际验证，不得凭推测、凭“看起来对”就宣称已修复或已生效。**

- 改前先读懂现状：用 `grep`/`read` 确认真实调用链与当前行为，必要时读日志、查数据库、看客户端表现；不理解现状不动手。
- 改后必须实跑验证，按改动类型至少做一层运行时验证：
  - 编译/静态：`cargo fmt --check`、`cargo build -p eve-server`、`cargo test -p eve-marshal -p eve-proto`、`cargo clippy`（可选）。
  - 服务端：`docker compose logs server --tail 100` 看启动、错误与 service 调用；必要时 `RMR_LOG=debug`。
  - 协议/玩法：用内置 `fakeclient`（`cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000 [--script <file>]`）跑无头断言，或进客户端实际操作。
  - 数据：`docker compose exec postgres psql -U rmr -d rmr -c "<SQL>"` 确认落库结果。
  - 客户端表现：完全重启客户端后确认；证据可取自 `capture\Gamelogs`、`capture\Chatlogs`。
- 结论要给证据：说明用什么命令/入口验证、看到什么结果；无法验证或只做了部分验证的部分如实写明。
- 验证结果与预期不符时，先查清根因再继续，不靠叠加补丁掩盖问题；改坏了就回滚或修正，不留半成品。
- 破坏性变更（数据库表结构、协议字段、`rmr.yml` 配置键、`/` 命令与 GM 菜单项、模块边界、目录结构）允许做，但改前先列出受影响的调用方/脚本/文档清单，改完逐个确认已同步，并实跑主要路径。
- 不写兼容层、不为将来预留抽象；整体替换优于打补丁，但替换后同样要按上面几条验证到位。

---

# 存档数据操作规则（RMR）

**所有角色/世界数据都在 PostgreSQL 里，落在 Docker 命名卷 `pgdata`；不得把宿主机路径当成数据根直接改。**

- 数据库由 `docker-compose.yml` 的 `postgres:16-alpine` 提供（容器 `rmr-postgres`，库/用户/密码都是 `rmr`，宿主端口 5432）。
- `db/*.sql.gz` 只在**卷为空**时由 `/docker-entrypoint-initdb.d` 导入一次；卷已存在时改 `db/` 不会生效——要重播种必须显式清卷（会**清空所有角色**，属破坏性操作，执行前必须让用户确认）。
- 读/写/备份/恢复一律通过容器：
  - 查询：`docker compose exec postgres psql -U rmr -d rmr -c "<SQL>"`
  - 备份：`docker compose exec -T postgres pg_dump -U rmr -d rmr | Out-File -Encoding utf8 backup.sql`（PowerShell 默认写 UTF-16，务必指定编码）
  - 恢复：`Get-Content backup.sql | docker compose exec -T postgres psql -U rmr -d rmr`
- 客户端 `exefile` 在跑时不要动数据库与服务端进程（见下节）。
- 详细命令与卷内路径见 `AGENTS-DETAIL.md`。

---

# 客户端在运行时禁止重启服务端（强制）

**动手前先确认 EVE 客户端是否运行；只要客户端在运行，禁止重启服务端。**

- “重启”含：`docker compose restart server`、`docker compose up --force-recreate server`、`docker compose down`/`up`、`Start-RMR.bat` 触发的重启，以及任何导致 `eve-server` 进程退出/连接被切断的操作；不得用 `docker kill` / `docker stop` 绕过。
- 原因：重启会切断在线客户端会话，2006 年的客户端可能卡死、报错或丢失未保存状态。
- 判断：`powershell -NoProfile -Command "Get-Process exefile -ErrorAction SilentlyContinue | Select-Object Id,StartTime"`（有输出即游戏在运行；只开着启动器 `eve.exe` 也算即将进入游戏，按运行处理）。
- 客户端运行时：不执行任何重启命令；改动需重启才生效时，先完成所有落盘（代码/文档/skill）并提示用户关闭客户端，等客户端退出后再重启。

---

# 客户端代码修改（强制）

**3913 客户端的 Python 代码只有两种形态：`script\compiled.code`（自定义容器：Python protocol-1 pickle + marshal code object，373 个模块，约 7.9 MB）和 `lib\*.pyo` / `stdlib\**` 里的散装字节码。`bin\exefile.exe`、`bin\*.dll`、`res\*.stuff` 一律不改。**

- 零售原样备份 `script\compiled.code.vanilla` 必须保持不动，它是唯一的重置来源。**当前 `compiled.code` 已与 vanilla 不同**（143/373 个模块被改过，2026-11-01 写入），即工作包已经带本地化改动；要回到零售状态就从 `.vanilla` 重新生成。
- 改动一律**由脚本生成**，可复现：工具在 `tools/localization/`（`eveccp.py` 读写容器、`dis24.py`/`opcode24.py` 反汇编、`localize_code.py` 改字符串、`scan.py`/`verify.py` 校验、`make_messages_zh.py` 生成静态消息文件；映射表 `config/localization/ui_en_zh.json`），已纳入版本库。
- 工具与产物都在版本库：`tools/localization/README.md`（用法）、`tools/localization/artifacts/compiled.code.zh`（当前客户端包，md5 `251dfdefbfa6eda204821afbf3dec74e`，与客户端 `script/compiled.code` 当前一致）、`artifacts/messages.zh.txt`、`artifacts/prefs.zh.ini`；详细流程见 `docs/client-localization-3913.md`。`tools/` 仍在 `.gitignore` 里，新增文件要 `git add -f`。
- 已知缺口：3913 仍没有 `tree/`+`dist/` 形态的独立客户端代码仓库；现在的版本化载体是本仓库的脚本 + `artifacts/`。要做结构性大改（增删模块、改逻辑）前，先评估是否拆出独立仓库（分支策略同本仓库：`plus`/`main`）。
- 每次写入前备份当前 `compiled.code`；写完必须进客户端**完全重启**验证（字节码只在进程启动时载入），并记录到 `doc/client/`。

---

# 性能分析前提（强制）

**性能分析/性能测试/性能优化一律默认以「单机单用户、无客户端升级」为前提；脱离该前提的结论必须先与用户确认。**

- **单机**：服务端（本机 Docker Compose）与客户端跑在同一台机器上；不评估多机部署、集群/负载均衡。
- **单用户**：只有 1 个在线角色/会话；不作为多用户并发目标优化或压测。注意：bot 人口（`bots.count`，本地 `rmr.yml` 现为 100000）**不是**用户并发，压测/优化前先分清瓶颈在 bot 模拟还是玩家路径。
- **无客户端升级**：客户端与 `compiled.code`/`res` 视为当前已部署版本且不会热更新；不考虑版本迁移与向下兼容。
- 当瓶颈与该前提冲突（例如必须多用户压测才能复现），先如实说明，再讨论是否放宽前提。

---

# 目录约定（opencode 工作区）

- workdir 用仓库：`M:\EVE-LOCAL\redmoonrising` 或 `M:\EVE-LOCAL\worktrees\wt-rmr-<task>`；**不要**用 `M:\EVE-LOCAL` 根（约 16 万只读文件，默认搜索会误扫）。
- `M:\EVE-LOCAL\inputs\`：只读输入（客户端/反编译客户端代码/SDE 等），只用绝对路径定向读取。
- `M:\EVE-LOCAL\worktrees\`：并行任务 git worktree；`_archive\`：历史备份/整包；`_scratch\`：临时产物；`mods\`：外部 mod 合并工作目录。
- 客户端目录 `M:\EVE-LOCAL\inputs\EVE-Online-3913`（本项目的唯一客户端）；新版客户端 `EVE-Online-3396210` 与本仓库无关，别混用。
- 仓库内：`crates/`（代码）、`db/`（官方表转储）、`tools/`（本地工具，已被忽略）、`config/`（本地化映射，未跟踪）、`doc/`（文档）。

---

# Shell 环境（PowerShell，强制）

**本工作区 opencode 会话的 shell 是 Windows PowerShell 5.1（实测），不是 Git Bash；命令按 PowerShell 语法写。**

- 路径：`M:\EVE-LOCAL\...` 或 `M:/EVE-LOCAL/...` 都可以；避免裸 `\` 转义问题。
- 常用对照：`ls` → `Get-ChildItem`；`cat` → `Get-Content`；`grep` → `Select-String`；`head -n N` → `Select-Object -First N`；`rm -rf` → `Remove-Item -Recurse -Force`；环境变量 `$env:X`（不是 `$X`）；条件执行用 `;` 或 `if`。
- 需要 POSIX 工具时显式调用 `bash -lc "..."`（Git for Windows 的 `grep`/`sed`/`awk`/`jq` 在 PATH 上，可直接用）。
- `jq` 已安装；`python` 不在 PATH，脚本用基座解释器 `C:\Users\zhang\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe`。
- **读写 UTF-8 文本文件必须指定编码**：PowerShell 5.1 的 `Get-Content`/`Set-Content` 默认按 ANSI（GBK）处理无 BOM 文件，会把中文写成乱码。用 `Get-Content -Encoding UTF8` / `Set-Content -Encoding UTF8`，或 `[IO.File]::ReadAllText($p,[Text.UTF8Encoding]::new($false))`；批量替换优先用编辑工具，不要用 shell 字符串替换。

---

# 工具使用与上下文效率（强制）

**工具输出与来回轮次是上下文膨胀与费用的主因；一切调用只把必要信息带进上下文，并尽量少往返。**

- **少往返**：一轮内**并行批量**发多个独立工具调用（多个 `read`/`grep`/`glob`、多条命令合并），不要串行一个个来。
- **探索交给子代理**：大范围开放式探索/多轮翻找交给 `task`（`explore` 定位、`general` 多步），主会话只收结论。
- **先规划再动手**：动手前列步骤，避免读一步想一步；同一文件/命令不重复读、不重复验证。
- 读取：先 `glob`/`grep` 定位，再用 `read` 的 `offset`/`limit` 只读片段；同一大文件一个会话最多整读一次。大文件典型：`crates/eve-server/src/svc/**`、`bots/**`、`db/*.sql.gz`、`compiled.code`。
- 命令输出：`docker compose logs --tail ≤100` + `Select-String` 只留目标行；数据库查询一律带 `LIMIT`，先聚合再取明细，禁止 `SELECT *` 全表回显；长输出接 `Select-Object -First N`。
- **Rust 构建输出很大**：`cargo build` 只回显末尾错误/警告，成功时只报结论；不要整段回显编译日志。
- 详细判定与流程见 skill `agent-context-efficient-reads`。
