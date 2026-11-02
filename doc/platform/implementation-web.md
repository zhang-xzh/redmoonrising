# Web 仪表盘与无头客户端

服务端有两个不经过游戏客户端的入口，都在 `crates/eve-server` 内：

- **Web 仪表盘**：`src/web.rs` + `web/`（页面源码与编译产物）。手写 HTTP/1.1，只读 JSON + 一个受开关限制的控制接口。
- **fakeclient**：`src/bin/fakeclient.rs`。一个无头 machoNet 客户端，走 LLV 握手、登录、按脚本发 service 调用并断言，是客户端之外最可靠的回归入口。

页面资源在编译期嵌入服务端二进制；fakeclient 的断言脚本在运行时读取。两者都不依赖 3913 客户端进程，也不需要 Node。

## Web 服务实现

### 监听与生命周期

| 项 | 取值 / 行为 | 依据 |
|---|---|---|
| 配置键 | `server.web`，环境变量 `RMR_WEB` | `crates/eve-server/src/config.rs:48`、`config.rs:223` |
| 默认值 | `0.0.0.0:8080` | `crates/eve-server/src/rmr.default.yml:8` |
| 关闭方式 | 地址为空字符串时 `run` 直接返回，不监听 | `crates/eve-server/src/web.rs:42` |
| 启动 | `tokio::spawn(web::run(...))`，与游戏端口 26000 并行 | `crates/eve-server/src/main.rs:121` |
| 绑定失败 | 记 `error!` 后返回，**不影响**游戏服务端继续运行 | `crates/eve-server/src/web.rs:46` |
| 连接模型 | 每个 TCP 连接 `tokio::spawn` 一个任务，错误只记 `debug!` | `crates/eve-server/src/web.rs:54` |
| 运行时长 | 进程内 `OnceLock<Instant>`，web 服务启动时初始化 | `crates/eve-server/src/web.rs:39`、`web.rs:45` |

### 请求解析

`answer()`（`crates/eve-server/src/web.rs:65`）是一个极简 HTTP 服务器：

1. 以 1024 字节块反复读到出现 `\r\n\r\n` 为止（`web.rs:68`）。
2. 累计超过 `MAX_REQUEST = 8 * 1024` 字节即回 `431 Request Header Fields Too Large`（`web.rs:35`、`web.rs:74`）。
3. 只解析请求行：方法、target；target 按第一个 `?` 切出 path 与 query（`web.rs:79`）。
4. **从不读取请求体**，也不解析任何请求头（无 `Host`、`Content-Length`、`Origin` 语义）。
5. 每个响应都带 `Cache-Control: no-store` 与 `Connection: close`，写完即 `shutdown`（`web.rs:139`）。

响应原因短语覆盖 200/400/403/404/405/431，其余状态码一律写 `Internal Server Error`（`web.rs:140`）。

### 路由分发

方法与路径的判定顺序：

1. `POST /api/control` 优先处理（`web.rs:82`）。
2. 其它非 `GET` 请求回 `405`、正文 `Only GET`（`web.rs:96`）。
3. 静态资源与 `/api/*` 在 `match path` 中分派（`web.rs:99`）。
4. 未知 `/api/*` 回 `404 application/json` `{"error":"no such thing"}`；未知非 API 路径回 `404 text/plain` `Not found`（`web.rs:132`、`web.rs:135`）。

静态路由：

| 路径 | Content-Type | 内容来源 |
|---|---|---|
| `/`、`/index.html` | `text/html; charset=utf-8` | `include_str!("../web/index.html")`（`web.rs:30`） |
| `/style.css` | `text/css; charset=utf-8` | `include_str!("../web/style.css")`（`web.rs:31`） |
| `/app.js` | `text/javascript; charset=utf-8` | `include_str!("../web/dist/app.js")`（`web.rs:32`） |

三个文件都在编译期嵌入 `eve-server` 二进制，因此 Docker 镜像不需要 Node，也不需要额外的静态目录挂载。

### 数据转换与错误

- `rows()` 把 PostgreSQL `Row` 按列名转 JSON 对象：`INT2/INT4/INT8`、`FLOAT4/FLOAT8`、`BOOL` 转对应 JSON 类型，其余类型按 `String` 取，取不到或为 NULL 时写 `null`（`web.rs:159`）。
- FILETIME（1601 起 100ns）转 1970 起毫秒：SQL 侧用 `ms()` 拼 `(<col> / 10000 - 11644473600000)::bigint`（`web.rs:183`）；内存数据在 Rust 侧做同样换算（如 `web.rs:214`、`web.rs:226`）。
- 查询失败：记 `warn!` 并输出错误链，返回 `500 {"error":"database"}`，不向客户端泄露 SQL 细节（`web.rs:128`）。
- 内存面板在 bot 模拟第一次存档前是 `Value::Null`（`BotPanels::default`，`crates/eve-server/src/world.rs:119`），所以 `/api/market`、`/api/relations`、`/api/followed`、`/api/events` 初始返回 `null`。

## JSON API 总表

所有 `/api/*` 只接受 `GET`（`/api/control` 例外，只接受 `POST`）。`Limit` 均为代码中写死的上限，没有分页参数。

| 路径 | 方法 | 参数 | 返回结构 | 数据来源 |
|---|---|---|---|---|
| `/api/summary` | GET | — | `{players, bots:{total,online,inSpace,running}, corporations, alliances, wars, lostInFights, systemsHeld, uptimeSeconds}` | `world.players()`、`world.bot_stats`、`count(*) mapSolarSystems WHERE allianceID IS NOT NULL`、`STARTED`（`web.rs:189`） |
| `/api/news` | GET | — | `[{time, text}]`，最新在前 | `world.bot_stats.news`（`web.rs:224`） |
| `/api/sieges` | GET | — | `[{attacker, defender, system, region, security, starts, fighting, attackers, defenders}]`，按 `starts` 升序 | `world.bot_stats.sieges`（`web.rs:206`） |
| `/api/wars` | GET | — | `[{id, declaredBy, declaredByTicker, against, againstTicker, declared, ends, mutual, bots, losses}]` | `crpWars` 左连 `alliances`/`corporation`；`losses` 取自 `bot_stats.war_losses`；`retracted` 过滤，`LIMIT 200`（`web.rs:229`） |
| `/api/players` | GET | — | `[{id, name, corporation, ticker, alliance, security, ship, system, systemSecurity, docked}]` | 在线玩家（`world.players()`）+ `character_`/`corporation`/`alliances`/`entity`/`invTypes`，星系名与安全等级另查 `mapSolarSystems`（`web.rs:262`） |
| `/api/alliances` | GET | — | `[{id, name, ticker, corporations, pilots, kind, region, systems}]` | `alliances` 左连 `corporation`/`botGroups`/`mapRegions`，`kind` 由 `botGroups.kind` 映射；按 `pilots` 降序 `LIMIT 60`（`web.rs:298`） |
| `/api/corporations` | GET | — | `[{id, name, ticker, members, alliance, bots}]` | `corporation` 左连 `alliances`；排除 `crpNPCCorporations`；按成员数降序 `LIMIT 40`（`web.rs:314`） |
| `/api/systems` | GET | — | `[{id, name, security, region, inSpace, docked}]` | 内存中在太空/停靠人数合并排序取前 30，再查 `mapSolarSystems`+`mapRegions`（`web.rs:326`） |
| `/api/kills` | GET | — | `[{id, time, victim, victimCorporation, ship, system, finalBlow, pod}]` | `killLog` 左连角色/公司/`invTypes`/星系，按 `killID` 降序 `LIMIT 30`（`web.rs:422`） |
| `/api/killboard` | GET | — | `{total, sides:[{id,name,ticker,kills,losses,bots}], ships:[{ship,lost}]}` | 最近 24h `killLog`/`killLogParticipants` 聚合；`ships` 为损失船型前 10；`sides` `LIMIT 30`（`web.rs:393`） |
| `/api/market` | GET | — | 经济面板对象或 `null`（见下） | `world.bot_panels.market`（`web.rs:115`），由 `bots/panels.rs:64` 生成 |
| `/api/relations` | GET | — | `{standings:[{side,player,heat,favor,flags}], wingmen:[{bot,player,rate,system}], hunting, grudges}` 或 `null` | `world.bot_panels.relations`（`web.rs:116`、`bots/panels.rs:103`） |
| `/api/followed` | GET | — | `[{id,name,role,corporation,alliance,ship,tier,isk,online,activity,system,security,station,history:[{time,text}]}]` 或 `null` | `world.bot_panels.followed`（`web.rs:117`、`bots/panels.rs:133`） |
| `/api/events` | GET | — | `{raids:[{system,raiders,kills,lost}], log:[{time,text}], said:[{time,text}], controls}` 或 `null` | `world.bot_panels.events`（`web.rs:118`、`bots/panels.rs:160`、`bots/mod.rs:787`） |
| `/api/pilots` | GET | `q`（名称片段；去空白转小写，少于 2 字符返回空） | `[{id, name}]`，最多 15 条 | 内存 `world.bot_roster` 名称匹配（`web.rs:378`） |
| `/api/control` | POST | `do`（见下节） | 成功 `{ok}`；失败 `{error}` | `bots::request`（`web.rs:82`） |

补充说明：

- `/api/market` 的对象字段：`minedM3, refinedUnits, hauledM3, hullsBuilt, hullsBought, hullsFromNpcs, soldToPlayers, boughtFromPlayers, playerOrdersFilled, orders, corpTax, hubs:[{station,worth,goods:[{name,kind,stock,ask,bid,npcAsk}]}], shortages:[{name,wanted}], log`（`bots/panels.rs:95`）。`hubs` 按库存价值降序，每个 hub 最多 24 行货物。
- `time`、`starts`、`declared`、`ends` 均为 1970 起毫秒，前端用 UTC 渲染；`security` 在内存面板中四舍五入到一位小数，`/api/systems` 在 SQL 里 `round(...,1)`。

## 写操作与控制面

`POST /api/control` 是仪表盘唯一会改变世界状态的入口，实际只是**入队**，由 bot 模拟下一次 tick 取走（`crates/eve-server/src/bots/control.rs:27`）。

处理流程（`crates/eve-server/src/web.rs:82`）：

1. 从 query 找 `do=`，用 `decode` 做 URL 解码（`+` → 空格，`%XX` → 字节；`web.rs:354`）。
2. `bots::controls_enabled()` 为假：回 `403 {"error":"Dashboard controls are off (bots.dashboardControls in rmr.yml)."}`（`web.rs:85`）。
3. 按空白切词，交给 `bots::request(&words)`（`web.rs:88`、`bots/mod.rs:101`）。
4. 解析成功：`200 {"ok": "..."}`，`ok` 是"已受理"的描述，不代表动作已执行完；解析失败：`400 {"error": "..."}`。

动作语法（`crates/eve-server/src/bots/control.rs:41`，首词大小写不敏感）：

| `do=` 形式 | 解析结果 | 约束 |
|---|---|---|
| `event raid` | `Request::Event(Raid)` | `events::Kind::parse` 还接受 `invasion`、`invade` 作为 raid 别名（`bots/events.rs:52`） |
| `event betrayal` | `Request::Event(Betrayal)` | 也接受 `betray` |
| `event merger` | `Request::Event(Merger)` | 也接受 `merge` |
| `event collapse` | `Request::Event(Collapse)` | — |
| `event coalition` | `Request::Event(Coalition)` | — |
| `war <A> \| <B>` | `Request::War(A, B)` | 必须含 `\|`，两侧去首尾空白；接受联盟/公司的名称、ticker 或 ID |
| `density <region> <factor>` | `Request::Density(region, f32)` | 用最后一个空格切分区域与倍率；倍率 `clamp(0.0, 5.0)` |
| `follow <name>` | `Request::Follow(name)` | 名称非空；接受名称或角色 ID |
| `unfollow <id>` | `Request::Unfollow(i64)` | 必须是整数角色 ID |

开关链路：

| 层 | 位置 | 说明 |
|---|---|---|
| `rmr.yml` | `bots.dashboardControls`，默认 `false`（`rmr.default.yml:59`） | 开启后仪表盘可操纵 bot |
| 环境变量 | `RMR_BOTS_CONTROLS`（`config.rs:234`） | 覆盖配置文件 |
| 启动注入 | `bots::configure(..., config.bots_controls)`（`main.rs:119`） | 写入 `AtomicBool CONTROLS`（`bots/mod.rs:90`） |
| 请求期读取 | `controls_enabled()`（`bots/mod.rs:95`） | 关闭时只读接口仍可用 |

权限与校验：**没有身份认证、没有 CSRF token、没有来源检查**；安全性完全依赖 `RMR_WEB` 的监听范围。校验只到语法层：`war` 的两侧是否存在、`follow` 的名字能否匹配到 bot，都由模拟 tick 自行处理，失败只写入仪表盘的 `said` 日志，不会作为 HTTP 错误返回（`bots/mod.rs:678`、`bots/mod.rs:720`）。

## 前端

### 源码结构

| 文件 | 作用 |
|---|---|
| `crates/eve-server/web/index.html` | 页面骨架：顶部 neocom 导航（14 个锚点）、`main.desktop` 下 14 个 `.window`、EVE 时间时钟 |
| `crates/eve-server/web/style.css` | 2006 客户端风格：灰玻璃窗口、Tahoma 小字、大写标题、星空/星云背景、安全等级配色 |
| `crates/eve-server/web/src/app.ts` | 唯一脚本，ES module，约 637 行；类型定义、列表渲染、轮询与交互 |
| `crates/eve-server/web/dist/app.js` | `tsc` 输出，随源码提交，被 `include_str!` 嵌入服务端 |
| `crates/eve-server/web/package.json` | `"build": "tsc"`，开发依赖 `typescript ^5.6.0` |
| `crates/eve-server/web/tsconfig.json` | `target/module ES2020`、`strict`、`noEmitOnError`、`noUnusedLocals`、`rootDir src`、`outDir dist`、`removeComments false` |

`index.html:8` 以 `<script type="module" src="/app.js">` 加载脚本，因此 `dist/app.js` 必须保持 ES module 语义（不能改成 IIFE 打包而不改 HTML）。

### 轮询与渲染

- 轮询间隔 `REFRESH_MS = 15_000`（`web/src/app.ts:164`）；页面启动立即 `refresh()` 一次，然后每 15 秒一次（`app.ts:636`）。
- `refresh()` 用 `Promise.all` 并发取 9 个接口：`summary, wars, players, systems, alliances, corporations, kills, news, sieges`（`app.ts:322`）；随后 `refreshBots()` 再并发取 `killboard, market, relations, followed, events`（`app.ts:414`）。
- 任一次失败都会把状态栏改成 `Status: unreachable, retrying (...)`，下一轮继续重试（`app.ts:401`）。
- `get()` 统一 `fetch(..., { cache: "no-store" })`，非 2xx 抛错（`app.ts:167`）。
- 表格由通用 `list()`/`draw()` 生成：列定义含标题、排序键、单元格；点击表头切换排序列与升降序，排序状态存于 `Map`，重绘不丢（`app.ts:219`、`app.ts:231`）。
- 视觉辅助：`SECURITY_COLOURS` 按 1.0→-1.0 映射颜色（`app.ts:186`）；`eveTime()` 用 UTC 输出 `YYYY.MM.DD HH:MM`（`app.ts:198`）；ISK 用 `Intl.NumberFormat` compact 格式。

### 页面区块

| 窗口 id | 标题 | 内容 | 数据接口 |
|---|---|---|---|
| `w-status` | Server Status | 在线人数、bot 总数/在线/在太空、公司/联盟/战争数、战损、主权星系数、运行时长 | `/api/summary` |
| `w-wars` | War Report | 宣战方/应战方、时间、战损、类型 | `/api/wars` |
| `w-pilots` | Pilots Online | 玩家、公司/联盟、星系与安全等级、船 | `/api/players` |
| `w-systems` | Busiest Systems | 星系、区域、在太空/停靠/合计 | `/api/systems` |
| `w-alliances` | Alliances | 联盟、占据区域、公司数、人数、星系数 | `/api/alliances` |
| `w-corporations` | Corporations | 公司、联盟、成员数 | `/api/corporations` |
| `w-sieges` | Sieges | 星系、攻守双方、开战时间或 `BATTLE n vs m` | `/api/sieges` |
| `w-news` | Galactic News | 时间、事件文本 | `/api/news` |
| `w-kills` | Kill Reports | 时间、受害者、船、星系、最后一击 | `/api/kills` |
| `w-killboard` | Killboard (24h) | 24h 总损失、联盟/公司击杀与损失、船型损失榜 | `/api/killboard` |
| `w-market` | Market | hub 下拉、产出/贸易汇总、货物库存与买卖价、短缺 | `/api/market` |
| `w-relations` | Standings | 各方对玩家的热度/好感/标记、雇佣的 wingman | `/api/relations` |
| `w-follow` | Follow a Pilot | 搜索框、被跟踪飞行员、该飞行员的历史 | `/api/followed`、`/api/pilots` |
| `w-control` | Events and Controls | 事件按钮、开战表单、区域密度表单、控制开关提示、raid/事件日志 | `/api/events`、`POST /api/control` |

交互细节：

- 每个窗口的 `_` 按钮切换 `minimized` 类（`app.ts:630`）。
- 时钟每秒刷新，显示 UTC 时分与日期（`app.ts:624`）。
- hub 下拉切换只重绘本地缓存的市场表，不再请求（`app.ts:603`）。
- 飞行员搜索输入去抖 250ms，少于 2 字符清空结果（`app.ts:604`）。
- 控制按钮/表单调用 `control(what)`，POST 后 1.5 秒再 `refresh()`；`data-do` 直接作为 `do` 值（`app.ts:562`、`app.ts:608`）。
- `events.controls` 为假时，控制窗口所有按钮 `disabled`，并提示去改 `bots.dashboardControls`（`app.ts:475`）。

### 构建方式

```powershell
cd crates/eve-server/web
npm install          # 首次，装 typescript ^5.6
npm run build        # tsc -> dist/app.js
```

- 只有 `tsc`，没有打包器、没有 source map、没有 watch 脚本；`noEmitOnError` 保证类型错误时不产出。
- `dist/app.js` **随源码提交**：`cargo build` 只读该文件，不需要 Node；改了 `app.ts` 必须重新 build 并一起提交，否则服务端仍嵌入旧脚本。
- 服务端侧是编译期 `include_str!`（`web.rs:32`），所以改前端也要重建 `eve-server` 二进制/镜像才生效。

## fakeclient

`crates/eve-server/src/bin/fakeclient.rs` 是一个同步、单线程的 machoNet 客户端：普通 `TcpStream` + `FrameReader`，复用 `eve-proto` 与 `eve-marshal`。

### 命令行

| 参数 | 默认 | 说明 |
|---|---|---|
| 第 1 个位置参数 `addr` | `127.0.0.1:26000` | 服务端地址 |
| 第 2 个位置参数 `user` | `testuser` | 账号 |
| 第 3 个位置参数 `password` | `testpass` | 密码 |
| `--script <file>` / `--script=<file>` | 无 | 载入断言脚本；两种写法都支持 |
| `--no-cache` | 关 | 跳过登录后缓存对象拉取 |
| 其它 `--*` | — | 直接报 `unknown flag`；位置参数超过 3 个也报错 |

解析见 `crates/eve-server/src/bin/fakeclient.rs:141`。环境变量：

- `RMR_STRINGS`：共享字符串表路径，默认 `crates/eve-marshal/tests/data/strings.txt`（`fakeclient.rs:27`）。必须与服务端使用同一份表，否则 marshal 解出的字符串会错位。
- `FAKECLIENT_FULL=1`：每次成功调用额外打印完整 `Value` 调试结构（`fakeclient.rs:92`）。

### 连接、LLV 握手与登录

| 阶段 | 行为 | 依据 |
|---|---|---|
| 连接 | `TcpStream::connect`，开启 `nodelay`，打印 `connected to ...` | `fakeclient.rs:34` |
| 收挑战 | 30 秒内收 `VersionChallenge`，否则报 `no LLV challenge from the server` | `fakeclient.rs:39` |
| 校验 | `validate()` **只校验** `magic` 与 `macho_version`；build/codename 仅打印、不比对 | `fakeclient.rs:40` |
| 回挑战 | 发送 `VersionChallenge::client()` | `fakeclient.rs:51` |
| 登录 | 发 `AuthenticationReq`，body 为 `clientinfo` 字典（`version.number`、`version.build`、`version.project`、`languageID="EN"`）+ 用户名 + 密码 | `fakeclient.rs:536` |
| 登录响应 | 打印 `serverinfo`、`userID`、`role`、`proxyNodeID`；解出第 4 个字段里的 initvals 字典；记录 `user_id` 供后续包使用 | `fakeclient.rs:575` |
| 空闲确认 | 登录后持续清空推送，直到 1.5 秒无新流量（`IDLE`），打印 `(no further traffic ...)` | `fakeclient.rs:11`、`fakeclient.rs:566` |
| 失败 | 无 `AuthenticationRsp` 或无 initvals → `the AuthenticationRsp carried no initvals -- login failed` | `fakeclient.rs:569` |

### 缓存对象

登录响应的 initvals 里每个句柄若是 `util.CachedObject`，默认会逐个调用 `objectCaching.GetCachableObject`，把返回的 pickle 做 `decompress` 后再 `eve_marshal::load` 验证，最后打印 `cached objects: ok/total decoded, X MB`（`fakeclient.rs:606`）。

`--no-cache` 时完全不发这些调用，只打印 `(skipping N cached objects: --no-cache)`（`fakeclient.rs:56`）。它适合只验证 service 调用、不想花时间拉大对象的场景；代价是没有验证缓存数据本身能否解码。

### 登录后的固定调用

无论有没有脚本，都会依次执行（`fakeclient.rs:62`）：

1. `authentication.Ping`
2. `authentication.GetPostAuthenticationMessage`
3. `character.GetCharactersToSelect`

角色选择：脚本里的 `!char <id>` 优先；否则取 `GetCharactersToSelect` 返回 rowset 的第一行 `characterID`；两者都没有则打印提示、不进游戏（`fakeclient.rs:67`）。选中后调用 `character.SelectCharacterID(id)`。

### 脚本语法

`parse_script`（`fakeclient.rs:192`）逐行解析，空行与 `#` 开头行忽略。

| 形式 | 含义 |
|---|---|
| `!char <id>` | 指定要登录的角色 ID（十进制整数）；全脚本最后一次生效 |
| `!sleep <seconds>` | 累计暂停秒数，作用在**下一条调用之前**；若出现在末尾，则作为最后调用后的 `final_pause` |
| `!<其它>` | 报错 `unknown directive` |
| `?service.Method ...` | 期望该调用被拒绝（`ErrorResponse`） |
| `service.Method ...` | 普通调用；`service`/`method` 都不能为空，缺 `.` 报 `expected service.method` |

参数是自定义字面量语法（`Literal`，`fakeclient.rs:237`）：

| 字面量 | 结果 |
|---|---|
| `"text"` | `Bytes`；支持 `\n`、`\t`、`\r`，其它 `\x` 取 `x` 本身（含 `\"`） |
| `123`、`-5` | `Int` |
| `1.5`、`1e3` | `Double`（token 含 `.`/`e`/`E`） |
| `none` / `None` | `None` |
| `true` / `True`、`false` / `False` | `Bool` |
| `[a, b]` | `List` |
| `(a, b)` | `Tuple` |
| `{"k": v}` | `Dict` |
| `name=value` | 顶层 kwargs；名字须为字母/数字/下划线且不以数字开头 |
| 裸词 | 报错 `unknown literal ... (strings need quotes)` |

注意 `"a=b"` 是普通字符串参数，不会被当作 kwarg（测试见 `fakeclient.rs:890`）。

### 断言、输出与退出码

每条脚本调用都会打印 `ok` / `FAIL` 与行号：

| 情况 | 判定 |
|---|---|
| 收到 `CallRsp` 且未标 `?` | `ok`，打印返回值摘要 |
| 收到 `ErrorResponse` 且标了 `?` | `ok ... refused, as expected` |
| 收到正常返回但标了 `?` | `FAIL ... answered, but the script expects a refusal` |
| 收到 `ErrorResponse` 但没标 `?` | `FAIL ... refused: ...` |
| 30 秒内无匹配回复 | `FAIL ... no reply within 30s` |
| 回复无法 unmarshal / body 形状不对 | `FAIL ... no usable reply` |

（`fakeclient.rs:88`、`CALL_TIMEOUT = 30s` 见 `fakeclient.rs:13`。）

收尾会等最多 500ms 的静默期，把期间到达的通知打印出来（`TRAILING`，`fakeclient.rs:15`、`fakeclient.rs:123`）。最后打印 `N call(s), X ok, Y failed`；**只要有一条 FAIL 就以退出码 1 结束**，否则 0（`fakeclient.rs:125`）。参数错误、连接失败、脚本语法错误、LLV 校验失败、登录失败等都以 `Err(String)` 从 `main` 返回，同样是非零退出。

等待期间收到的非应答包由 `show_unsolicited` 打印（`fakeclient.rs:810`）：

- `SessionChangeNotification`：逐条打印属性名与旧值 → 新值。
- `Notification`：打印 broadcast id 和嵌套后的参数。
- `ErrorResponse`：打印错误类名、消息与字典参数。

### 典型脚本

```text
# 冒烟：进游戏并确认基础服务
!char 140000001
authentication.Ping
authentication.GetPostAuthenticationMessage
character.GetCharactersToSelect
!sleep 3
```

`!sleep 3` 在最后一条调用之后生效，用来观察 3 秒内的推送（session change、通知等）。具体 service/method 名以 `crates/eve-server/src/services.rs` 的注册表为准；脚本里写错方法名会得到 `ErrorResponse`，从而计为 FAIL。

## 验证用法

### fakeclient 回归

```powershell
# 最短连通性检查（默认 testuser/testpass，只走握手 + 登录 + 固定调用）
cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000

# 带断言脚本（脚本内容自行编写）
cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000 --script .\my.script

# 自定义账号，并跳过缓存对象
cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000 root root --no-cache

# 打印完整返回结构，便于写断言
$env:FAKECLIENT_FULL=1; cargo run -p eve-server --bin fakeclient -- 127.0.0.1:26000 --script .\my.script
```

判定标准：输出末尾 `N call(s), N ok, 0 failed` 且进程退出码 0。适合放进脚本做提交前回归；`--no-cache` 可用于快速迭代 service 层，正式回归应至少跑一次不带 `--no-cache` 的版本，确认缓存对象仍可解码。

### Web 接口回归

```powershell
# 只读接口
Invoke-RestMethod http://127.0.0.1:8080/api/summary
Invoke-RestMethod http://127.0.0.1:8080/api/wars
Invoke-RestMethod "http://127.0.0.1:8080/api/pilots?q=an"

# 控制接口（需 bots.dashboardControls: true，改后重启服务端）
Invoke-RestMethod -Method Post "http://127.0.0.1:8080/api/control?do=event+raid"
Invoke-RestMethod -Method Post "http://127.0.0.1:8080/api/control?do=war+Black+Legion+%7C+Red+Pact"

# 负向检查：关闭控制时应为 403；GET 控制接口应为 404；错误方法应为 405
```

页面本身：浏览器打开 `http://127.0.0.1:8080/`，确认各窗口能正常渲染（bot 面板首次存档前对应窗口为空）、状态栏不是 `unreachable`、点击表头可排序、`CTL` 窗口根据 `events.controls` 正确禁用按钮。改前端后先 `npm run build`，再重建/重启服务端（客户端在运行时禁止重启，见 `AGENTS.md`）。

## 已知限制

- **无认证、无 TLS、无 CSRF 防护，且控制开关是全局的**：任何能访问 8080 的人都能读全部数据；`bots.dashboardControls` 一旦打开，对所有访问者都能操纵 bot。只应监听本机或可信网络。
- **HTTP 实现极简**：不支持 keep-alive、请求体、分块传输、HTTP/2、压缩、条件请求；只认请求行，路径区分大小写；8 KB 头部上限。
- **控制接口是异步受理**：`200 {ok}` 只表示入队成功，动作在下一次模拟 tick 才生效；名称/ID 找不到不会在 HTTP 层报错。
- **面板数据有快照延迟，列表上限写死**：`/api/market`、`/api/relations`、`/api/followed`、`/api/events` 来自模拟每轮存档时写入的快照，首次存档前为 `null`，前端按 `null` 跳过渲染；wars 200、alliances 60、corporations 40、systems 30、kills 30、killboard sides 30 / ships 10、market 每 hub 24 行、followed 最多 12 人、每人历史 60 条、搜索 15 条，均无分页。
- **数据库错误被折叠**：统一 `500 {"error":"database"}`，客户端无法区分连接失败、SQL 错误或数据缺失。
- **fakeclient 只验证协议面，且有运行约束**：不模拟 ballpark 内的移动与战斗，也不覆盖客户端 UI；`RMR_STRINGS` 必须与服务端一致，对不上时表现为 unmarshal 失败而非明确的版本错误；所有调用依次等待回复，单次 30 秒超时，不能并发压测，也不会自动重连，等待期间只打印通知、不做断言。
- **脚本字面量是子集**：没有变量、表达式、循环、include；裸词必须是引号字符串；`!sleep` 只能累加到下一条调用，不能插在调用之间做精确时序控制。
- **前端产物需手工同步**：没有 `build.rs` 或 npm 构建钩子，忘记提交 `dist/app.js` 会让服务端继续提供旧脚本；`tsconfig` 也未生成 source map。
