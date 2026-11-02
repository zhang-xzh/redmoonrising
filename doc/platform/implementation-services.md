# 服务层实现

本文件讲 `crates/eve-server/src/svc/` 下每个模块负责哪些 machoNet service、实现了哪些 method、读写哪些表、有哪些硬性规则与缺口。服务注册的唯一清单是 `crates/eve-server/src/svc/mod.rs:58` 的 `registry()`；分发骨架在 `crates/eve-server/src/services.rs`，`svc/bound.rs` 与 `svc/rows.rs` 是两个公共工具模块。

会话移动（`beyonce` 的 Dock/StargateJump、`ship` 的 Undock/Board、`space.rs`/`moves.rs`/`inflight.rs` 的移动与战斗推进）的过程细节见 `doc/platform/implementation-world.md`，这里只列它们注册的 service/method 与职责边界。

## 分发模型

### Registry、Handler、Ctx、Outcome

- `Registry` 是 `HashMap<&'static str, Service>`（`services.rs:222`）；每个 `Service` 保存 `name`、`bound: bool` 和按注册顺序排列的 `handlers: Vec<Handler>`（`services.rs:185`）。
- `Handler` 是 `for<'a> fn(&'a Call, &'a Ctx<'a>) -> HandlerFuture<'a>`，返回 `Option<Outcome>`（`services.rs:171`）。`handler!` 宏把 `async fn` 包成这个签名（`services.rs:177`）。
- `Ctx` 给 handler 的是只读环境：`bulk`（登录 bulk 对象）、`dogma`（属性/效果目录）、`session`、共享数据库客户端 `db`、`db_url`（需要独立事务时再连）、`node_id`、`world`、`client_id`（通知投递目标）（`services.rs:122`）。
- `Ctx::query` / `query_one` 在 SQL 失败时记日志并返回空结果，客户端看到的是“空列表”而不是异常；`Ctx::execute` 失败返回 `false`（`services.rs:139`、`services.rs:150`、`services.rs:160`）。这是全服务层一致的“读失败即空”约定。

### 同名多 handler 与顺序

`Service::call` 依次 `await` 每个 handler，第一个返回 `Some` 的生效（`services.rs:192`）；全部返回 `None` 才生成 `Outcome::Unknown("{service}::{method}")`（`services.rs:198`）。因此同名服务的注册顺序就是匹配优先级：

| service | handler 顺序 |
|---|---|
| `character` | `login` → `charcreation` → `charsheet` → `notes`（`svc/mod.rs:67`） |
| `map` | `map::map` → `station::map`（`svc/mod.rs:78`） |
| `dogmaIM` | `starbase` → `inflight` → `dogma`（`svc/mod.rs:84`） |
| `marketProxy` | `market` → `wallet`（`svc/mod.rs:100`） |
| `corpRegistry` | `membership` → `alliance` → `war` → `votes` → `corp`（`svc/mod.rs:107`） |

同一名字的所有注册必须同为 bound 或同为非 bound，否则 `Registry::entry` 直接 `assert_eq!` 崩溃（`services.rs:242`）。

### bound 服务、`add_bound`、`MachoResolveObject` / `MachoBindObject`

- `add` 注册普通服务，`add_bound` 只多置一个 `bound = true`（`services.rs:230`、`services.rs:237`）。差别全部在 `Registry::dispatch`：bound 服务先截获两个方法（`services.rs:260`）：
  - `MachoResolveObject` → `Value::Long(ctx.node_id)`，表示这个对象就在本节点；
  - `MachoBindObject` → `Service::bind`（`services.rs:203`）：从绑定参数生成对象 ID，再用该 ID 构造内层 `Call`；若客户端在 bind 上捎带了一个方法（piggyback），先执行它，把结果作为 `(object_ref, retval)` 的第二个元素返回；否则 retval 是 `None`。
- 绑定参数由 `bound::params_of` 决定：service 串本身是对象 ID 就取其 `#` 后的参数，否则取第一个元组/列表参数（`svc/bound.rs:43`）。对象 ID 形态为 `N=<node>:<service>#<p1>,<p2>`（`svc/bound.rs:13`），解析在 `svc/bound.rs:24`。
- 对象引用是 `ObjectCallGPCS` 的 `(objectID, [__publicattributes__], refID)` pickle（`svc/bound.rs:63`）；`refID` 用当前 FILETIME。
- piggyback 内层调用失败不会变成错误包：未知方法只 `warn!`，`UserError` 只 `info!`，都回 `None` 作为 retval（`svc/bound.rs:95`）。
- `Call::service_name()` 用于把 `N=1:invbroker#...` 还原成 `invbroker` 再查表（`services.rs:29`）。但 `parse_call` 优先采用包目的地址里的 service（`services.rs:64`），因此“目的地址写 `corpRegistry`、对象 ID 写别的服务”会按目的地址路由（测试见 `services.rs:330`）。

### `rows` 工具

`svc/rows.rs` 负责把 PostgreSQL 行变成客户端能 unpickle 的容器，并做 NULL 安全读取：

- `key_val` → `util.KeyVal`（`svc/rows.rs:8`）；`row` / `rowset` → `util.Row` / `util.Rowset`（`svc/rows.rs:17`、`svc/rows.rs:27`）；`rowset_with_columns` 额外带 `columns`（市场 UI 需要，`svc/rows.rs:39`）；`index_rowset` → `util.IndexRowset`（`svc/rows.rs:50`）。
- `change(header, old, new)` 生成 `On*Changed` 的 `{column:(old,new)}`（`svc/rows.rs:64`）。
- `cell` / `line` / `lines` / `int` / `float` / `text` 按列类型取值，NULL 或未知类型统一变 `Value::None`，不会 panic（`svc/rows.rs:96`、`svc/rows.rs:113`）。

### 未知方法与 `UserError`

- `Outcome::Unknown(text)` → `conn` 记 `not implemented` 并回 `exceptions.ServiceNotFound`（`conn/mod.rs:282`）。
- `Outcome::UserError { msg, args }` → `exceptions::user_error`，编成 `ccp_exceptions.UserError(msg, dict)`（`conn/mod.rs:286`、`exceptions.rs:6`）。`Outcome::custom(text)` 是 `msg="CustomError"`、`args={error: text}` 的快捷构造（`services.rs:106`）；`not_enough_money(need, have)` 是 `NotEnoughMoney` 带 `amount`/`balance`（`services.rs:114`）。
- 未知名、未实现方法在 handler 里通常显式 `Outcome::Unknown(...)`，或直接 `return None` 让后续同名 handler 尝试，最终落到 `ServiceNotFound`。

### 不走服务表的调用

`conn` 在 `services.dispatch` 之前截获会改连接状态的方法（`conn/mod.rs:240` 起）：`character::SelectCharacterID`、`beyonce::Dock/TurboDock/StargateJump`、`ship::Undock/Board`（含 bind 上的 piggyback）。这些方法即使在 `registry()` 对应的模块里也查不到实现。

## 服务总表

下表按 `svc/mod.rs:58` 的注册顺序逐条列出，共 64 条注册、53 个唯一 service 名。

| service | 模块 | 绑定? | 主要 method | 主要数据表 | 备注 |
|---|---|---|---|---|---|
| `objectCaching` | `login` | 否 | `GetCachableObject` | 无（`BulkData`） | 未命中缓存对象直接 `Unknown` |
| `authentication` | `login` | 否 | `Ping`、`GetPostAuthenticationMessage`、`SetLanguageID` | 无 | 只做登录后杂务 |
| `alert` | `alert` | 否 | `BeanCount`、`SendClientStackTraceAlert`、`BeanDelivery` | 无（进程内 `BEANS`） | 客户端异常去重与首见日志 |
| `config` | `config` | 否 | `Get*Ex`、`GetMap*`、`GetCelestialStatistic`、`GetUnits` | `invTypes`、`invGroups`、`map*`、`staStations` 等静态表 | 批量静态数据入口 |
| `languageSvc` | `language` | 否 | `GetLanguages`、`GetMessagesByLanguageID`、`GetTextsForGroup` | 无 | 只有英语，语言包为空 |
| `machoNet` | `machonet` | 否 | `GetClusterSessionStatistics` | 无（`WorldState`） | 星图在线人数 |
| `character` | `login` | 否 | `GetCharactersToSelect`、`GetCharacterToSelect`、`PrepareCharacterForDelete`、`CancelCharacterDeletePrepare`、`DeleteCharacter` | `character_`、`account` | 角色选择/删除 |
| `character` | `charcreation` | 否 | `GetCharCreationInfo`、`GetAppearanceInfo`、`ValidateName`、`GetCharacterAppearanceList`、`CreateCharacter` | `chr*`、`bloodlineTypes`、`character_`、`entity` | 建号全流程 |
| `character` | `charsheet` | 否 | `GetPrivateInfo`、`GetCharacterInfo`、`GetCharacterDescription`、`SetCharacterDescription`、`GetCloneTypeID`、`GetHomeStation` | `character_`、`chr*`、`entity` | 角色面板 |
| `character` | `notes` | 否 | `GetOwnerNoteLabels`、`GetOwnerNote`、`Add/Edit/RemoveOwnerNote`、`GetNote`、`SetNote` | `chrNotes`、`chrOwnerNote` | 个人备注 |
| `charmgr` | `charsheet` | 否 | `GetPublicInfo`、`GetPublicInfo3`、`GetPrivateInfo`、`GetCharacterInfo`、`GetTopBounties`、`AddToBounty` | `character_`、`bounties`、`entity` | 公开信息与赏金 |
| `skillMgr` | `skills` | 是 | `GetEndOfTraining`、`CharStartTrainingSkill`、`CharStopTrainingSkill`、`CharAddImplant`、`RemoveImplantFromCharacter` | `entity`、`entity_attributes`、`invTypes` | 技能训练/植入体 |
| `jumpCloneSvc` | `clones` | 是 | `GetCloneState`、`GetShipCloneState`、`GetStationCloneState`、`GetPriceForClone` | 无 | 安装/跳跃等 6 个方法显式未实现 |
| `standing2` | `standing` | 否 | `GetMyStandings`、`GetNPCNPCStandings`、`GetNPCStandingsTo`、`SetPlayerStanding`、`SetCorpStanding`、`GetMyKillRights` | `chrStandings`、`ownerStandings`、`chrNPCStandings`、`chrKillRights` | 军团 standing 需 Director |
| `station` | `station` | 否 | `GetStationItemBits`、`GetGuests` | `staStations`、`staStationTypes`、`entity`、`character_` | 当前空间站 |
| `stationSvc` | `station` | 否 | `GetStation`、`GetSolarSystem`、`GetConstellation`、`GetRegion`、`GetAllianceSystems` | `staStations`、`map*` | 地点详情 |
| `map` | `map` | 否 | `GetSolarSystemPseudoSecurities`、`GetStationCount`、`GetBeaconCount`、`GetMyExtraMapInfoAgents`、`GetSolarSystemLoadRatios` 等 | `mapSolarSystems`、`staStations`、`entity`、`chrNPCStandings` | 星图附加层 |
| `map` | `station` | 否 | `GetStationExtraInfo` | `staStations`、`staServices` | 空间站服务列表 |
| `tutorialSvc` | `tutorial` | 否 | `GetTutorials`、`GetCriterias`、`GetTutorialInfo`、`GetTutorialVersionInfo` | `tutorials`、`tutorial_pages`、`tutorial_criteria` | 教程只读 |
| `invbroker` | `inventory` | 是 | `GetInventory`、`GetInventoryFromId`、`GetInventoryFromIdEx` | 无 | 只发容器对象引用 |
| `invcontainer` | `inventory` | 否 | `List`、`ListStations`、`ListStationItems`、`ListStationBlueprintItems`、`GetItem`、`GetCapacity` | `entity`、`invTypes`、`invGroups`、`invBlueprints` | 写方法由 `moves` 处理 |
| `dogmaIM` | `starbase` | 是 | `AnchorStructure`、`Get/SetTowerClaim`、`Get/SetTowerSentrySettings`、`SetTowerPassword`、`SetShipPassword`、`Get/SetStarbasePermissions`、`LinkResourceForTower`、`ChangeStructureProvisionType` | `posStructures`、`posLinks`、`dgmTypeAttributes` | POS 操作 |
| `dogmaIM` | `inflight` | 是 | `AddTarget`、`RemoveTarget`、`ClearTargets`、`GetTargets`、`GetTargeters`、`Activate`、`Deactivate` | `dgmTypeAttributes`、`dgmEffects`、`invTypes` | 锁定与模块循环 |
| `dogmaIM` | `dogma` | 是 | `GetAttributeTypes`、`GetSkillPrerequisites`、`ShipGetInfo`、`CharGetInfo`、`ItemGetInfo`、`CheckSendLocationInfo`、`LogAttribute` | `dgmAttributeTypes`、`dgmTypeAttribs`、`invTypes` | 属性计算与信息窗 |
| `factory` | `factory` | 否 | `GetBlueprintAttributes`、`GetMaterialsForTypeWithActivity`、`GetMaterialCompositionOfItemType`、`GetBlueprintInformationAtLocationWithFlag` | `invBlueprintTypes`、`invBlueprints`、`TL2MaterialsForTypeWithActivity` | 蓝图信息 |
| `ramProxy` | `ram` | 否 | `AssemblyLinesSelect`、`AssemblyLinesGet`、`GetJobs2`、`InstallJob`、`CompleteJob` | `ramAssemblyLines`、`ramJobs`、`invBlueprints` | 制造/科研/拷贝 |
| `reprocessingSvc` | `reprocessing` | 是 | `GetReprocessingInfo`、`GetOptionsForItemTypes`、`GetQuotes`、`Reprocess` | `staStations`、`chrNPCStandings`、`TL2MaterialsForTypeWithActivity` | 按站与技能算产出 |
| `repairSvc` | `repair` | 是 | `GetDamageReports`、`RepairItems`、`UnasembleItem`、`UnasembleItems` | `entity`、`entity_attributes`、`dgmTypeAttribs` | 修理报价为 0；拆包 |
| `ship` | `space` | 是 | `AssembleShip`、`Drop`、`Scoop`、`ScoopDrone` | `entity`、`invTypes`、`map*` | Undock/Board 由 `conn` 处理 |
| `insuranceSvc` | `insurance` | 是 | `GetContracts`、`GetContractForShip`、`InsureShip`、`UnInsureShip` | `insuranceContracts`、`entity`、`invTypes` | 保险费与 12 周合同 |
| `beyonce` | `space` | 是 | `GetFormations`、`UpdateStateRequest`、`GetGangState`、`GetRelativity`、移动 7 方法 | `mapDenormalize`、`mapJumps`、`staStations` | Dock/Jump 由 `conn` 处理 |
| `posMgr` | `starbase` | 是 | `GetControlTowerFuelRequirements`、`GetMoonForTower`、`GetMoonProcessInfoForTower` | `posStructures`、`invControlTowerResources` | 控制塔窗口 |
| `entity` | `crate::drones` | 是 | `CmdEngage`、`CmdMine`、`CmdMineRepeatedly`、`CmdReturnHome`、`CmdReturnBay`、`CmdAbandonDrone` | 无（`WorldState` park） | 无人机指令 |
| `aggressionMgr` | `crate::concord` | 是 | `CheckLootRightExceptions` | `corporation` | 偷窃判定 |
| `account` | `wallet` | 否 | `GiveCash`、`GiveCashFromCorpAccount`、`GetCashBalance`、`GetKeyMap`、`GetRefTypes`、`GetJournal` | `character_`、`corporation`、`market_journal`、`market_keyMap`、`market_refTypes` | 现金与流水 |
| `billMgr` | `wallet` | 否 | `GetBillTypes`、`CharGetBills`、`CharGetBillsReceivable`、`GetCorporationBills`、`PayCorporationBill`、`CharPayBill` | `billsReceivable`、`billTypes`、`market_journal` | 账单支付 |
| `marketProxy` | `market` | 否 | `GetMarketGroups`、`GetOrders`、`GetNewPriceHistory`、`GetStationAsks`、`GetSystemAsks`、`GetRegionBest`、`GetCharOrders`、`GetCorporationOrders` | `market_orders`、`market_transactions`、`invMarketGroups`、`invTypes` | 查询为主 |
| `marketProxy` | `wallet` | 否 | `CharGetNewTransactions`、`CharGetTransactions` | `market_journal` | 钱包流水 |
| `trademgr` | `pvptrade` | 否 | `InitiateTrade` | `character_`、`corporation` | 只发起 |
| `tradeSession` | `pvptrade` | 是 | `List`、`IsCEOTrade`、`Add`、`MultiAdd`、`MultiMerge`、`StackAll`、`OfferMoney`、`ToggleAccept`、`Abort` | `entity`、`character_` | 交易对象在内存 |
| `corpmgr` | `corp` | 否 | `GetCorporations`、`GetPublicInfo`、`GetCorporationIDForCharacter`、`GetCorporationStations`、`GetItemsRented`、`GetAssetInventory*`、`AuditMember` | `corporation`、`staStations`、`entity`、`crpOffices`、`rentalInfo` | 军团公开信息 |
| `corporationSvc` | `corp` | 否 | `GetNPCDivisions`、`GetEmploymentRecord`、`GetCorpInfo`、`GetFactionInfo` | `crpNPCDivisions`、`chrEmployment`、`chrFactions`、`mapRegions` | 雇佣与阵营 |
| `corpRegistry` | `membership` | 是 | `AddCorporation`、`InsertApplication`、`UpdateApplication`、`UpdateApplicationOffer`、`DeleteApplication`、`KickOutMember`、`UpdateMember(s)`、`CanBeKickedOut` | `corporation`、`crpApplications`、`chrEmployment`、`crpCharShares` | 建军/入团 |
| `corpRegistry` | `alliance` | 是 | `CreateAlliance`、`ApplyToJoinAlliance`、`GetAllianceApplications`、`DeleteAllianceApplication`、`GetSuggestedAllianceShortNames` | `alliances`、`allianceApplications` | 联盟申请 |
| `corpRegistry` | `war` | 是 | `RetractWar`、`ChangeMutualWarFlag` | `crpWars` | 无联盟公司由 CEO 决定 |
| `corpRegistry` | `votes` | 是 | `InsertVoteCase`、`InsertVote`、`UpdateSanctionedAction`、`ResignFromCEO`、`GetVoteCasesByCorporation` 等 | `crpVoteCases`、`crpVoteOptions`、`crpVotes`、`crpSanctionedActions` | 军团投票 |
| `corpRegistry` | `corp` | 是 | `GetCorporation`、`GetMember(s)`、`GetRoles`、`GetRoleGroups`、`GetSharesByShareholder`、`GetLockedItemLocations` | `corporation`、`character_`、`crpCharShares`、`crpItemLocks` | 军团对象读取 |
| `corpStationMgr` | `corp` | 是 | `GetCorporateStationInfo`、`GetQuoteForRentingAnOffice`、`RentOffice`、`GetPotentialHomeStations`、`SetHomeStation`、`SetCloneTypeID` | `crpOffices`、`staStations`、`entity` | 办公室与医疗舱 |
| `corpMembers` | `corp` | 是 | `Fetch`、`FetchByKey` | `character_`、`corporation` | `util.SparseRowset` 提供者 |
| `allianceRegistry` | `alliance` | 是 | `GetAlliance`、`GetMembers`、`GetApplications`、`UpdateApplication`、`DeclareExecutorSupport`、`DeleteMember`、`UpdateAlliance`、`Set/DeleteRelationship`、`DeclareWarAgainst`、`GetBills*` | `alliances`、`allianceMembers`、`allianceApplications`、`allianceRelationships` | 联盟对象 |
| `warRegistry` | `war` | 是 | `GetWars`、`GetCostOfStartingAWarAgainst` | `crpWars` | 宣战成本随受害方战争数增长 |
| `LSC` | `chat` | 否 | `JoinChannels`、`GetChannels`、`SendMessage`、`GetMyMessages`、`Page`、`Invite`、`CreateChannel`、`Configure`、`AccessControl` 等 | `channels`、`channelChars`、`channelMods`、`evemail`、`evemailDetails` | 聊天与邮件 |
| `onlineStatus` | `onlinestatus` | 否 | `GetInitialState`、`GetOnlineStatus` | 无（`WorldState`） | 在线状态 |
| `bookmark` | `bookmark` | 否 | `GetBookmarks`、`BookmarkLocation`、`UpdateBookmark`、`DeleteBookmarks`、`CreateBookmarkVoucher(s)`、`AddBookmarkFromVoucher` | `bookmarks`、`bookmarkVouchers`、`entity` | 地点与凭证 |
| `voucher` | `bookmark` | 否 | `GetObject` | `entity`、`bookmarkVouchers` | 返回 `voucher.Bookmark` |
| `petitioner` | `petition` | 否 | `CreatePetition`、`GetMyPetitions`、`GetPetitionQueue`、`ClaimPetition`、`ClosePetition`、`PetitionerChat` 等 | `petitions`、`petitionMessages`、`petitionLog`、`petitionProperties` | 客服单 |
| `lookupSvc` | `lookup` | 否 | `LookupOwners`、`LookupCharacters`、`LookupCorporations`、`LookupStations`、`LookupFactions`、`LookupLocationsByGroup` | `eveStaticOwners`、`character_`、`corporation`、`staStations`、`mapDenormalize` | 名字搜索，最多 500 条 |
| `gangsta` | `gang` | 否 | `GetGangInfoForChar`、`InviteCharacter`、`AcceptInvitation`、`RejectInvitation`、`LeaveGang`、`KickMember`、`DisbandGang`、`MakeLeader` | `character_`、`corporation`、`alliances` | 舰队在内存 |
| `agentMgr` | `agents` | 是 | `GetAgents`、`DoAction`、`GetMyJournalDetails`、`GetMissionJournalInfo`、`GetInfoServiceDetails`、`WarpToLocation`、`GotoLocation` | `agtAgents`、`agtCharMissions`、`staStations`、`map*` | 代理对话与任务 |
| `missionMgr` | `missions` | 是 | `GetCourierOptions`、`CreateCourierMission`、`GetAvailableCourierMissions`、`GetMyCourierMissions`、`AcceptCourierMission`、`DeliverCourierPackage`、`CancelMission` | `courierMissions`、`entity`、`invTypes`、`staStations` | 玩家间快递任务 |
| `slash` | `gm` | 否 | `SlashCmd` | `entity`、`character_`、`chrNPCStandings`、`invTypes` | GM 斜杠命令 |
| `keeper` | `gm` | 否 | `GetLevelEditor`、`DEGet*`、`EditObject`、`ActivateAccelerationGate` | 无 | 无地牢可编辑 |
| `dungeon` | `gm` | 否 | 同 `keeper` | 无 | 同上 |
| `benchmark` | `gm` | 否 | `SaveSession` | 无 | 只记日志，不落盘 |

## 按域的实现要点

### 登录与角色

**登录杂务**。`objectCaching::GetCachableObject` 用第二参数作为 key 查 `BulkData.entries`，返回预编码 payload，未命中即 `Unknown`（`svc/login.rs:10`）。`authentication` 只有 `Ping`（回 FILETIME）和两个空操作（`svc/login.rs:21`）。

**角色选择与删除**。`character::GetCharactersToSelect` / `GetCharacterToSelect` 按 `accountID` 读 `character_`；删除采用“先标记、后删除”：`PrepareCharacterForDelete` 写 `deletePrepareDateTime`，`CancelCharacterDeletePrepare` 清空，`DeleteCharacter` 只在准备期已过（`BIOMASS_DELAY` 为 1 小时）后执行（`svc/login.rs:50`、`svc/login.rs:30`）。真正的 `SelectCharacterID` 不在这里，由 `conn` 处理。

**建号**。`CreateCharacter` 要求已登录（`session.user_id`），前 13 个参数是名字、血统、性别、祖先、学校、部门、领域、专长与五项属性点，第 14 个是外观 dict（`svc/charcreation.rs:317`）。`insert_character` 在一个事务里写 `character_`、`entity`、技能/物品、`chrEmployment`、`crpCharShares` 等；创建目录与外观数据来自 `chr*` 静态表，`GetCharCreationInfo` / `GetAppearanceInfo` 走进程内 `OnceLock` 缓存（`svc/charcreation.rs:181`）。`ValidateName` 做形状与重名校验（`svc/charcreation.rs:231`）。

**角色面板**。`charmgr` 的 `GetPublicInfo(3)` / `GetPrivateInfo` / `GetCharacterInfo` / `GetTopBounties` 都是只读；`AddToBounty` 是唯一写入：先 `wallet::move_cash` 扣付款人（`payee=None`，钱离开经济），成功后在 `bounties` upsert 并累加 `character_.bounty`（`svc/charsheet.rs:22`）。金额非有限、≤0 或给自己时静默返回 `None`。

**描述与备注**。`character::GetCharacterDescription` / `SetCharacterDescription` 读写 `character_`（`svc/charsheet.rs:54`）；`notes` 的 7 个方法读写 `chrNotes` / `chrOwnerNote`（`svc/notes.rs:7`）。

**技能与植入体**。`skillMgr` 是 bound 到角色的对象。`levels` 被市场、工业等模块复用，按 `entity_attributes` 的 `skillLevel` 取每个技能最大等级（`svc/skills.rs:25`）。`CharStartTrainingSkill` 校验物品归属、类别 `CATEGORY_SKILL`、等级 <5，然后把同角色其它 `FLAG_SKILL_IN_TRAINING` 全部改回 `FLAG_SKILL`，再把目标置为训练中（`svc/skills.rs:75`）。`CharAddImplant` 按 `CATEGORY_IMPLANT` 校验，boosters 用 `FLAG_BOOSTER`、普通植入体用 `FLAG_IMPLANT`，并把 `locationID` 改为角色（`svc/skills.rs:127`）；`RemoveImplantFromCharacter` 先删 `entity_attributes` 再删 `entity` 行（`svc/skills.rs:148`）。`GetEndOfTraining` 只按技能点与时间常数算出预计完成 FILETIME（`svc/skills.rs:63`、`svc/skills.rs:168`）；服务层没有升级结算路径。

**克隆**。`jumpCloneSvc` 的读方法返回空 rowset 或 0 价格（`svc/clones.rs:14`）；`InstallCloneInStation`、`DestroyInstalledClone`、`CloneJump`、`OfferShipCloneInstallation`、`AcceptShipCloneInstallation`、`CancelShipCloneInstallation` 都显式 `Unknown`，注释说明依赖尚未应用的迁移 `db/migrations/0012_insurance_clones_bounties.sql`（`svc/clones.rs:31`）。克隆的实际数据在 `medical`：克隆是角色拥有的 `GROUP_CLONE` 物品，`customInfo` 存家空间站；`replace_clone` 删旧插新（`svc/medical.rs:35`），`set_clone_type` 收费后替换（`svc/medical.rs:100`）。

**standing**。`standing2` 的读方法覆盖 NPC-NPC、角色对 NPC、我的全部 standing 与击杀权；`SetPlayerStanding` 写 `chrStandings`，`SetCorpStanding` 写 `ownerStandings` 且要求 Director（`svc/standing.rs:34`）。standing 统一 clamp 到 [-10,10]，写 0 表示删除该条（`svc/standing.rs:58`）。`GetStandingCompositions` 只把直接设置的 standing 当唯一组成，不做派生（`svc/standing.rs:94`）；`GetStandingTransactions` 永远空表（`svc/standing.rs:106`）。

**地点与地图**。`station` 只服务当前会话空间站：`GetStationItemBits` 组合 `staStations`、`staStationTypes`、`entity` 与 `staOperationServices` 的 service 位图（`svc/station.rs:36`）；`GetGuests` 读同站且 `accountID` 非空的角色（`svc/station.rs:67`）。`stationSvc` 提供 `GetStation/GetSolarSystem/GetConstellation/GetRegion/GetAllianceSystems`（`svc/station.rs:16`）。`map` 的附加层大多来自 `mapSolarSystems`/`staStations`/`entity`，其中 `GetStuckSystems`、`GetHistory`、`GetSolarSystemVisits`、`GetDeadspaceComplexMap`、`GetMyExtraMapInfo`、`GetSolarSystemLoadRatios` 是空占位（`svc/map.rs:34`）。`tutorialSvc` 只读 5 张教程表（`svc/tutorial.rs:7`）。

### 物品与舰船

**两个 inventory 服务**。`invbroker` 是 bound 服务，只做“把容器变成对象”：`GetInventory(containerID, ownerID)` 返回 `invcontainer` 引用 `[KIND_SPECIAL, containerID, ownerID]`，`GetInventoryFromId(Ex)(itemID)` 返回 `[KIND_ITEM, itemID, -1]`（`svc/inventory.rs:72`）。`invcontainer` 从绑定参数还原 `Container`（`svc/inventory.rs:125`），先交给 `moves::container_write` 处理写方法（`svc/inventory.rs:90`），再处理读方法：

| method | 行为 | 关键边界 |
|---|---|---|
| `List` | 按容器范围查 `entity`+`invTypes`+`invGroups` | 空间站结构要先过 `starbase::may(ViewPut)`（`svc/inventory.rs:96`） |
| `ListStations` | 按 owner 聚合 `locationID` 与件数 | 只统计 `60000000..64000000` 的空间站 ID |
| `ListStationItems` | 某站全部物品 | 含站内一层容器里的物品，排除 `FLAG_FACTORY_BLUEPRINT=36` |
| `ListStationBlueprintItems` | 同上但只取蓝图 | 左连 `invBlueprints` 追加 4 列 |
| `GetItem` | 单件物品 | 特殊容器取当前空间站 |
| `GetCapacity` | `(capacity, used)` | 特殊容器容量 9e15；硅筒容量可由 POS 提升（`svc/moonmining.rs:171`） |

容器范围定义在 `contents_scope`（`svc/inventory.rs:136`）：`10004` 机库（同站同 owner，排除工厂蓝图）、`10012` 军团市场（flag 62）、`10002` 全局（owner 全部，排除工厂蓝图）、`10011` 角色（角色 ID 为 location）；其余特殊容器返回空 rowset。`item_change` 生成 `OnItemChange(item, {ix: old})`，`IX_LOCATION_ID=3`、`IX_QUANTITY=7`（`svc/inventory.rs:375`）。

**物品移动**。`moves::container_write` 识别 `Add`、`MultiAdd`、`MergeItems`、`MultiMerge`、`StackAll`、`ReplaceCharges`（`svc/moves.rs:39`），`ship::AssembleShip` 走同一个 `run`（`svc/moves.rs:77`）。`run` 在一个 `ItemTxn` 里完成，提交后依次：通知物品事件、在太空时调 `concord::took_from`（偷窃）、`loot::clear_emptied`（清空太空箱）、`pvptrade::offers_changed`（交易窗口同步）、必要时推送装配属性变化（`svc/moves.rs:91`）。可达范围只有“当前停靠站的机库/一到两层容器”或“太空中的本船”（`svc/moves.rs:5`）。

**装配**。`fitting` 不是 service，是 `moves` 的装配规则：模块按 `category::MODULE` 找空闲槽位，充能按 `category::CHARGE` 合并或拆分，`set_online` 处理上线/下线并推送属性（`svc/fitting.rs:55`、`svc/fitting.rs:335`）。

**舰船与太空对象**。`ship`（`space::ship`）只实现 `AssembleShip`、`Drop`、`Scoop`、`ScoopDrone`；`Drop` 先尝试 `starbase::launch`（结构），否则交 `drones::launch`（`svc/space.rs:33`）。`beyonce` 只实现 `GetFormations`、`UpdateStateRequest`（重推 set state）、`GetGangState`、`GetRelativity` 与 7 个移动方法（`SetSpeedFraction`、`GotoDirection`、`GotoPoint`、`Stop`、`FollowBall`、`Orbit`、`WarpToStuff`）（`svc/space.rs:62`、`svc/space.rs:82`）。移动的几何、落点、跳跃与推进在 `implementation-world.md`。

**dogma 信息**。`dogma::dogma_im` 的 `ShipGetInfo` 取本船、角色与 11..34 flag 的装配物品；`CharGetInfo` 取角色与 7/61/88/89 flag 的技能/植入体；`ItemGetInfo` 取单件；三者都用 `computed_attributes` 算属性后组 `util.Row`（`svc/dogma.rs:96`、`svc/dogma.rs:111`、`svc/dogma.rs:120`）。`GetAttributeTypes` 返回以 `attributeName` 为键的 `IndexRowset`（`svc/dogma.rs:42`）；`GetSkillPrerequisites`、`CheckSendLocationInfo`、`LogAttribute` 是空实现（`svc/dogma.rs:27`）。

**锁定与模块**。`inflight::dogma_im` 的 `AddTarget` 只是登记；锁定完成由心跳发 `OnTarget("add")`。`Activate` 按模块与弹药的计算属性建循环，`Deactivate` 停止；目标、目标者、循环状态都在 `combat`/`WorldState` 里（`svc/inflight.rs:265`）。

**蓝图、制造、精炼、修理、保险**。
- `factory` 只读：蓝图属性来自 `invBlueprintTypes` + `invBlueprints`，无 `invBlueprints` 行时按原图 0/0、无限 runs 处理（`svc/factory.rs:16`、`svc/factory.rs:69`）。
- `ramProxy` 的 `InstallJob` 锁 assembly line 行，校验活动类型、射程、安全等级、蓝图归属/位置、拷贝与 runs 限制；蓝图在堆叠中会先拆出 1 个 singleton（`svc/ram.rs:420`、`svc/ram.rs:451`）。公司任务与 `UpdateAssemblyLineConfigurations` 未支持（`svc/ram.rs:437`、`svc/ram.rs:124`）。
- `reprocessingSvc` 的产出率 = 站点效率 + 0.375×(1+0.02×Refining)×(1+0.04×RefineryEfficiency)，上限 1；小行星类不加 Scrapmetal，其它类再乘 `(1+0.05×Scrapmetal)`；站点抽成 `max(0, stationsTake − 0.0075×standing)`（`svc/reprocessing.rs:85`、`svc/reprocessing.rs:123`、`svc/reprocessing.rs:129`）。
- `repairSvc` 的修理报价恒为 0（无定价数据），`RepairItems` 直接删 `damage` 属性；`UnasembleItem(s)` 只允许拆空且非当前船、位置在本站的 singleton 物品，成功后推 `OnItemChange`（`svc/repair.rs:86`、`svc/repair.rs:97`）。
- `insuranceSvc` 由客户端报价、服务端存合同：保费为基价的 n×5% 时赔付比例为 `0.4+0.1n`（n=1..6，即 50%..100%）；只保本站、本人/本团、已装配且无现有合同的船，合同 12 周（`svc/insurance.rs:60`、`svc/insurance.rs:69`）。

### 市场与钱包

**市场查询**。`market::market_proxy` 全部只读：`GetMarketGroups` 用递归 CTE 把 `invMarketGroups` 按 parent 分桶并附 `published` 类型；`GetOrders` 只看当前 region、`orderState=0`、`volRemaining>0`，按 `bid` 分买卖两表；`GetStationAsks`/`GetSystemAsks`/`GetRegionBest` 用 `DISTINCT ON (typeID)` 取各范围最低卖价；`GetNewPriceHistory` 从 `market_transactions` 按天聚合，无成交时用 `invTypes.basePrice/portionSize` 造当天一条（`svc/market.rs:54`、`svc/market.rs:180`、`svc/market.rs:250`、`svc/market.rs:286`）。`GetOldPriceHistory` 返回 `(None, [])` 占位（`svc/market.rs:18`）；`GetCharSkillLimits` 显式 `Unknown`，注释称客户端没有调用点（`svc/market.rs:33`）。所有订单 rowset 带 `columns`，因为市场 UI 读 `bids.columns.index('jumps')`（`svc/rows.rs:37`）。

**下单/改单/撤单**。`marketProxy` 的 `PlaceCharOrder`/`CancelCharOrder`/`ModifyCharOrder` 转给 `trade::market_write`（`svc/market.rs:30`）。`trade::transact` 开独立连接与 `ItemTxn`，提交后统一发物品、钱包、订单通知（`svc/trade.rs:121`、`svc/trade.rs:152`）。规则：
- 先吃对手单，成交价用挂单方价格；`duration=0` 必须全成，否则整单拒绝；
- 买单剩余部分冻结 escrow 并挂出，卖单剩余部分把物品留在机库并挂出；
- 卖单必须本人、本站机库、flag 4、数量足够；已装配船必须先打包，容器必须先清空；
- NPC 订单（`charID < 1e8`）不同于玩家单：NPC 卖单不交税、不记卖家流水；NPC 买单不收货，卖给它的物品离开经济；
- 公司订单直接拒绝（`svc/trade.rs:201`）。
- 手续费：broker 1%×(1−0.05×BrokerRelations)，最低 100 ISK；交易税 1%×(1−0.1×Accounting)，低于 0.01 不收（`svc/trade.rs:429`、`svc/trade.rs:439`）。

**钱包**。`account` 提供现金、keyMap、refTypes、journal；`GiveCash` 与 `GiveCashFromCorpAccount` 走 `move_cash`，后者要求 Accountant 角色，reason 截断到 40 字符（`svc/wallet.rs:389`）。`billMgr` 先 `UPDATE ... SET paid=1 ... RETURNING` 抢锁，支付失败再释放，避免重复支付；军团账单要求 Accountant（`svc/wallet.rs:78`、`svc/wallet.rs:60`）。流水查询按 `accountKey`、日期、refType、refID 过滤，单次最多 `JOURNAL_BATCH=25` 条，可按 `reverse` 反转顺序（`svc/wallet.rs:208`、`svc/wallet.rs:244`）。

**点对点交易**。`trademgr::InitiateTrade(other, war?)` 要求双方同站、非自己，并在 `WorldState.trades` 建会话；`tradeSession` 是 bound 到交易容器 ID 的对象，每次调用都校验调用者是交易方且仍在原站，否则回 “That trade is over.”（`svc/pvptrade.rs:139`）。`Add`/`MultiAdd` 把机库物品移进交易容器，可拆分数量；`OfferMoney` 只记录金额。`ToggleAccept` 在双方都接受时同步调用 `complete`：把各自报价移进对方机库并改 owner、按 `REF_PLAYER_TRADING` 双向转账、销毁交易容器，然后广播 `TradeComplete`；失败则重置接受状态、保留交易（`svc/pvptrade.rs:223`、`svc/pvptrade.rs:244`）。CEO 交易（`war` 非空）要求双方都是未结束战争的现任 CEO，成交后调用 `war::surrender`（`svc/pvptrade.rs:114`、`svc/pvptrade.rs:298`）。

### 公司与联盟

**公司创建与入团**。`membership::corp_registry` 负责 `AddCorporation`（收 1,599,800 ISK 注册费、要求 Corporation Management、发 1000 股、给 CEO 全部角色位 `ALL_ROLES`）、申请/还价/接受/拒绝、踢人与成员更新（`svc/membership.rs:50`、`svc/membership.rs:26`、`svc/membership.rs:32`）。任何改变所属公司的操作都通过 `world::Move::Affiliation` 让连接重读身份（`svc/membership.rs:1`）。

**公司读取**。`corpRegistry` 的 `corp` handler 提供 `GetCorporation`、`GetMember(s)`、`GetRoles`、`GetRoleGroups`、`GetSharesByShareholder`、`GetLockedItemLocations` 等（`svc/corp.rs:134`）。`GetTitles` 与 `GetMemberIDsWithMoreThanAvgShares` 是空结果（`svc/corp.rs:149`、`svc/corp.rs:152`）。`corpmgr` 另提供公开信息、资产清单（只允许查自己公司，`own_corp` 在 `svc/corp.rs:66`）、租用项与 `AuditMember`；审计两张表永远为空（`svc/corp.rs:57`）。

**办公室与医疗舱**。`corpStationMgr` 的 `RentOffice` 先抢占 `crpOffices` 唯一行并建 office item，再向军团钱包收费，失败则回滚删除；要求 Director、玩家公司、报价与当前租金误差 ≤0.5 ISK（`svc/corp.rs:734`）。`SetHomeStation`/`SetCloneTypeID` 委托 `medical`（`svc/corp.rs:634`）。

**成员列表提供者**。`corpMembers` 实现 `util.SparseRowset` 的 `Fetch(start,count)` / `FetchByKey(pks)`，只允许本公司成员读取（`svc/corp.rs:272`）。

**联盟**。`allianceRegistry` 由 CEO 创立（10 亿 ISK，`svc/alliance.rs:37`）或申请加入；执行人公司的董事接受/拒绝；接受后延迟生效（配置 `allianceJoinDelaySeconds`）；成员公司各推举一名 executor，得票最多者领导；执行人董事设置关系（NAP/Friend/Competitor/Enemy，1..4）并发动战争（`svc/alliance.rs:75`、`svc/alliance.rs:261`）。每 14 天 CONCORD 按成员公司数收维护费（`svc/alliance.rs:44`）。

**战争**。`warRegistry` 的 `GetWars` 按宣战方/应战方查 `crpWars`，`GetCostOfStartingAWarAgainst` 基础 200 万，受害方每多一场非共同战争加一次（`svc/war.rs:51`、`svc/war.rs:100`）。无联盟公司的 `RetractWar`/`ChangeMutualWarFlag` 由现任 CEO 决定，且公司不能属于联盟（`svc/war.rs:75`）。战争状态在内存中供 CONCORD 使用，心跳与每次变更后重载（`svc/war.rs:10`）。

**投票**。`votes::corp_registry` 的读方法先校验 `viewer`：本公司董事或持股人；`InsertVoteCase` 提议、`InsertVote` 记录每股一票（只有持股人能投）、`UpdateSanctionedAction` 让 CEO 在一周内把制裁付诸实施、`ResignFromCEO` 移交/关闭公司（`svc/votes.rs:56`、`svc/votes.rs:87`）。计票在 `close_votes` 里按 `crpCharShares` 加权、按持股总和最高者胜出，由心跳推进（`svc/votes.rs:466`）。

**舰队**。`gangsta` 的舰队完全在内存：无舰队时由邀请创建，之后邀请/接受/离开/踢人/解散/移交/夺回领导权；邀请会先检查双方战争并警告，邀请方可带 `ignoreWars` 再发（`svc/gang.rs:76`、`svc/gang.rs:116`、`svc/gang.rs:1`）。

### 社交与聊天

**LSC 频道**。`chat::lsc` 同时承载聊天频道与邮件：
- 频道成员存 `channelChars`，ACL 存 `channelMods`；操作者判定是 owner 或 `mode >= 7`（`OPERATOR_TEST`，`svc/chat.rs:19`）。
- `SendMessage` 只发给世界状态里“已加入该频道”的连接，且发言者必须在成员表中，否则只 `warn!`（`svc/chat.rs:57`）。
- `CreateChannel` 支持 `joinExisting`：按 `comparisonKey=lower(name)` 找非临时频道；新建者角色为 `CHTMODE_CREATOR=15`，加入者为 `CHTMODE_CONVERSATIONALIST=3`（`svc/chat.rs:793`）。
- `Configure`/`RenameChannel`/`SetChannelMOTD`/`DestroyChannel` 都只允许 owner；`SetChannelMOTD` 允许操作者；`AccessControl` 允许 owner 或操作者，对 `channelID == charID` 的“自己的邮箱”即联系人屏蔽（`svc/chat.rs:842`、`svc/chat.rs:874`）。
- `Invite` 通过 `world.call` 反向调用对方客户端的 `LSC.ChatInvite`，等待 10 分钟；拒绝以 `OnRemoteMessage(reason,{char,channel})` 回给邀请者（`svc/chat.rs:193`）。
- `Page` 是邮件：收件人可以是角色、公司、联盟或 `mailingList != 0` 的频道；主题截 150 字符、正文 8000 字符；附件不存储（`svc/chat.rs:153`）。`deliver` 写 `evemail` + `evemailDetails` 并推 `OnMessage`（`svc/chat.rs:236`）。
- 邮件读取 `GetMyMessages` 合并“自己的邮箱”和订阅的邮件列表频道（`svc/chat.rs:125`）。

**书签与凭证**。`bookmark` 读写 `bookmarks`；把书签做成凭证时，停靠状态放机库、太空放货舱，生成 `typeBookmark=51` 的物品与 `bookmarkVouchers` 行（`svc/bookmark.rs:66`）。`voucher::GetObject` 返回 `voucher.Bookmark` 实例给客户端信息窗（`svc/bookmark.rs:129`）。

**客服单**。`petitioner` 覆盖创建、列表、队列、认领/取消认领/升级、关闭/取消/删除、消息与日志；`GetClaimedPetitions`/`GetPetitionQueue` 需要 petitionee 身份（GM 角色位），`MarkAsRead` 只允许请愿者或认领人（`svc/petition.rs:83`、`svc/petition.rs:95`）。行里附在线状态与 `petitionProperties`（`svc/petition.rs:160`）。

**查找与在线状态**。`lookupSvc` 的所有结果形状都是 `[name, id, typeID]`，因为客户端按列名与位置混读；`exact` 控制等值/包含，`players_only` 用 `ID >= 100000000` 过滤 NPC，最多 500 条（`svc/lookup.rs:18`、`svc/lookup.rs:74`）。`onlineStatus` 完全查 `WorldState`（`svc/onlinestatus.rs:8`）。

### 任务与代理

**代理**。`agentMgr` 是 bound 服务，绑定参数第一个就是 agentID（`agent_of`，`svc/agents.rs:41`）。`GetAgents` 一次返回全部 `agtAgents` 左连 `character_` 取血统（`svc/agents.rs:68`）；`GetInfoServiceDetails` 返回 `util.KeyVal`，LP 恒为 0、services 为空（`svc/agents.rs:53`）；`GetOfferJournalInfo` 返回 `None`（`svc/agents.rs:29`）。`DoAction` 的 action 可以是整数或文本（客户端链接会把 ID 当字符串回传，`svc/agents.rs:47`）。

**代理任务**。`agent_missions` 不是独立 service，由 `agentMgr` 调用：
- `conversation` 按 `(action, 当前开放任务)` 分派：`ASK` 生成报价、`ACCEPT` 接受、`DECLINE` 关闭、`COMPLETE` 完成、`QUIT_MISSION` 放弃，其余显示状态（`svc/agent_missions.rs:215`）。
- 报价按代理 division 决定类型：14/5 采矿、12/16/18 贸易、6/9/10/19/21 遭遇、其余快递；奖励随等级、质量、跳数/货量变化，写入 `agtCharMissions` 并设过期时间（`svc/agent_missions.rs:194`、`svc/agent_missions.rs:320`）。
- 任务状态全部落在 `agtCharMissions.state`：`OFFERED`、`ACCEPTED`、`CLEARED`、`COMPLETED`、`DECLINED`、`QUIT`、`EXPIRED`（`svc/agent_missions.rs:40`）；`chrMissionState` 只在删号时被清理（`svc/login.rs:131`）。

**玩家快递任务**。`missionMgr` 只处理 courier/escrow：`CreateCourierMission` 把发起人机库物品装进 `TYPE_PLASTIC_WRAP` 包裹（owner 为 system），按体积上限校验、排除已包装/锁定物品、预扣奖励；`AcceptCourierMission`/`DeliverCourierPackage` 移包裹并结算奖励与押金；`CancelMission` 退包；每次调用先 `settle_lapsed` 处理过期任务（`svc/missions.rs:190`、`svc/missions.rs:70`、`svc/missions.rs:452`）。`GetManifest` 列包裹内容（`svc/missions.rs:175`）。

### GM

`slash::SlashCmd` 先检查 `session.role & (ROLE_GML|ROLE_LEGIONEER)`，非 GM 直接 `CustomError`（`svc/gm.rs:50`）。支持的命令：`/help`、`/create`、`/giveisk`、`/giveskill`、`/setstanding`、`/spawn`、`/tr`、`/bots`（`svc/gm.rs:58`）。类型/技能可写 ID 或名字，`find_type` 先精确后前缀匹配（`svc/gm.rs:88`）。`/create` 停靠时进机库、太空时进货舱，`ItemTxn` 提交后推物品事件（`svc/gm.rs:110`）；`/giveisk` 用 `refType=25`（GM 杂项）直接 `wallet::post` 并推 `OnAccountChange`（`svc/gm.rs:130`）；`/tr` 通过 `Move::Teleport` 排队传送，由连接任务落地（`svc/gm.rs:240`、`svc/gm.rs:259`）。

`keeper`/`dungeon` 是地牢编辑器占位：`GetLevelEditor` 返回 `None`，`DEGet*` 空列表，编辑类命令统一 `CustomError`（`svc/gm.rs:265`）。`benchmark::SaveSession` 只记一条日志（`svc/gm.rs:277`）。

### POS 与工业

**发射、锚定、上线**。`starbase::launch` 把货舱里的结构发射到太空（`ship.Drop` 调用），`anchor` 校验锚定位置、离月距离、安全等级（≥0.8 禁止）、与控制塔距离，`online` 消耗燃料并写入 `posStructures` 状态（`svc/starbase.rs:78`、`svc/starbase.rs:194`、`svc/starbase.rs:327`）。一个控制塔只对应一个卫星；非塔结构必须挂在同 owner 的在线塔上并占其 CPU/功率（`svc/starbase.rs:7`）。

**燃料与主权**。控制塔每个 `posControlTowerPeriod` 烧一次燃料：在线资源全量、CPU/功率按结构消耗比例；联盟拥有主权时打 75 折。燃料不足则塔与结构一起离线（`svc/starbase.rs:817`）。无 NPC 阵营的星系里，声明并在线塔最多的联盟获得主权，需持续 `RMR_SOV_CLAIM_DELAY`，平局维持原状（`svc/starbase.rs:909`）。

**POS 窗口**。`posMgr` 提供控制塔燃料需求、卫星、claim、哨戒设置、密码、权限、月矿处理信息；`SetTowerPassword`/`SetShipPassword` 分别写塔密码与舰船密码；`LinkResourceForTower`/`ChangeStructureProvisionType` 需 `may_configure`（Director + StarbaseConfig）（`svc/starbase.rs:1002`、`svc/starbase.rs:1133`）。`RunMoonProcessCycleforTower` 返回 `None`，周期实际由心跳在燃料结算时推进（`svc/starbase.rs:1098`）。

**月矿与反应**。`moonmining` 是 `posMgr`/`invcontainer` 的支撑模块：采矿阵列按卫星产出、硅筒按设定存一种类型、反应堆读取 `invTypeReactions` 与 `posLinks` 输入输出；每次塔付燃料时在线结构跑一个周期（`svc/moonmining.rs:1`、`svc/moonmining.rs:277`）。数据库没有卫星矿物表，矿物由 moonID 与安全等级确定性抽取（`svc/moonmining.rs:62`），这是明确的“零售数据缺口”。

### 其它

- `alert`：`SendClientStackTraceAlert` 用客户端栈哈希去重，首次出现打 `warn!` 带 user/char 与完整栈；`BeanCount`/`BeanDelivery` 只维护进程内计数（`svc/alert.rs:9`）。
- `config`：按 `GetMulti*Ex` 批量返回 `(header, lines)`；`GetMapObjects`/`GetMapConnections` 读 `mapDenormalize` 与跳线表；`GetUnits`、`GetCelestialStatistic`、`GetStationSolarSystemsByOwner` 读对应静态表（`svc/config.rs:9`）。
- `languageSvc`：只登记英语，语言包与文本组为空（`svc/language.rs:9`）。
- `machoNet`：`GetClusterSessionStatistics` 把 `WorldState` 的太空/停靠人数按 `solarSystemID - 30000000` 编码（`svc/machonet.rs:12`）。
- `entity`（无人机）：`CmdEngage/CmdMine/CmdMineRepeatedly/CmdReturnHome/CmdReturnBay/CmdAbandonDrone/CmdRelinquishControl`；`CmdDelegateControl`/`CmdUnanchor` 明确拒绝（`crates/eve-server/src/drones.rs:268`）。目标与归属都在 park 里校验。
- `aggressionMgr`：`CheckLootRightExceptions(canID)` 查太空箱 owner 与其公司，判断拿取是否算偷窃（`crates/eve-server/src/concord.rs:233`）。

**总表里以「等」省略的方法**。下面这些 handler 的 match 分支较多，完整清单如下：

| handler | 完整 method |
|---|---|
| `config` | `GetOwnersEx`/`GetMultiOwnersEx`、`GetLocationsEx`/`GetMultiLocationsEx`、`GetCorpTickerNamesEx`/`GetMultiCorpTickerNamesEx`、`GetAllianceShortNamesEx`/`GetMultiAllianceShortNamesEx`、`GetInvTypesEx`/`GetMultiInvTypesEx`、`GetInvGroupsEx`/`GetMultiInvGroupsEx`、`GetInvCategoriesEx`/`GetMultiInvCategoriesEx`、`GetInvMetaGroupsEx`/`GetMultiInvMetaGroupsEx`、`GetBlueprintTypeEx`/`GetMultiBlueprintTypeEx`、`GetGraphicsEx`/`GetMultiGraphicsEx`、`GetAssemblyLineTypeEx`/`GetMultiAssemblyLineTypeEx`、`GetMapObjects`、`GetMapConnections`、`GetMap`、`GetMapLandmarks`、`SetMapLandmarks`、`GetCelestialStatistic`、`GetUnits`、`GetStationSolarSystemsByOwner` |
| `allianceRegistry` | `GetAlliance`、`GetRankedAlliances`、`GetMembers`、`GetApplications`、`UpdateApplication`、`DeclareExecutorSupport`、`DeleteMember`、`UpdateAlliance`、`GetRelationships`、`SetRelationship`、`DeleteRelationship`、`DeclareWarAgainst`、`RetractWar`、`ChangeMutualWarFlag`、`GetBills`、`GetBillsReceivable`、`GetBillBalance`、`PayBill` |
| `corpRegistry`（votes） | `GetVoteCasesByCorporation`、`GetVoteCaseOptions`、`GetVotes`、`GetSanctionedActionsByCorporation`、`CanViewVotes`、`InsertVoteCase`、`InsertVote`、`UpdateSanctionedAction`、`MemberCanRunForCEO`、`ResignFromCEO` |
| `corpRegistry`（corp） | `GetCorporation`、`GetEveOwners`、`GetMember`、`GetRoles`、`GetRoleGroups`、`GetSharesByShareholder`、`GetInfoWindowDataForChar`、`GetTitles`、`GetLockedItemLocations`、`GetMemberIDsWithMoreThanAvgShares`、`GetMembers` |
| `LSC` | `JoinChannels`、`GetChannels`、`GetMembers`、`LeaveChannels`、`LeaveChannel`、`SendMessage`、`GetMyMessages`、`MarkMessagesRead`、`DeleteMessages`、`CreateChannel`、`Configure`、`RenameChannel`、`SetChannelMOTD`、`DestroyChannel`、`ForgetChannel`、`AccessControl`、`GetMessageDetails`、`Invite`、`Page` |
| `petitioner` | `GetUnreadMessages`、`MarkAsRead`、`GetMyPetitions`、`GetClaimedPetitions`、`GetPetitionQueue`、`GetPetition`、`GetPetitionMessages`、`GetPetitionLog`、`GetCategories`、`GetCategoryName`、`GetCategoryProperties`、`GetQueues`、`MayPetition`、`CreatePetition`、`PetitionerChat`、`PetitioneeChat`、`ClaimPetition`、`UnClaimPetition`、`EscalatePetition`、`ClosePetition`、`CancelPetition`、`DeletePetition` |
| `gangsta` | `GetGangInfoForChar`、`InviteCharacter`、`AcceptInvitation`、`RejectInvitation`、`LeaveGang`、`KickMember`、`DisbandGang`、`MakeLeader`、`ResignLeadership`、`ClaimLeadership` |
| `lookupSvc` | `LookupOwners`、`LookupPCOwners`、`LookupNoneNPCAccountOwners`、`LookupCharacters`、`LookupCorporations`、`LookupPlayerCorporations`、`LookupCorporationTickers`、`LookupCorporationsOrAlliances`、`LookupStations`、`LookupFactions`、`LookupLocationsByGroup` |
| `marketProxy`（market） | `GetMarketGroups`、`GetOrders`、`GetOldPriceHistory`、`GetNewPriceHistory`、`GetStationAsks`、`GetSystemAsks`、`GetRegionBest`、`GetCharOrders`、`GetCorporationOrders`、`PlaceCharOrder`、`CancelCharOrder`、`ModifyCharOrder`、`GetCharSkillLimits` |
| `corpmgr` | `GetCorporations`、`GetPublicInfo`、`GetCorporationIDForCharacter`、`GetCorporationWallet`、`GetCorporationStations`、`GetItemsRented`、`GetAssetInventory`、`GetAssetInventoryForLocation`、`AuditMember` |
| `corpStationMgr` | `GetCorporateStationInfo`、`GetQuoteForRentingAnOffice`、`DoesPlayersCorpHaveJunkAtStation`、`GetQuoteForGettingCorpJunkBack`、`DoStandingCheckForStationService`、`GetPotentialHomeStations`、`AreAnyFactorySlotsAvailableForRenting`、`AreAnyResearchFacilitySlotsAvailableForRenting`、`GetQuoteForRentingAFactorySlot`、`GetQuoteForRentingAResearchFacilitySlot`、`SetCloneTypeID`、`SetHomeStation`、`RentOffice` |
| `keeper`/`dungeon` | `GetLevelEditor`、`ActivateAccelerationGate`、`DEGetDungeons`、`DEGetFactions`、`DEGetRooms`、`EditObject`、`CopyObject`、`RemoveObject` |



## 跨模块约定

### 物品事务与通知

- 所有物品写入都走 `crate::items::ItemTxn`：`begin` → 操作 → `commit()` 返回 `Vec<Value>` 事件；调用方必须 `items::notify(ctx.world, ctx.client_id, events)`（`svc/moves.rs:94`、`svc/trade.rs:126`、`svc/gm.rs:120`）。
- 失败统一转成 `Outcome`：`MoveError::Refused(why)` → `Outcome::custom(why)`，`MoveError::Db` 记日志后回通用错误（`svc/moves.rs:118`）。
- 单件“变化”用 `rows::change(header, old, new)` 生成客户端 `On*Changed` 的 `{column: (old,new)}`；新增/删除带全列（`svc/rows.rs:64`）。物品用 `inventory::item_change`，索引是列位置（`svc/inventory.rs:381`）。
- 移动物品后还要做跨系统副作用：太空偷窃判定、清空箱、交易窗口刷新、装配属性重算（`svc/moves.rs:104`）。

### 钱包 `post` 与 `Entry`

- 单边记账用 `wallet::post(&tx, owner, delta, &Entry)`：先 `SELECT ... FOR UPDATE` 锁余额，拒绝扣成负数，更新 `character_` 或 `corporation.balance`，再写一条 `market_journal`（`accountKey=1000`）（`svc/wallet.rs:499`、`svc/wallet.rs:534`）。
- `Entry { ref_type, payer, payee, arg_id1, reason }` 决定流水两侧与备注；`payee=0` 表示钱离开经济（`svc/wallet.rs:487`）。
- 双方转账用 `move_cash(db_url, Payment)`：自己开连接与事务，按 owner ID 排序后逐边 `post`，避免两笔反向转账死锁（`svc/wallet.rs:473`）。
- `refType` 常量集中在各模块：市场 2/42/46/54、赏金 16、保险 19、办公室租金 13、联盟注册 48、战争费 49、联盟维护 50、克隆 8、GM 25。

### standing

- 角色对角色/公司：`chrStandings(characterID,toID,standing)`；公司对外：`ownerStandings(fromID,toID,standing,reason,setAt)`；NPC 对角色：`chrNPCStandings(characterID,fromID,standing)`。
- 写 0 即删除；范围 clamp [-10,10]；公司 standing 要 Director，个人不要（`svc/standing.rs:58`）。
- 读取时把“prime”（owner 行）与 standing 分开发，因为客户端 `cfg.eveowners.Hint` 需要 owner 行而不是裸 ID（`svc/standing.rs:114`）。

### role 检查

- 会话位：`ctx.session.role`；GM 判定 `role & (8|262144)`（`svc/gm.rs:50`），配置侧 `GM_ROLES = 8|16|256|262144`（`crates/eve-server/src/config.rs:9`）。
- 军团位：`ctx.session.has_corp_role(mask)`（`crates/eve-server/src/session.rs:67`）。常用：`CORP_ROLE_DIRECTOR=1`、`CORP_ROLE_ACCOUNTANT=256`；POS 配置另有 `corpRoleStarbaseConfig = 1<<53`（`svc/starbase.rs:54`）。
- 典型拒绝：军团账单/公司账户转账要 Accountant（`svc/wallet.rs:62`、`svc/wallet.rs:416`）；办公室租赁、公司 standing、投票要 Director（`svc/corp.rs:742`、`svc/standing.rs:40`、`svc/votes.rs:88`）；POS 配置要 Director + StarbaseConfig（`svc/starbase.rs:1133`）。

### bulk 与 bound 的用法

- `bulk` 只服务登录期静态对象：`objectCaching::GetCachableObject` 按 key 返回 `BulkData` 预编码 payload（`svc/login.rs:10`）；静态数据查询走 `config` 等服务直查数据库。
- `bound` 表示“客户端先 bind 再调用”：服务端在 bind 时把参数编码进对象 ID，之后每次调用由 `parse_call` 还原 service 与参数。哪些服务 bound 由 `registry()` 的 `add_bound` 决定，不能由客户端任意指定。
- 绑定对象 ID 里的 node 号来自 `ctx.node_id`；本实现所有对象都解析到当前节点（`MachoResolveObject` 返回本节点），不做跨节点转发（`services.rs:262`）。

## 与数据库的交互

| 表 | 使用方（模块） | 用途 |
|---|---|---|
| `entity` | inventory、moves、fitting、skills、medical、missions、repair、insurance、ram、gm、pvptrade、starbase | 物品主表：位置、flag、数量、singleton、customInfo |
| `entity_attributes` | skills、repair | 物品实例属性（技能等级、伤害） |
| `invTypes`、`invGroups`、`invCategories`、`invMetaGroups` | config、inventory、market、factory、ram、reprocessing、dogma、gm | 类型/分组/分类静态数据 |
| `invBlueprints`、`invBlueprintTypes` | inventory、factory、ram、missions | 蓝图实例与蓝图类型 |
| `invMarketGroups` | market | 市场树与 `hasTypes` |
| `invTypeReactions` | moonmining | 反应输入/输出 |
| `TL2MaterialsForTypeWithActivity` | factory、ram、reprocessing | 制造/科研/精炼配方 |
| `dgmAttributeTypes`、`dgmTypeAttribs`、`dgmTypeAttributes`、`dgmEffects` | dogma、inflight、skills、starbase、moonmining、gm、repair | 属性/效果目录与类型默认值 |
| `market_orders` | market、trade | 买卖挂单、escrow、状态 |
| `market_transactions` | market、trade | 成交记录与历史价格 |
| `market_journal` | wallet、trade、missions、insurance、gm | 钱包流水（所有收支） |
| `market_keyMap`、`market_refTypes` | wallet | 账户类型与流水 refType 名称 |
| `billsReceivable`、`billTypes` | wallet、alliance、war | 账单、租金/战争/联盟维护费 |
| `character_` | 几乎所有角色相关模块 | 角色主表：公司、余额、空间站、在线相关字段 |
| `corporation` | corp、membership、alliance、war、votes、wallet、chat、standings | 公司主表：CEO、executor、余额、税率 |
| `alliances`、`allianceMembers`、`allianceApplications`、`allianceRelationships` | alliance、war、gang | 联盟、成员、申请、关系 |
| `crpApplications` | membership | 入团申请 |
| `crpCharShares` | corp、membership、votes | 股份与股东 |
| `crpOffices` | corp | 办公室租赁 |
| `crpWars` | war | 战争 |
| `crpVoteCases`、`crpVoteOptions`、`crpVotes`、`crpSanctionedActions` | votes | 投票与制裁 |
| `crpItemLocks` | votes、missions | 投票锁定的物品 |
| `crpNPCCorporations`、`crpNPCDivisions` | corp、agent_missions、war | NPC 公司与部门 |
| `chrStandings`、`ownerStandings`、`chrNPCStandings`、`npcStandings` | standing、agent_missions、reprocessing、gm | 角色/公司/NPC standing |
| `chrKillRights` | standing | 击杀权 |
| `chrNotes`、`chrOwnerNote` | notes | 个人笔记与联系人备注 |
| `chrCorporationRoles`、`chrEmployment` | membership、corp、charcreation、votes | 军团角色位与雇佣记录 |
| `rentalInfo` | corp | 公司租用的办公室/工厂槽位 |
| `chrBloodlines`、`chrRaces`、`chrFactions`、`chrAncestries`、`chrSchools` 等 `chr*` 外观/出身表 | charcreation、charsheet、corp | 建号目录与角色信息 |
| `chrAgentLoyalty`、`chrAgentResearch`、`chrMissionState`、`chrOffers` | login | 只在删号事务里清空（`svc/login.rs:131`） |
| `agtAgents`、`agtCharMissions` | agents、agent_missions | 代理与角色任务 |
| `courierMissions` | missions | 玩家快递任务 |
| `channels`、`channelChars`、`channelMods` | chat | 频道、成员、ACL |
| `evemail`、`evemailDetails`、`evemailMimeType` | chat | 邮件与正文 |
| `bookmarks`、`bookmarkVouchers` | bookmark、voucher | 书签与凭证 |
| `petitions`、`petitionMessages`、`petitionLog`、`petitionCategories`、`petitionCategoryProperties`、`petitionProperties`、`petitionQueues` | petition | 客服单 |
| `posStructures`、`posLinks`、`invControlTowerResources` | starbase、moonmining | POS 结构与连接、燃料需求 |
| `ramAssemblyLines`、`ramAssemblyLineStations`、`ramAssemblyLineTypes`、`ramAssemblyLineTypeDetailPerCategory/Group`、`ramJobs` | ram | 生产线与任务 |
| `insuranceContracts` | insurance | 保险合同 |
| `bounties` | charsheet | 悬赏 |
| `tutorials`、`tutorial_pages`、`tutorial_criteria`、`tutorials_criterias`、`tutorial_page_criteria` | tutorial | 教程 |
| `staStations`、`staStationTypes`、`staOperations`、`staOperationServices`、`staServices` | station、corp、market、trade、missions、insurance、RAM、config | 空间站与服务 |
| `mapSolarSystems`、`mapConstellations`、`mapRegions`、`mapDenormalize`、`mapJumps`、`map*Jumps`、`mapCelestialStatistics`、`mapLandmarks` | config、map、station、space、mission、gm | 星图与天体 |
| `eveStaticOwners`、`eveStaticLocations`、`eveGraphics`、`eveUnits`、`eveNames`、`eveConstants` | config、corp、standing、lookup | 静态名称/图形/常量 |
| `account` | login、charcreation、petition | 账号与登录 |

## 已知限制/未实现方法

以下均由代码直接证实，不含推测：

- **克隆**：`InstallCloneInStation`、`DestroyInstalledClone`、`CloneJump`、`OfferShipCloneInstallation`、`AcceptShipCloneInstallation`、`CancelShipCloneInstallation` 回 `ServiceNotFound`，原因写在错误文本里：缺少 `db/migrations/0012_insurance_clones_bounties.sql`（`svc/clones.rs:31`）。
- **公司钱包对象**：`corpmgr::GetCorporationWallet` 需要绑定公司钱包对象，当前回 `Unknown`（`svc/corp.rs:26`）。
- **市场**：`GetCharSkillLimits` 显式 `Unknown`；`GetOldPriceHistory` 返回空占位；公司订单下单被拒绝（`svc/market.rs:33`、`svc/market.rs:18`、`svc/trade.rs:201`）。
- **工业**：公司任务不支持（`svc/ram.rs:437`）；`UpdateAssemblyLineConfigurations` 永远 `RamConfigAssemblyLinesAccessDenied`（`svc/ram.rs:124`）。
- **POS**：`RunMoonProcessCycleforTower` 什么都不做，月矿周期只在燃料结算时推进（`svc/starbase.rs:1098`）；卫星矿物由 moonID 伪随机生成，因为数据库没有卫星矿物分布表（`svc/moonmining.rs:12`）。
- **聊天邮件**：附件不存储，只发正文（`svc/chat.rs:160`）；语言只有英语（`svc/language.rs:1`）。
- **军团审计/标题**：`AuditMember` 两张表恒空、`GetTitles` 空 `IndexRowset`、`GetMemberIDsWithMoreThanAvgShares` 空列表、`GetCorpInfo` 空 rowset（`svc/corp.rs:57`、`svc/corp.rs:149`、`svc/corp.rs:152`、`svc/corp.rs:127`）。
- **军团设施**：`DoesPlayersCorpHaveJunkAtStation` 恒 0、`GetQuoteForGettingCorpJunkBack` 恒 0、`DoStandingCheckForStationService` 恒 `None`、工厂/研究槽位可用性恒 0 且报价恒 0（`svc/corp.rs:621`）。
- **standing 历史**：`GetStandingTransactions` 恒空（`svc/standing.rs:106`）。
- **地图附加层**：`GetStuckSystems`、`GetHistory`、`GetSolarSystemVisits`、`GetDeadspaceComplexMap`、`GetMyExtraMapInfo`、`GetSolarSystemLoadRatios` 为空占位（`svc/map.rs:34`）。
- **代理**：`GetOfferJournalInfo` 返回 `None`（没有 LP 商店）；`GetInfoServiceDetails` 的 `loyaltyPoints` 恒 0、`services` 恒空（`svc/agents.rs:29`、`svc/agents.rs:62`）。
- **修理**：没有修理定价数据，`costToRepairOneUnitOfDamage` 恒 0（`svc/repair.rs:6`）。
- **GM 地牢工具**：没有地牢，`keeper`/`dungeon` 的编辑器与对象操作全部为空或拒绝（`svc/gm.rs:263`）。
- **benchmark**：`SaveSession` 不落盘，只记日志（`svc/gm.rs:277`）。
- **未注册模块**：`svc/agent_missions.rs`、`svc/fitting.rs`、`svc/medical.rs`、`svc/moonmining.rs`、`svc/moves.rs`、`svc/rows.rs`、`svc/bound.rs` 不直接出现在 `registry()`；它们是其它 handler 的支撑代码，不能由客户端直接调用。
