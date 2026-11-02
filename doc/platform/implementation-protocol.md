# 协议与传输实现
范围：本文说明 RMR 服务端当前实际使用的那一层协议——EVE marshal 值编码、LLV 版本握手、machoNet 帧与包、服务调用解析与分发、bulk data 缓存对象，以及连接生命周期。只描述代码里已经成立的行为；客户端侧的协议细节（`compiled.code` 里的 pyMarshalStream 等）不在本文范围内。文中行号对应当前仓库快照。

## 分层与模块地图
| 文件 | 职责 |
|---|---|
| `crates/eve-marshal/src/value.rs` | `Value` 值模型：Python 侧的 None/bool/int/long/str/unicode/tuple/list/dict 以及 Blue 扩展对象，附取值辅助方法 |
| `crates/eve-marshal/src/ser.rs` | marshal 编码器：选最窄的整数标签、字符串表引用、元组/列表的短标签、UCS2/UTF-8 unicode |
| `crates/eve-marshal/src/de.rs` | marshal 解码器：5 字节头 + 末尾共享表、共享引用、CHECKSUM 标签、深度与长度防护 |
| `crates/eve-marshal/src/strings.rs` | 客户端共享字符串表（最多 255 条，1 基索引） |
| `crates/eve-marshal/src/error.rs` | marshal 错误枚举与 `Display` |
| `crates/eve-proto/src/frame.rs` | 4 字节长度前缀帧、zlib 压缩判定、帧长上限 |
| `crates/eve-proto/src/llv.rs` | LLV 常量、`VersionChallenge`、关闭原因文本 |
| `crates/eve-proto/src/packet.rs` | `MessageType`、`MachoPacket` 及包体 arity 校验、oob |
| `crates/eve-proto/src/address.rs` | `MachoAddress` 的四种地址形态与 marshal 互转 |
| `crates/eve-proto/src/lib.rs` | payload 编解码入口：解压 → marshal，特殊识别客户端的关闭原因 |
| `crates/eve-server/src/conn/mod.rs` | 单连接循环：select 读帧/通知队列、分发、回包、错误帧落盘、断线清理 |
| `crates/eve-server/src/conn/auth.rs` | LLV 握手、`AuthenticationReq`、账号校验、登录返回体 |
| `crates/eve-server/src/services.rs` | `Call` 解析、`Ctx`、`Handler`/`Registry`、bound 服务分发、`Outcome` |
| `crates/eve-server/src/bulkdata.rs` | `SPECS`、启动时加载 bulk 对象、CRC/版本、压缩、`util.CachedObject` 载荷 |
| `crates/eve-server/src/exceptions.rs` | 客户端可反序列化的 `UserError` / `ServiceNotFound` |
| `crates/eve-server/src/svc/bound.rs` | bound 对象 ID 的拼装/解析、`CallbackObject` 引用、piggyback 调用 |
| `crates/eve-server/src/svc/rows.rs` | `util.Row`/`util.Rowset`/`util.IndexRowset`/`util.KeyVal` 构造与 PostgreSQL 单元格转换 |

## marshal 值模型与编解码
### Value 变体与用途

`Value` 是唯一的中间表示，既用于解析客户端请求，也用于构造回包（`crates/eve-marshal/src/value.rs:1-24`）。

| 变体 | 对应客户端类型 | 服务端用途 |
|---|---|---|
| `None` / `Bool` / `Int` / `Long` / `Double` | NoneType、bool、int、long、float | 参数与返回值 |
| `Bytes` | `str` | ASCII 文本、对象 ID、marshal 子块、字节串 |
| `Unicode` | `unicode` | 非 ASCII 文本（中文等） |
| `Buffer` | `buffer` | 二进制数据；与 `Bytes` 在取值时通常等价 |
| `Tuple` / `List` / `Dict` | tuple/list/dict | 调用参数、rowset 行列、session 变更 |
| `Global` | 模块全局名 | 少见，仅解码保留 |
| `Instance { class, state }` | 任意 Python 实例 | `util.Rowset`、`util.Row`、`ccp_exceptions.UserError`、`macho.*` 包 |
| `CallbackObject` | callback 对象 | bound 对象引用（内含一段 marshal 字节） |
| `BlueObject` / `MarshalStream` | Blue 对象 / 嵌套 marshal 流 | 解码保留；调用里的二层 payload 也用 `MarshalStream` 承载 |
| `Pickle` | 原始 pickle | 非 marshal 数据的兜底 |
| `Marker` | marshal MARK | 仅编解码保留，服务端不构造 |

文本选择由 `Value::text` 决定：ASCII 走 `Bytes`（客户端按 `str` 读），非 ASCII 走 `Unicode`，避免 UTF-8 字节被客户端当 `str` 显示成乱码（`crates/eve-marshal/src/value.rs:35-44`）。`Value::get_str` 只按 `Bytes` 键查 dict，所以服务端构造的 dict 键统一用 `Value::bytes(...)`（`crates/eve-marshal/src/value.rs:81-83`）。

### 编码规则要点

编码器构造时就写入 5 字节头 `~` + 4 字节小端 mapcount（当前固定 0，即不产出共享表），之后顺序写根对象（`crates/eve-marshal/src/ser.rs:13-15`、`crates/eve-marshal/src/lib.rs:13-15`）。

1. 整数按值选最窄标签：`-1/0/1` 用专用标签，其次 `INT8`、`INT16`、`INT32`、`INT64`；`Value::Long` 无论大小一律 `INT64` + 8 字节小端（`crates/eve-marshal/src/ser.rs:52-76`）。
2. `Double` 的正零写成 `DOUBLE_0`，其余 `DOUBLE` + 8 字节小端（`crates/eve-marshal/src/ser.rs:78-85`）。
3. 字符串优先查共享表，命中写 `STRING_TABLE` + 1 字节索引；否则按空串/单字符/<256/长串分档，长串用 `extsize`（1 字节，≥0xFF 时写 `0xFF` + 4 字节小端长度）（`crates/eve-marshal/src/ser.rs:163-181`、`crates/eve-marshal/src/ser.rs:29-36`）。
4. `Unicode` 先转 UTF-16 码元：空/单码元用短标签，多码元时比较 UTF-8 字节数与 UCS2 字节数，UTF-8 更短则 `UNICODE_UTF8`，否则 `UNICODE_UCS2`（`crates/eve-marshal/src/ser.rs:183-205`）。
5. `Tuple` 0/1/2 个元素用 `TUPLE_0/1/2`，`List` 0/1 个用 `LIST_0/1`，其余用通用标签 + `extsize`（`crates/eve-marshal/src/ser.rs:95-121`）。
6. `Dict` 写 `DICT` + 对数，然后每对先 **value 后 key**（与 Python marshal 一致），解码端同样按 value→key 读（`crates/eve-marshal/src/ser.rs:122-129`、`crates/eve-marshal/src/de.rs:242-252`）。
7. 扩展类型：`INSTANCE` 写 class 再写 state；`BLUE_OBJECT`/`MARSHAL_STREAM` 写长度 + 原始字节；`CALLBACK_OBJECT` 写一个子值；`PICKLE` 用 `PICKLE_REST` 直接写到流尾（`crates/eve-marshal/src/ser.rs:131-158`）。
8. 编码深度超过 `MAX_DEPTH = 64` 返回 `DepthLimit`（`crates/eve-marshal/src/ser.rs:42-45`、`crates/eve-marshal/src/lib.rs:15`）。
9. 编码器不会产出 `CHECKSUM`、`REFERENCE`、`PICKLE_SIZED`、`DBROW` 与共享标志位；这些只在解码侧支持。

### 解码容错与限制

- 头部不足 5 字节报 `UnexpectedEof`；mapcount × 4 超出缓冲区报 `TooLittleData`；共享表项为 0 或超过 mapcount 报 `BogusMap`（`crates/eve-marshal/src/de.rs:21-40`）。
- 标签低 6 位是类型，`0x40` 位表示“该对象随后占用一个共享槽”；`CHECKSUM` 标签先读 4 字节并记录 `crc/had_crc`，不产生值（`crates/eve-marshal/src/de.rs:119-128`、`crates/eve-marshal/src/de.rs:16-17`）。
- `INSTANCE` 的共享槽在 class 之后、state 之前分配，且先放 `None` 占位，避免自引用死循环（`crates/eve-marshal/src/de.rs:130-142`）。
- `STRING_TABLE` 索引查不到时退化为空字节串而不是报错（`crates/eve-marshal/src/de.rs:194-198`）。
- `DBROW`（0x2A）明确不支持，报 `UnsupportedTag`；0x22/0x23 同样报“语义未恢复”（`crates/eve-marshal/src/de.rs:288-300`）。
- 集合长度读取后先 `guard_count`，元素数不得超过剩余可读字节数，避免按伪造长度巨量分配（`crates/eve-marshal/src/de.rs:307-321`）。
- `root()` 读完根对象后若仍有剩余字节，报 `TrailingData`（`crates/eve-marshal/src/de.rs:102-108`）。
- 顶层入口 `load`：首个字节不是 `~` 时不报错，而是把整段数据包成 `Value::Pickle`，供上层决定（`crates/eve-marshal/src/de.rs:324-329`）；`load_with_crc` 额外返回是否出现过 CHECKSUM（`crates/eve-marshal/src/de.rs:331-337`）。

### 共享字符串表

`StringTable::parse` 按行切分、去掉行尾 `\r`、丢弃末尾空行，最多登记 255 条；索引 1 基，索引 0 表示“无”，重复字符串保留第一次出现的索引（`crates/eve-marshal/src/strings.rs:3`、`crates/eve-marshal/src/strings.rs:16-37`、`crates/eve-marshal/src/strings.rs:47-56`）。服务端启动时从 `config.strings` 读入，默认路径是 `crates/eve-marshal/tests/data/strings.txt`（`crates/eve-server/src/main.rs:66-71`、`crates/eve-server/src/config.rs:188`）。

## LLV 握手与登录
### 常量

| 常量 | 值 | 位置 |
|---|---|---|
| `LLV_MAGIC` | `170472` | `crates/eve-proto/src/llv.rs:4` |
| `MACHO_VERSION` | `139` | `crates/eve-proto/src/llv.rs:6` |
| `BOOT_VERSION` | `2.1`（f64） | `crates/eve-proto/src/llv.rs:8` |
| `BOOT_BUILD` | `3913` | `crates/eve-proto/src/llv.rs:10` |
| `BOOT_CODENAME` | `b"Blood"` | `crates/eve-proto/src/llv.rs:12` |
| `MAX_CLIENT_LLV_BYTES` | `1000` | `crates/eve-proto/src/llv.rs:14` |
| `LLV_TIMEOUT_SECS` | `120` | `crates/eve-proto/src/llv.rs:16` |

`LLV_TIMEOUT_SECS` 目前在服务端没有引用点，握手与读取都没有实际超时（全仓仅定义处出现）。

### 时序

1. 连接进入 `serve` 前先跑 `handshake`；服务器主动把 `VersionChallenge::server(online_count)` marshal 后作为一帧发出，客户端此时还没发过任何数据（`crates/eve-server/src/conn/auth.rs:17-21`）。
2. challenge 是 6 元组 `(magic, macho_version, user_count, boot_version, boot_build, codename)`；`user_count` 取 `world.online_count()`，即在线玩家 + 在线 bot（`crates/eve-proto/src/llv.rs:44-53`、`crates/eve-server/src/world.rs:241-245`）。
3. 客户端回一帧自己的 6 元组；帧长超过 1000 字节直接以关闭原因挂断（`crates/eve-server/src/conn/auth.rs:22-29`）。
4. 解析后调用 `validate`：`magic` 必须等于 `LLV_MAGIC`，`macho_version` 必须等于 `MACHO_VERSION`，否则发关闭原因并断开（`crates/eve-proto/src/llv.rs:78-88`、`crates/eve-server/src/conn/auth.rs:31-45`）。
5. 握手成功后进入 `serve` 的主循环，客户端下一条才是 `AuthenticationReq`（`crates/eve-server/src/conn/mod.rs:126-131`）。

### 登录请求与校验

`AuthenticationReq` 允许 3 或 4 元包体（`crates/eve-proto/src/packet.rs:92`）。服务端取：

- `body[0]`：clientinfo dict（版本、语言）；
- `body[1]`：用户名；
- `body[2]`：密码；字符串按 `Unicode` 或逐字节 `char` 读取（`crates/eve-server/src/conn/auth.rs:54-57`、`crates/eve-server/src/conn/auth.rs:156-162`）。

版本校验（`crates/eve-server/src/conn/auth.rs:134-153`）：

1. `version.number` 必须是 `Double(2.1)`，整数 2 也不行；
2. `version.project` 必须等于 `b"Blood"`；
3. `version.build` 必须存在且 `>= 3913`（允许更高 build）。

失败时先回一个 `VersionMismatch` 的 `UserError`（`srv="Blood 2.1(3913)"`、`cli=具体原因`），再发关闭原因并断开（`crates/eve-server/src/conn/auth.rs:59-69`）。账号查询失败回 `AutClusterStarting` 并断开；账号不存在/密码不符回 `LoginAuthFailed`，但连接保留（`crates/eve-server/src/conn/auth.rs:71-82`）。

### 登录返回体

成功时（`crates/eve-server/src/conn/auth.rs:84-113`）：

1. `session.user_id`、`session.role = ROLE_LOGIN | ROLE_PLAYER | account.role`、`session.address`、`session.language_id`（缺省 `"EN"`）写入；
2. `authenticated = true`，之后 `dispatch` 会给每个入站包补 `user_id`（`crates/eve-server/src/conn/mod.rs:195-197`）；
3. 预生成登录用的 session change，暂存在 `pending_session_change`，**不立即发送**（`crates/eve-server/src/conn/auth.rs:98`）；
4. `AuthenticationRsp` 包体 5 元：`server_info` dict、`accountID`（Int）、`role`（Long）、`Bytes(payload)`、`node_id`（Int），其中 `payload` 是另一层 marshal，内容为 `(bulk.init_vals(), service_info())`；`service_info()` 目前是空 dict（`crates/eve-server/src/conn/auth.rs:100-111`、`crates/eve-server/src/bulkdata.rs:353-355`）。

### session change 的延迟释放

登录时生成的 session change（`session.change_body()` = `[(0, {变量: (旧, 新)}), []]`，见 `crates/eve-server/src/session.rs:141-146`、`crates/eve-server/src/session.rs:126-139`）要等客户端 `ConnectToServer` 返回后才发。释放条件是：任意一个 **非 `objectCaching`** 的服务调用处理完毕（`crates/eve-server/src/conn/mod.rs:293`、`crates/eve-server/src/conn/mod.rs:368-375`）。因此客户端登录后连续拉取 bulk 缓存对象不会提前触发 session change。后续移动/选角触发的是 `send_session_change_from`，按前后 session 差异即时发送（`crates/eve-server/src/conn/mod.rs:409-413`）。

## machoNet 帧与包
### 帧布局

```
+--------------------+---------------------------+
| u32 LE 长度 (N)    | N 字节 payload            |
+--------------------+---------------------------+
```

长度前缀固定 4 字节（`crates/eve-proto/src/frame.rs:7`）。payload 有两种形态：首字节为 `~`（0x7E）表示裸 marshal；否则视为 zlib 流，解压后必须以 `~` 开头，否则报 `BadCompression`（`crates/eve-proto/src/frame.rs:72-84`）。

- 发送上限 `MAX_FRAME_LEN = 1_000_000`：超过直接报 `FrameTooLarge`，不截断（`crates/eve-proto/src/frame.rs:9-10`、`crates/eve-proto/src/frame.rs:59-65`）。
- 接收上限 `MAX_INCOMING_FRAME_LEN = 16_000_000`：只用于防内存，客户端上传头像/长错误报告会超过 1 MB（`crates/eve-proto/src/frame.rs:12-14`、`crates/eve-proto/src/frame.rs:46-48`）。
- 长度 0 视为非法帧（`crates/eve-proto/src/frame.rs:43-45`）。
- `FrameReader` 是纯缓冲区：`push` 追加，`next_frame` 在凑够一整帧时切出并 `drain`，否则返回 `None`（`crates/eve-proto/src/frame.rs:20-57`）。

### 压缩

发送前经 `maybe_compress(raw, compressed_part)`（`crates/eve-proto/src/frame.rs:86-110`）：

1. 空 payload 不压缩；
2. `compressed_part` 占比 ≥ 75% 时不压缩；
3. 可压缩部分不超过 200 字节时不压缩；
4. 用 zlib level 1 压一次；压缩结果不比原文小，或压缩收益 ≤ 5%，都回退原文。

连接层调用时 `compressed_part` 固定传 0（`crates/eve-server/src/conn/mod.rs:445-450`），所以实际规则是：payload > 200 字节且压缩收益 > 5% 才发压缩帧。bulk 对象另有一套 level 9 的压缩，见后文。

### MessageType

`MessageType` 是 15 个命令的枚举，`from_i64` 对未知值报 `UnknownCommand`（`crates/eve-proto/src/packet.rs:9-49`）。

| 值 | 名称 | 从客户端允许 | 服务端当前处理 |
|---|---|---|---|
| 0/1 | `AuthenticationReq` / `AuthenticationRsp` | 仅 Req | 登录 |
| 2/3 | `IdentificationReq` / `IdentificationRsp` | 否 | 未使用 |
| 6/7 | `CallReq` / `CallRsp` | 均允许 | 服务调用 / 客户端应答 |
| 8 | `TransportClosed` | 否 | 未使用 |
| 10/11 | `ResolveReq` / `ResolveRsp` | 仅 Req | 仅告警 `unhandled`（`crates/eve-server/src/conn/mod.rs:216-219`） |
| 12 | `Notification` | 允许 | 解析后仅识别少数事件 |
| 15 | `ErrorResponse` | 允许 | 作为客户端应答/异常 |
| 16/18 | `SessionChangeNotification` / `SessionInitialStateNotification` | 否 | 前者发送；后者定义未使用 |
| 20/21 | `PingReq` / `PingRsp` | 仅 Req | 原样回 `PingRsp`（`crates/eve-server/src/conn/mod.rs:202-206`） |

`is_request` 按命令码奇偶判定（偶数=请求，`crates/eve-proto/src/packet.rs:106-108`）。

### 包体结构

`MachoPacket` 的线上形态是一个 `Value::Instance`：class 为 `macho.<命令名>`，state 为固定 6 元组（`crates/eve-proto/src/packet.rs:191-212`）：

```
(cmd:int, source:address|None, destination:address|None,
 userID:int|None, body:tuple, oob:dict|None)
```

- `to_value` 先按 `body_arity` 校验包体元素个数，不匹配报 `BadArity`（`crates/eve-proto/src/packet.rs:89-104`、`crates/eve-proto/src/packet.rs:164-174`）。
- `oob` 为空且命令没有默认 channel 时写 `None`；`Authentication*` 自动补 `channel="authentication"`，`SessionChange*` 补 `"sessionchange"`（`crates/eve-proto/src/packet.rs:80-87`、`crates/eve-proto/src/packet.rs:176-189`）。
- 解析时若 Instance 带 class GUID，必须与命令码对应的 GUID 一致，否则报 `GuidMismatch`（`crates/eve-proto/src/packet.rs:214-234`）。
- `respond` 交换 source/destination 并沿用 `user_id`；`error_response` 固定把“原命令码 + 错误码 + payload”塞进 `ErrorResponse`（`crates/eve-proto/src/packet.rs:146-162`）。

### 地址

`MachoAddress` 的 GUID 是 `macho.MachoAddress`，state 是带单字节标签的元组（`crates/eve-proto/src/address.rs:4`、`crates/eve-proto/src/address.rs:62-86`）：

| 标签 | 变体 | 元组 | 含义 |
|---|---|---|---|
| `"C"` | `Client` | `(C, clientID, callID, service)` | 指向某个客户端连接 |
| `"N"` | `Node` | `(N, nodeID, service, callID)` | 指向服务节点 |
| `"A"` | `Any` | `(A, service, callID)` | 任意节点上的服务 |
| `"B"` | `Broadcast` | `(B, broadcastID, narrowcast, idType)` | 广播/窄播，通知用它按事件名路由 |

service 可以是 `None`；整数位允许 `None`。解析也接受裸元组（不带 Instance 包装），但带包装时 GUID 必须匹配（`crates/eve-proto/src/address.rs:95-135`）。

### 从客户端允许的命令

白名单为 `ErrorResponse | Notification | CallRsp | CallReq | ResolveReq | AuthenticationReq | PingReq`（`crates/eve-proto/src/packet.rs:110-117`）。主循环在解包后检查，不在白名单内直接以 `"Invalid packet - command not allowed from a client"` 关闭连接（`crates/eve-server/src/conn/mod.rs:160-162`）。

## 服务调用解析与分发
### CallReq 的两层 marshal

第一层是包体：`CallReq` 的 body 固定 2 元 `(payload, None)`（`crates/eve-proto/src/packet.rs:134-136`），`payload` 是 `(bound_flag, blob)`：

- `bound_flag == 1` 表示这是 bound 对象调用；
- `blob` 允许 `MarshalStream`、`Bytes` 或 `Buffer`（`crates/eve-server/src/services.rs:52-59`）。

第二层 `blob` 自身是一段 marshal，解出 `(service_or_object_id, method, args, kwargs)`：

1. `service` 取值优先用 `destination.service`；没有时，若 `bound_flag == 1` 则用内层第 0 项（对象 ID 字符串）；两者都没有报 `Shape`（`crates/eve-server/src/services.rs:64-70`）。
2. `method` 必须是第 1 项的字节串，否则报 `Shape("call method name")`（`crates/eve-server/src/services.rs:72-76`）。
3. `args` 取第 2 项序列，缺省为空；`kwargs` 取第 3 项 dict，缺省为空（`crates/eve-server/src/services.rs:77-81`）。
4. `kwargs` 中删除 `machoVersion`，它是传输元数据而不是方法参数（`crates/eve-server/src/services.rs:82-83`）。

解析失败不会断开连接：`service_call` 记警告并回一个 `CustomError`（"The server could not read that call."）（`crates/eve-server/src/conn/mod.rs:223-231`）。

### service_name 与 bound 对象 ID

bound 对象 ID 形如 `N=<node>:<service>#<p1,p2,...>`，由 `object_id` 生成、`parse` 反向解析；参数按逗号分隔，解析失敗的项被丢弃，`#` 后为空则参数为空（`crates/eve-server/src/svc/bound.rs:13-37`）。

`Call::service_name()` 用 `bound::parse` 去掉 ID 前缀，返回纯服务名；解析不了就原样返回（`crates/eve-server/src/services.rs:29-31`）。注意参数里若含逗号以外的内容不会保留，bound 参数只支持整数。

### bound 服务的解析与绑定

对 `add_bound` 注册的服务，`Registry::dispatch` 先拦截两个协议方法（`crates/eve-server/src/services.rs:255-268`）：

1. `MachoResolveObject` → 直接返回 `Long(node_id)`，不进入 handler。
2. `MachoBindObject` → `Service::bind`：
   - `params_of`：优先从 `call.service` 的 bound ID 取参数；否则取第一个参数的元组/列表整数项，或单个整数（`crates/eve-server/src/svc/bound.rs:43-54`）；
   - `piggyback`：从 `call.args[1]` 取 `(method, args)`，这是客户端把首次调用搭在 bind 上的形式（`crates/eve-server/src/svc/bound.rs:81-89`）；
   - 有 piggyback 时，用绑定后的对象 ID 构造内层 `Call` 再走本服务的 handler 链；`Outcome::Unknown` / `UserError` 都降级为 `None` 返回值，不向客户端报错（`crates/eve-server/src/services.rs:203-218`、`crates/eve-server/src/svc/bound.rs:95-107`）；
   - 最终结果是 `(object_ref, retval)`（`crates/eve-server/src/svc/bound.rs:91-93`）。

`object_ref`/`object_ref_with` 把一个对象引用编码为 `CallbackObject`，内部 marshal 的是 `(objectID, refID)`；带公共属性时是 `(objectID, {属性}, refID)`，`refID` 用当前 FILETIME（`crates/eve-server/src/svc/bound.rs:56-79`）。

### Registry 与分发顺序

`Registry` 是 `HashMap<&'static str, Service>`，`Service` 持有 `bound` 标志和 handler 列表（`crates/eve-server/src/services.rs:185-189`、`crates/eve-server/src/services.rs:221-233`）。

- 同名服务可由多个模块注册（例如 `character` 由 `login`、`charcreation`、`charsheet`、`notes` 四组 handler 组成），按 `svc/mod.rs` 中的注册顺序依次尝试，第一个返回 `Some(Outcome)` 的 handler 生效（`crates/eve-server/src/services.rs:191-199`、`crates/eve-server/src/svc/mod.rs:66-70`）。
- 同一个服务不能既按 bound 又按 unbound 注册，触发 `assert_eq!`（`crates/eve-server/src/services.rs:242-249`）。
- 服务名不存在 → `Outcome::Unknown("<name>::<method> (no such service)")`；服务存在但没有 handler 认领 → `Outcome::Unknown("<name>::<method>")`（`crates/eve-server/src/services.rs:198`、`crates/eve-server/src/services.rs:257-259`）。
- 所有 bound 服务共用同一套 `MachoResolveObject`/`MachoBindObject` 处理，不经过各模块自己的 handler。

### 连接层对调用的前置拦截

部分调用会改变连接/session 状态，因此在进 Registry 之前由 `conn` 直接处理（`crates/eve-server/src/conn/mod.rs:242-270`）：

- `character::SelectCharacterID`；
- `beyonce` 的 `Dock`/`TurboDock`/`StargateJump`（`TurboDock` 是任意位置停靠的 GM 快捷方式）；
- `ship` 的 `Undock`/`Board`，以及 `ship::MachoBindObject` 里 piggyback 的这两种调用。

这些路径走自己的逻辑，不经过 `Registry::dispatch`，也不会触发 pending session change 的释放。

## bulk data 与对象缓存
### SPECS

`SPECS` 是一张静态表，共 38 项，每项给出缓存键、形状、SQL、可选 header 与“按数字文本再解析”的列名（`crates/eve-server/src/bulkdata.rs:18-24`、`crates/eve-server/src/bulkdata.rs:43-131`）。键名与客户端请求的 `objectID` 一一对应，例如 `config.BulkData.types`、`config.Roles`、`config.StaticOwners`。

构造器有三种（`crates/eve-server/src/bulkdata.rs:26-41`）：

- `s(key, shape, sql)`：从数据库查；
- `s_num(key, shape, sql, numeric_text)`：查库，并把这些文本列再解析成 Int/Double；
- `empty(key, shape, header)`：不从库读，只给 header 的空对象（如 `config.BulkData.owners`、`config.EncyclopediaTypes`）。

`config.StaticOwners` 的 SQL 还排除了 `bots` 表里的角色，避免登录时整包超过 1 MB（`crates/eve-server/src/bulkdata.rs:124-128`）。主循环会对超过 900 KB 的对象打警告（`crates/eve-server/src/main.rs:41`、`crates/eve-server/src/main.rs:149-151`）。

### 三种 shape

| Shape | 线上形态 | 用途 |
|---|---|---|
| `Tuple` | `(header:list, lines:list)` | `config.BulkData.*` 的常规二维表 |
| `Rowset` | `Instance("util.Rowset", {header, lines})` | `config.Flags` 等客户端按行集读的表 |
| `RowTuple` | `(header:list, [Instance("util.Row", {header, line})...])` | 客户端逐行读 `row.column` 的表（`cfg.py` 的 ram 相关表） |

三个分支的构造见 `crates/eve-server/src/bulkdata.rs:193-217`。

### 加载、CRC 与版本

`BulkData::load` 在启动时执行一次（`crates/eve-server/src/main.rs:94-97`），逐项：

1. 查库得到 header 与 lines；`UNDEFINED_TABLE` 降级为空对象并记错误日志，其它数据库错误直接让启动失败（`crates/eve-server/src/bulkdata.rs:171-191`）。
2. 按 shape 组装 `Value`，用当前字符串表 marshal 成 `inner`（`crates/eve-server/src/bulkdata.rs:192-219`）。
3. `checksum = crc_hqx(inner, CRC_SEED)`，CRC 是 16 位 CCITT（多项式 `0x1021`）（`crates/eve-server/src/bulkdata.rs:150-159`、`crates/eve-server/src/bulkdata.rs:220`）。
4. 版本 `version = (now, checksum)`，`now` 是启动时一次的 `filetime_now()`（100ns 为单位的 Windows FILETIME），因此所有对象共享同一时间戳（`crates/eve-server/src/bulkdata.rs:227`、`crates/eve-server/src/bulkdata.rs:346-351`）。
5. 用 `maybe_deflate` 压缩：≤200 字节不压；否则 zlib level 9，只有更小才标记为已压缩（`crates/eve-server/src/bulkdata.rs:278-290`）。

`CRC_SEED` 写作 `170_611_u32 as u16`，运行时截断为 `39539`（0x9A73）（`crates/eve-server/src/bulkdata.rs:161`）。

### 缓存对象的两种形态

1. `handle(entry)`：`Instance("util.CachedObject", (key, nodeID, (filetime:Long, crc:Int)))`，是登录时 `init_vals` 里交给客户端的“句柄”（`crates/eve-server/src/bulkdata.rs:237-246`、`crates/eve-server/src/bulkdata.rs:274-276`）。
2. `payload(entry)`：`Instance("objectCaching.CachedObject", (version, None, nodeID, 1, Bytes(pickle), isCompressed:int, key))`，是客户端真正取回的数据（`crates/eve-server/src/bulkdata.rs:258-271`）。

`init_vals` 把全部 handle 放进一个 dict，并按 key 字节序排序，保证每次登录顺序稳定（`crates/eve-server/src/bulkdata.rs:248-256`）。

### 与 GetCachableObject 的关系

客户端对 `objectCaching` 调 `GetCachableObject`，参数第 1 项（索引 1）是对象 ID 文本；服务端在 `entries` 里查到就返回 `payload`，查不到返回 `Outcome::Unknown`，客户端会收到 `ServiceNotFound`（`crates/eve-server/src/svc/login.rs:10-19`）。bulk 对象集合是启动时的静态快照，没有运行期刷新或按需生成。

数据库列到 marshal 值的转换在 `query_rows` 中固定：`INT2/INT4 → Int`、`INT8 → Long`、`FLOAT4/FLOAT8 → Double`、`BOOL → Int(0/1)`，其余按文本读，`numeric_text` 命中的列再用 `numeric_value` 尝试解析为 Int/Double（`crates/eve-server/src/bulkdata.rs:292-344`）。NULL 一律变 `Value::None`。这与 `svc/rows.rs` 的 `cell` 略有不同：后者把 `BOOL` 映射为 `Value::Bool`，文本走 `Value::text`（`crates/eve-server/src/svc/rows.rs:96-110`）。

## 错误与异常
### wrapped exception

服务端回错误统一走 `send_error`（`crates/eve-server/src/conn/mod.rs:483-490`）：

1. 把异常 `Value` marshal 成 `blob`；
2. 用原请求的 `error_response` 生成 `ErrorResponse`，body 为 `(原命令码, MACHONETERR_WRAPPEDEXCEPTION=2, (Bytes(blob),))`。

错误码常量：`MACHONETERR_UNMACHODESTINATION=0`、`UNMACHOCHANNEL=1`、`WRAPPEDEXCEPTION=2`（`crates/eve-proto/src/packet.rs:5-7`）。当前服务端只使用 2。

### UserError

`ccp_exceptions.UserError` 的 state 是 `{msg, dict, args}`（`crates/eve-server/src/exceptions.rs:6-22`）：

- 无参数：`dict=None`，`args=(msg,)`；
- 有参数：`dict={k: v}`，`args=(msg, dict)`。

`Outcome::UserError` 会被转换为这种形态再包进 wrapped exception（`crates/eve-server/src/conn/mod.rs:286-291`、`crates/eve-server/src/services.rs:97-120`）。常用构造有 `CustomError`（文本原样显示）与 `NotEnoughMoney`（`amount`/`balance`）（`crates/eve-server/src/services.rs:104-119`）。

### ServiceNotFound

`exceptions.ServiceNotFound` 的 state 是 `{serviceName, args: [serviceName]}`，`serviceName` 通常是 `"service::method"`（`crates/eve-server/src/exceptions.rs:30-39`）。`Outcome::Unknown` 一律映射为它（`crates/eve-server/src/conn/mod.rs:282-285`），包括“服务不存在”“方法未实现”“bulk 对象不存在”。

### 数据库错误的降级

- `Ctx::query`：失败时记录 `error!` 并返回空 `Vec`，调用方拿到空结果而不是异常（`crates/eve-server/src/services.rs:136-152`）。
- `Ctx::execute`：失败时记录并返回 `false`（`crates/eve-server/src/services.rs:159-168`）。
- bulk 加载：只有 `UNDEFINED_TABLE` 降级为空对象，其它错误中止启动（`crates/eve-server/src/bulkdata.rs:173-186`）。

### 关闭原因

服务端要主动断开时调用 `close`：先 marshal 一个字节串 `"<原因>, bootver=<hex>"`，hex 部分是 `(2.1, 3913, "Blood")` 的 marshal 结果，再用 `encode_frame` 发出，最后返回 `ConnError::Closed`（`crates/eve-server/src/conn/mod.rs:493-500`、`crates/eve-proto/src/llv.rs:95-109`）。

客户端主动断开时也可能发一个 `Bytes`：`decode_payload` 见到根值为 `Bytes` 就解析 `, bootver=` 后缀，返回 `ProtoError::PeerClosed`（`crates/eve-proto/src/lib.rs:15-23`、`crates/eve-proto/src/lib.rs:30-55`）。主循环对 `PeerClosed` 只记 info 并正常结束，不当错误处理（`crates/eve-server/src/conn/mod.rs:145-150`）。

## 连接生命周期与并发
### 接入与任务

1. 监听循环 `accept` 后设置 `TCP_NODELAY`，`seq += 1`，`tokio::spawn(Conn::new(...).run())`（`crates/eve-server/src/main.rs:125-137`）。
2. `client_id = seq * 10_000_000 + node_id`，保证同一进程内序号不冲突且带节点号（`crates/eve-server/src/conn/mod.rs:84-85`）。
3. `run` 先向 `World` 注册并取得该连接的通知队列，然后进入 `serve`；无论成功失败都会执行 `leave_world`（`crates/eve-server/src/conn/mod.rs:108-124`）。

### 单连接循环

`serve` 用 `tokio::select!` 同时等待两件事（`crates/eve-server/src/conn/mod.rs:126-165`）：

1. `read_frame`：从 `FrameReader` 取整帧，凑不齐就继续 `read` 8192 字节（`crates/eve-server/src/conn/mod.rs:429-441`）；返回 `None` 表示对端关闭。
2. `notifications.recv()`：处理其它连接/世界推来的 `Push`。

注释明确两个分支都是取消安全的：读分支输掉竞争不会消费字节，`recv` 不会丢消息（`crates/eve-server/src/conn/mod.rs:129-131`）。

### 通知队列

`WorldState` 为每个 client 保存一个无界 `mpsc` 发送端（`crates/eve-server/src/world.rs:76-82`、`crates/eve-server/src/world.rs:185-189`）。队列元素 `Push` 有三种（`crates/eve-server/src/world.rs:55-61`）：

| 变体 | 内容 | 连接侧处理 |
|---|---|---|
| `Notify(Notification)` | 事件名 + 参数元组 | 转成 `Notification` 包（`crates/eve-server/src/conn/mod.rs:463-476`） |
| `Move(Move)` | 沉船/爆舱/军团变更/组队/传送 | `forced_move` 改 session 并补发 session change（`crates/eve-server/src/conn/location.rs:365-399`） |
| `Call(ClientCall)` | 服务名、方法、参数、oneshot 回信 | `call_client`（`crates/eve-server/src/conn/mod.rs:298-310`） |

`World` 侧的入队方法 `notify` / `call` / `push_move` 都只做 `send`，不等待网络（`crates/eve-server/src/world.rs:317-339`）；这样做是为了不在持锁期间 await。

发出的通知包：内层 marshal `(0, (1, args))`，包体 `(0, Bytes(blob))`，destination 为 `Broadcast{broadcastID=事件名, narrowcast=[client_id], idType="clientID"}`（`crates/eve-server/src/conn/mod.rs:463-476`）。

### 服务端反向调用客户端

`call_client` 生成自增 `call_id`，构造内层 `(1, method, args, {})`，外层 `CallReq` 包体 `(0, Bytes(blob))`，source 为 `Node(node_id, call_id)`，destination 为 `Client(client_id, service)`；把 `oneshot::Sender` 存进 `client_calls` 后发送（`crates/eve-server/src/conn/mod.rs:298-310`）。

客户端回 `CallRsp` 或 `ErrorResponse` 时，`client_answered` 用 destination 的 `call_id` 找回发送端：`CallRsp` 的 `Bytes/MarshalStream/Buffer` 会再解一层 marshal，其它情况视为 `None`；`ErrorResponse` 一律视为客户端抛异常，回 `None`（`crates/eve-server/src/conn/mod.rs:314-340`）。找不到对应 `call_id` 只记警告。

### 断线清理

`leave_world`（`crates/eve-server/src/conn/mod.rs:169-190`）：

1. `world.disconnect` 移除连接、结束其组队关系并返回它所在的聊天频道及剩余成员；
2. 若角色在太空且有船，从 ballpark 移除该船，并异步保存受损状态（按“回站”处理）；
3. 异步结束该角色的交易会话；
4. 对每个受影响的频道广播 `LeaveChannel`。

客户端侧发来的 `Notification` 只做少量识别：`ClientHasReleasedTheseObjects` 被静默忽略，其它事件名记 debug，payload 读不出记警告（`crates/eve-server/src/conn/mod.rs:342-364`）。

## 已知限制/缺省行为
以下均由代码直接可证：

1. **未实现的方法返回 `ServiceNotFound`**，不断线；只有非法帧/非法包/命令白名单外才关闭连接（`crates/eve-server/src/conn/mod.rs:282-285`、`crates/eve-server/src/conn/mod.rs:151-162`）。
2. **`ResolveReq` 在白名单内但没有处理分支**：解包后落入 `other => warn!("unhandled ...")`，不回 `ResolveRsp`（`crates/eve-proto/src/packet.rs:110-117`、`crates/eve-server/src/conn/mod.rs:216-219`）。`ResolveRsp`、`Identification*`、`TransportClosed`、`SessionInitialStateNotification` 在服务端没有发送点。
3. **LLV 握手没有超时**：`LLV_TIMEOUT_SECS=120` 只有定义，没有引用（`crates/eve-proto/src/llv.rs:16`）。
4. **marshal 编码器不产出共享表/CHECKSUM/REFERENCE**：头部 mapcount 恒为 0，解码器则支持这些标签（`crates/eve-marshal/src/ser.rs:14`、`crates/eve-marshal/src/de.rs:119-128`、`crates/eve-marshal/src/de.rs:270-277`）。
5. **非法 marshal 帧会落盘**到 `dump_dir/badframe-<client_id>-<len>.bin`，并记录前 48 字节的十六进制；`dump_dir` 由 `RMR_DUMP_DIR` 配置，默认当前目录（`crates/eve-server/src/conn/mod.rs:502-513`、`crates/eve-server/src/config.rs:160`、`rmr.yml:20`）。
6. **`service_call` 解析失败只回 `CustomError`**，连接继续；`MachoPacket::from_value` 失败则直接以 `"Malformed packet: ..."` 关闭（`crates/eve-server/src/conn/mod.rs:223-231`、`crates/eve-server/src/conn/mod.rs:156-159`）。
7. **所有 bulk 对象在启动时一次性构建**，运行期不刷新；SQL 缺失表降级为空对象，客户端会自己报错（`crates/eve-server/src/bulkdata.rs:164-235`、`crates/eve-server/src/bulkdata.rs:173-186`）。
8. **bound 对象参数只支持整数**，`parse` 用 `filter_map` 丢弃非法项（`crates/eve-server/src/svc/bound.rs:24-37`）。
9. **同连接反向调用没有超时**：`client_calls` 的 oneshot 只会在客户端回包或连接结束时被丢弃（`crates/eve-server/src/conn/mod.rs:314-340`）。
