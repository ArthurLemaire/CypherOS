# 首页会话分组（Folder）设计分析

> 状态：分析文档，未动任何业务代码。基于 2026-07-31 对 v1.10-dev 的代码通读（关键文件引用均带行号）。
> 命名约定：本文将该特性统一称为 **Folder（文件夹）**，刻意避开 "Group"——代码里已有三个 "group"：
> ① `ModelGroup`（LLM 供应商 fallback 组，首页 FAB 就有 "New Chat with Group" 菜单，`ContentView.swift:2405`）；
> ② 草稿会话 id 的 `__grp__` 编码（`ContentView.swift:98-109`，内嵌的正是 ModelGroup id）；
> ③ SwiftUI `Group {}`。用户可见文案与代码符号若再叫 Group 必然混淆。

---

## 0. 现状摘要（相关链路盘点）

| 关注点 | 现状 | 位置 |
|---|---|---|
| 会话存储 | `actor ChatStore` + 裸 SQLite（`minis.db`，WAL），列用 `addColumnIfMissing` 幂等迁移 | `ChatStore.swift:357,492,521-556` |
| 会话模型 | `struct ChatSession`，**手写 `==` 只比较廉价字段**（列表刷新依赖它） | `ChatStore.swift:42-101`，`==` 在 `:83-92` |
| 列表排序 | SQL `ORDER BY updated_at DESC`（`:1144`）→ Swift 端二次分桶（Pinned/Today/Yesterday/…） | `ChatStore.listSessions:1040`；`ContentView.groupedSessions:1005-1051` |
| 未读红点 | `SessionBadgeStore`（UserDefaults，`.unread` 刻意不持久化、不同步），行内读 `hasUnread(for:)` | `SessionBadgeStore.swift:41-170`；`ContentView.swift:3846,3857` |
| 自动标题 | `generateSessionTitleIfNeeded` → `callSubModelForTitle`（子模型 + JSON-only prompt + thinking off）→ `updateSessionTitle`（顺带写 `category`） | `AIChatViewModel+TitleGeneration.swift:38,276-320`；`ChatStore.swift:1801-1815` |
| iCloud 同步 | V2 引擎，`SessionV2` 记录，**新类型有 6 个接线点**（漏任何一个静默失效），删除走 `deleted_record_tombstones` 硬删 | `SyncedTypes.swift:13-59,723`；`ICloudSharedZoneTransport.swift:40,630`；`ChatStore.swift:4860,687` |
| 多选 | 自研多选（非 EditMode）：`isSelecting` + `selectedIds` + 底部 `selectionToolbar` + 分节全选 | `ContentView.swift:244-245,2494-2630` |
| 行菜单 | `SessionContextMenu` **值语义 + Equatable、禁止捕获闭包**（UAF 崩溃修复约束），动作经 `SessionMenuAction` 枚举转发 | `ContentView.swift:3634+,20-33,1956` |
| 既有"分类" | `session.category`（16 个枚举值，标题生成时由 AI 一并产出，目前只驱动行图标，已在 SessionV2 同步） | `TitleGeneration.swift:301-302`；`ContentView.swift:4073` |

结论先行：**现有架构对"加一个 folder 维度"非常友好**——`pinned_at` 就是一条完整的先例路径（schema→模型→列表→菜单→同步），逐层照抄即可；真正要克制的是不去动 `groupedSessionIDs` 的 `[String]` id 投影和 ContextMenu 的值语义约束（两处都是修过的性能/崩溃热点）。

---

## 1. 数据结构方案

### 1.1 Folder 实体

新表 `folders`（建在 `ChatStore.createTables` 里，仿照 `:492` 的 sessions 建表 + 后续 `addColumnIfMissing` 模式）：

```sql
CREATE TABLE IF NOT EXISTS folders (
    id TEXT PRIMARY KEY,          -- 本地生成的 UUID；多端唯一性靠生成算法保证，无需协调
    name TEXT NOT NULL,           -- 刻意不加 UNIQUE：允许多端各自创建的同名 folder 并存
    icon TEXT,                    -- SF Symbol 名，可选
    color TEXT,                   -- 主题色 token，可选
    origin TEXT NOT NULL DEFAULT 'manual',  -- 'manual' | 'ai'
    sort_index INTEGER NOT NULL DEFAULT 0,  -- 用户自定义文件夹顺序（V2 拖拽重排预留）
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
```

对应 `struct ChatFolder: Identifiable, Codable, Hashable`。`origin` 记录来源仅用于统计/调试，不影响行为。

**主键 = 本地生成的 UUID，`name` 不加唯一约束（2026-08-01 决策）：**

- **不用名字当主键。** 名字当主键会把"改名"从改一个字段升级成**换一个身份**（删旧键 + 建新键 + 迁移全部成员），这串多行操作跨端会撕裂：A 端改名的同时 B 端往旧名字里归档，合并后 B 那批会话指向一个已不存在的键，静默掉回未分组。用 UUID 则改名只是 `FolderV2.name` 的单字段 LWW，成员一行不动。
- **允许同名 folder 并存。** 两端各建「工作」得到两个不同 UUID，同步后列表里就是两个同名夹——**不自动合并、不加唯一约束、不做同名提示**。理由：自动合并是不可逆的，而两个同名夹未必真是一回事（「工作」可以是公司也可以是副业）；用户想收拾随时可以多选移入 + 解散旧的，成本远低于误合并的代价。
- 完整并发矩阵见 3.3.1。
- ⚠️ 由此推出的实现约束：**任何按名字查 folder 的地方都必须能处理"匹配到多个"**。目前只有 2.3 自动分组一处（模型返回夹名 → 本地解析成 id），规则已定：**取最近活跃的那个**，判据是 `sortKey = max(组内 session.updatedAt)` 而非 `folders.updatedAt`（两个时间戳的辨析见 2.3）。

### 1.2 会话↔文件夹：**多对一（sessions.folder_id），不做多对多**

在 `sessions` 表加一列（`ChatStore.swift:531` 的 `pinned_at` 旁）：

```swift
addColumnIfMissing(table: "sessions", column: "folder_id", definition: "TEXT")  // NULL = 未分组
```

理由：
1. **心智模型**：需求描述是"文件夹"（归入、并入、新建），不是标签云。文件夹语义天然互斥；多对多会让"分组的时间排序/未读聚合"出现一条会话计入多个组的歧义（红点消一处другой处还在？）。
2. **迁移成本**：多对一 = 一列 + `ChatSession` 一个字段（**必须同步加进 `==`，`ChatStore.swift:83-92`，否则移动会话后行不刷新**——这是 `[T-ios-session-list-equatable-jank]` 注释明示的坑）。多对多则要新关联表 + 新同步类型 + 列表 JOIN + 去重逻辑，V2 同步接线点从 1 套变 2 套。
3. **同步冲突面**：`folder_id` 作为 SessionV2 的一个新 field 走既有 `lastWriteWinsByField(\.updatedAt)` 冲突策略（`SyncedTypes.swift:42`），零新增冲突逻辑；关联表则要自己处理成员关系的双端增删合并。
4. 将来真要标签，可在 V2+ 另加 `tags` 多对多而不受此列拖累。

⚠️ 已知陷阱（memory 存档 `provider_config_db_add_column_wipe_trap`）：加列必须同时进 CREATE TABLE 初始 DDL 和幂等 `addColumnIfMissing` 两处的其中之一且与同步 hydrator 的字段解码一致，否则 bulkReplace 类路径会静默丢数据。sessions 表走的是 addColumnIfMissing 模式，照抄 `pinned_at` 即可。

### 1.3 排序与未读：**运行时派生，不加缓存字段**

- 文件夹的 `sortKey = max(组内 session.updatedAt)`、`unreadCount / hasUnread = 组内任一 hasUnread`。
- **不需要 groupSummary 缓存表**。依据：
  - 列表数据本来就是全量拉进内存的（`listSessions()` 一次 SELECT + `sessionListCache`，`ChatStore.swift:376`；ContentView 持有 `sessions` 数组全量分桶，`groupedSessions:1005` 每次刷新都 O(n) 跑一遍日期分桶）。在同一个 O(n) 循环里顺手按 `folderId` 聚合 max/any，是零额外量级的。
  - 未读本身就在内存里（`SessionBadgeStore.badgeStates` 是 `@Published` 字典，`hasUnread` O(1)），聚合是对组内 id 的 any() —— 且它刻意不持久化（`persist()` 里剥掉 `.unread`，`SessionBadgeStore.swift:152-155`），如果给 folder 存 unreadCount 反而破坏这个"重启即清"的既有设计。
  - 会话量级：本地个人应用，数百到低千级。真到性能瓶颈时，先出问题的是 listSessions 全量 SELECT 而不是分组聚合，届时统一优化。
- 派生实现落点：扩展 `ContentView.groupedSessions(_:)`（`:1005-1051`）——在现有 Pinned/日期桶之前先按 folder_id 切出文件夹桶，桶内仍按 updatedAt 排、桶间按 max(updatedAt) 排；保持 `groupedSessionIDs` 的 `[(label, ids)]` 投影形态（`:1069`）不变，SwiftUI diff 行为不回退。

---

## 2. 交互方案

### 2.1 创建/归组入口（四个入口：A+B+C+D 全做）

| 方案 | 说明 | 优点 | 缺点 |
|---|---|---|---|
| **A. 多选 → 底部操作栏加 "移入文件夹"（推荐）** | 复用现成 `isSelecting` + `selectionToolbar`（`ContentView.swift:2559-2630`），新增一个按钮弹 sheet：已有文件夹列表 + "新建文件夹" + "✨AI 建议" | 多选基建全在（含分节全选 `:2517`）；批量归组是主场景；改动集中在一个 sheet | 入口藏在多选里，首次可发现性一般 |
| **B. 行长按菜单加 "移入文件夹 ▸" 子菜单（推荐并行做）** | `SessionMenuAction` 枚举加 case（`:20-33`），菜单体加 submenu | 单会话快速归组零成本；与 pin/duplicate 同一心智 | **必须遵守值语义约束**（`[T-ios-crash-contextmenu-uaf]`，`:3626-3633`）：文件夹列表得经 MenuKey/单例 store 传入，不能捕获闭包——文件夹多时 submenu 构建成本要注意 |
| C. 独立"管理文件夹"页面 | 设置里或列表头进入，集中管理增删改名排序 | 管理彻底 | 单独页面 + 导航，V1 负担大；归组仍要回到列表操作，闭环长。**V2 再做**（V1 的改名/删除放在文件夹头长按菜单即可） |

**决策（2026-08-01，用户确认）**：A + B **都做**，不是二选一。另外把原先划到 V2 的"文件夹头长按菜单"提到 **V1**，承载解散 / 删除全部会话 / 组内新建；并新增入口 D「长按拖拽入夹」。下面 2.1.1~2.1.4 是四个入口的落地细节。

#### 2.1.1 入口 A：多选 → "移入文件夹"

`selectionToolbar`（`ContentView.swift:2558-2629`）当前是 3 个等宽项：Export(Menu) / Force Sync(iOS17+且开了 iCloud 才在) / Delete。加一个 **Move**（`folder` 图标）：

- 位置放 Export 之后、Force Sync 之前（破坏性的 Delete 保持最右）。
- `.disabled(selectedIds.isEmpty)`，与其余项一致。
- ⚠️ **等宽挤压**：这一行是 `HStack(spacing: 0)` + 每项 `.frame(maxWidth: .infinity)`。iOS 17+ 且 iCloud 开启时会变成 **4 项**，小屏（SE/mini）下 `Text("Move").font(.caption2)` 与本地化后的长词（德语 "Verschieben"）要验证不截断。真截断了就只留图标 + 缩短文案，别加横向滚动。
- 动作：弹 folder picker sheet（已有文件夹列表 + 新建 + ✨AI 建议），确认后批量写 `folder_id`。
- 完成后**退出多选**并清 `selectedIds` —— 对齐 `runForceSyncOnSelection` 里 `singleSession == nil` 分支的既有行为（`:2660-2664`）。
- ⚠️ sheet 与多选态的时序：`:2809` 的注释写明 `isSelecting`/`selectedIds` 要在 **sheet 的 onDismiss** 里重置以避开动画冲突，别在按钮回调里就地清。

#### 2.1.2 入口 B：会话行长按 → "移入文件夹"

`SessionMenuAction` 枚举（`:20-33`）加一个 case，`wireMenuActions()`（`:1956-2007`）加对应分支。

- **不做 submenu 内联文件夹列表**。原方案想用 `Menu { … }` 子菜单直接列出所有文件夹，实测约束下不划算：菜单体是 `[T-ios-contextmenu-localized-mainthread-hang]` 的重灾区（一个 `String(localized:)` 就曾在 ~2000 会话下累积出 226s 主线程 hang，`:1913-1922`），把 N 个文件夹名塞进每一行的菜单体，等于给每次 AttributeGraph 重算乘上 N。
- 改为**单个 Button → 复用 2.1.1 的同一个 picker sheet**（`case moveToFolder(String)`，sheet 接收 `Set<String>`，单选就是一个元素的集合）。菜单体只多一个静态 Label，成本恒定。
- 顺带解决值语义约束（`[T-ios-crash-contextmenu-uaf]`）：文件夹数据根本不进菜单体，也就不存在"闭包捕获 vs MenuKey 传值"的问题。

#### 2.1.3 入口 C（V1 纳入）：文件夹 Section 头长按菜单

folder section header 上挂 `.contextMenu`，三个动作（a 解散 / b 删除全部 / c 组内新建）：

**a) 解散分组（Dissolve）**
- 语义 = 删 folder + 成员 `folder_id` 置 NULL，**会话一条不删**。这与 3.3 已定的删除语义完全一致，直接复用，无新逻辑。
- **必须与 Delete 视觉区分**。这是本次改动最大的误操作风险：用户在"删除会话"上已被训练出肌肉记忆，一个挂在会话列表上的破坏性菜单项极易被误读成"连同会话一起删"。因此：
  - 文案用 **"解散分组"/"Dissolve Folder"**，不用 "Delete"；
  - **不加** `role: .destructive`（不染红）—— 它不破坏用户数据，染红会强化"要删会话"的误读；
  - 加副标题或确认 alert 明示 "会话会移回未分组"。参考既有 delete 确认走 `computeDeleteInfo` 给出量化信息的做法（`:2602-2615`），这里给"N 个会话将移回未分组"即可，不需要算文件体积。
- 组内为空时也允许解散（此时无副作用）。

**b) 删除分组及其所有会话（Delete Folder and Sessions）**
- 真删：组内每个会话走既有的完整删除路径，再删 folder 本身。
- **必须复用 `computeDeleteInfo`**（`:2602-2615`）给出量化确认——"删除 N 个会话，含 M 个文件，共 X MB"。这条和多选删除是同一后果，就该有同一等级的确认。不要为它新写一套轻量确认。
- 这条**加** `role: .destructive`（染红），与上面的"解散"形成视觉对比。
- 实现上等价于「选中该 folder 全部成员 → 执行现有多选删除」。**优先直接复用那条链路**（把 folder 成员 id 灌进现有删除流程），而不是新写一个 `deleteFolderWithSessions`——删除路径牵涉会话文件、tombstone、同步，重写一遍等于把 `computeDeleteInfo`/`deleted_record_tombstones` 的既有正确性重来一次。

> ⚠️ **a 与 b 并列在同一菜单里，是本特性最高的误操作风险点。** 两条都作用于"整个文件夹"，只差"会话留不留"，而后者不可逆。必须靠三重区分把它们拉开：
> - **文案**：解散分组 / 删除分组及 N 个会话 —— 第二条**把数量写进菜单标题**，让后果在点开菜单时就可见，而不是等到确认弹窗；
> - **配色**：只有 b 染红（`role: .destructive`）；
> - **排序**：a 在上、b 在最下（destructive 沉底，与行菜单里 `.delete` 的位置习惯一致）；中间可用 `Divider()` 隔开。
>
> b 的确认弹窗措辞要避免只说"删除文件夹"——那会读成 a。用"将永久删除 N 个会话"作为主句。

**c) 在此分组新建会话**
- 需求：新建的会话直接落在这个 folder 里，不用"新建完再移进来"。
- ⚠️ **这条最容易实现错**，因为首页新建走的是**草稿会话**机制：id 编码在 `ContentView.swift:98-109`（`__grp__` 那套，注意此处的 `grp` 是 **ModelGroup**，与本特性无关，别复用这个编码位），落库时机延后到首条消息发出。所以 folder 归属**不能**在建草稿时写进 SQLite —— 那会儿行还不存在。
- 正确做法：把 `pendingFolderId` 随草稿态一起持有，在草稿**转正落库**的那一步连同其它字段一起写入。实现前必须先读通 `activeDraftId` / `newSessionRealId` 的转正路径（`:1893-1904` 附近），确认写入点唯一。
- 用户中途放弃草稿则什么都不发生（本来也没有行）。
- 建议同时让该 folder 自动展开，否则新会话进了折叠态的夹子，视觉上像"新建没生效"。

**入口 C 的前置依赖**：`.contextMenu` 要挂在 folder section header 上，而 `sectionHeader`（`:2515-2554`）目前在 `isSelecting` 时整个换成全选按钮。folder header 需要区分这两态：多选态下 folder header 应继续充当"全选本夹"（沿用现有分节全选语义），**长按菜单只在非多选态提供**。

#### 2.1.4 入口 D：长按会话拖拽进文件夹（2026-08-01 用户需求）

**需求**：长按一条会话后可以直接把它拖进某个文件夹，不必走菜单/sheet。

这是最直觉的归组方式，但它与既有交互有一处**真实冲突**，必须先解决。

##### ⚠️ 长按手势已经被 contextMenu 占用

会话行现在的长按 = 弹出 `SessionContextMenu`（`ContentView.swift:1233,1331`）。SwiftUI 里 `.contextMenu` 和 `.onDrag` **共用同一个长按识别器**,同时挂在一个视图上会互相抢:典型表现是菜单弹出后拖拽失效，或者拖拽启动了但菜单也闪一下。这不是能靠调参数绕开的，得明确二者的关系。

三种解法，**推荐 b**：

| | 做法 | 评价 |
|---|---|---|
| a | 长按只出菜单，拖拽改用其它触发（如多选态下拖） | 最保守，但"长按拖拽"这个需求就没实现 |
| **b（推荐）** | **iOS 16+ 的 `.draggable()` + `.dropDestination()`，与 `.contextMenu` 共存**——系统在同一长按上做仲裁：按住不动 → 菜单；按住后位移 → 拖拽 | 这正是系统相册/文件 App 的行为，用户已有心智；且 `.draggable` 与 `.contextMenu` 组合是 Apple 明确支持的 |
| c | 自己写 `LongPressGesture` + `DragGesture` 序列仲裁 | 手势仲裁自己写极易与 List 的滚动手势打架；本项目已有 `ios_webview_preview_swipe_dismiss` 的教训——**要赢系统手势就得在手势层解决，而不是自己造一套** |

选 b 还有个附带好处：拖拽预览、跨 App 拖放、iPad 分屏拖放全部由系统提供。

##### 落地要点

- **载荷用 session id 字符串**（`.draggable(session.id)`），不要塞 `ChatSession` 值——行菜单的 `[T-ios-crash-contextmenu-uaf]` 值语义约束同理适用，而且 id 也是列表投影一直在用的形态。
- **放置目标 = folder section header**（`.dropDestination(for: String.self)`）。折叠态的 header 就是一个夹子的代理，拖到它上面 = 移入，语义直白。
- **拖到展开态夹子的内部行上**也应当接受（等同于拖到该夹 header）,否则用户展开了夹子反而没法往里拖，反直觉。
- **拖到"未分组"日期桶的 header** = 移出文件夹（`folder_id = NULL`）。这条让拖拽成为**双向**操作，不然移出还得回去点菜单。
- 落点必须有**明确的高亮反馈**（`isTargeted` 回调），否则用户不知道松手会落在哪——夹子在折叠态下是一行，目标区域本来就不大。

##### ⚠️ 与多选态的关系

多选态（`isSelecting`）下行已经是"点击=勾选"，此时**不启用拖拽**——多选态的批量归组走 2.1.1 的 Move 按钮，那条路径更适合批量。拖拽只在**非多选态**提供，与 2.1.3 的 header 长按菜单同一个门。

##### 定位：锦上添花，可延后

`sort_index` 那条注释里原本就把"拖拽"划给了 V2。这条需求把**拖会话入夹**提前了，但**拖动文件夹重排**仍留在 V2。

如果 V1 工期紧，这一条是最适合砍的——2.1.1/2.1.2 已经覆盖了归组的全部功能，拖拽是体验增益而非能力增益。建议实现顺序上放在三个入口之后。

### 2.2 AI 辅助分组流程（复用标题生成管线）

用户多选 N 个会话 → 点 "✨AI 分组"：

1. **组 prompt**：完整复刻 `callSubModelForTitle` 的形态（`TitleGeneration.swift:276-320`：子模型 entry、`streamAgentMessage(tools: [], maxTokens: 1024, thinkingLevel: .off)`、JSON-only 指令、`titleLanguageInjection()` 语言注入）。上下文只传**轻量摘要**：
   - 已有文件夹：`[{name, 组内前3个会话标题}]`（给"并入判断"依据）。**不传 id**——与 2.3 同一条原则：模型没法推理不透明 id，只会费 token + 幻觉；下标索引同理不可靠（模型会数错位）。
   - 选中会话：`[{title, category}]`（标题已是 AI 生成的语义摘要，**不必再传消息内容**——省 token、避免把聊天内容送进子模型的隐私面）
2. **输出 schema**：`{"decision": "merge" | "create", "folder": "已有夹名", "name": "新夹名", "icon": "..."}`。`decision == "merge"` 时 `folder` 是要并入的**已有夹名**，由调用方本地解析成 id（解析规则与重名 tie-break 同 2.3）；`decision == "create"` 时读 `name` 作为新夹名。
   - ⚠️ 与 2.3 的关键差异：这条路径**允许新建夹**，所以解析失败的处理不同——2.3 匹配不到就当 null（不造夹），而这里匹配不到应当**降级为 create 分支**并把模型返回的字符串作为新夹名预填进确认框，由用户拍板。
3. **必须有确认步**：结果以底部 sheet 呈现——"并入『xxx』？"或"新建『yyy』（可编辑名字）"，确认才落库。理由：标题生成错了改一个标题；分组错了是批量数据移动，且子模型质量参差（既有 fallbackTitle 路径就是明证）。AI 失败时降级为普通"新建文件夹"输入框，不阻塞流程。
4. 失败/超时兜底照抄 `applyFallbackTitle` 的 attempt 思路，但交互上直接给手动输入框即可，不用自动重试。

### 2.3 自动分组（设置开关驱动，2026-08-01 用户需求）

**需求**：设置 → 外观 → 新增"分组设置"，含"自动分组"开关。**仅当开启时**，才在生成标题的同时按**已有分组**自动归类；且允许 AI 判定"都不相关"而**不分组**——不强迫每个会话都落进某个夹。

#### 设置位置与形态

`AppearanceSettingsView`（`ContentView.swift:4670-4795`）当前是 App Icon / Language 两个 Section。新增第三个 Section「Grouping」：

- Section header 用「分组设置 / Grouping」，`Toggle("Auto-Grouping")`，`@AppStorage("autoGroupingEnabled")`，**默认 OFF**。
- 默认关的理由：虽然它**不新增请求**（复用标题那一次，见下），但它会在用户不知情时移动数据。一个静默把会话分门别类的行为必须是用户主动开启的——这与"不新增开销"是两回事。
- Section footer 写清三件事：只在**首次生成标题**时判定一次（之后不重分类）、只会归入**已有**分组、不匹配则留在未分组。
- ⚠️ 文案层面别叫它 "AI 自动整理"——那是 V2 的全库批量整理（见 V2 列表），两者范围差很远，共用叫法会让用户以为开了开关就会重排历史会话。
- ⚠️ 这个页面**不要**照抄 Language 那套 `pendingSettingsReopen` 逻辑（`:4757-4765`）——那是 `appLanguage` 触发根视图 `.id()` 重建才需要的补偿，普通 toggle 没有这个副作用。

#### 挂载点：与标题生成同一次调用，不新增一次请求

关键结构事实：`callSubModelForTitle`（`TitleGeneration.swift:276`）**本来就是一次调用同时返回 title + category**，返回类型 `(String, String?)`，写回走 `updateSessionTitle(_:title:category:)`（`:126`）。

因此自动分组**扩展这次调用的 schema，而不是新增一次子模型往返**：

- prompt 追加一段：给出已有文件夹的**名字清单**（纯字符串数组，如 `["工作", "生活", "读书"]`），要求在 `folder` 字段回填其中之一，**或回 `null`**。
- 输出 schema：`{"title": "...", "category": "...", "folder": "工作" | null}`。
- 返回类型扩为 `(String, String?, String?)`，第三项是**名字**；由调用方**在本地解析成 folder id** 后随 `updateSessionTitle` 落库。

> ⚠️ **模型接口用名字，数据库主键用 id——这两层必须分开（2026-08-01 决策）。**
>
> **为什么 LLM 层不能给 id**：模型没有任何依据去推理 `f_a3f9c2` 这种不透明字符串，塞进 prompt 既费 token 又诱发幻觉 id，few-shot 例子也变得不可读。给名字则是模型天然擅长的语义匹配。
>
> **为什么存储层不能用名字当主键**：名字当主键会让"改名"从改一个字段升级成**换一个身份**（删旧键 + 建新键 + 迁移全部成员），而这串多行操作跨端会撕裂——A 端改名的同时 B 端往旧名字里归档，合并后 B 那批会话指向一个已不存在的键，静默掉回未分组。用 id 则改名只是 `FolderV2.name` 的单字段 LWW，成员一行不动，与并发归档干净合并（详见 3.3）。
>
> **解析规则**：模型返回的名字在本地 `folders` 表里按名字精确匹配（建议 trim + 大小写不敏感匹配，避免模型回 "work" 而库里是 "Work" 就失配）。**匹配不到就当 null**——绝不能凭模型返回的名字去新建夹子（自动路径不造夹，已在下文列明）。名字重复时（见 3.3 的同名并存）**取最近活跃的那个夹**——判据是 folder 的 `sortKey = max(组内 session.updatedAt)`（1.3 节定义），**不是 `folders.updatedAt`**。
>
> **这两个时间戳容易混淆，但选错会把会话塞进错夹：**
> - `folders.updatedAt` = **文件夹记录本身**的修改时间（改名、换图标）。一个天天有新会话进出的夹子，只要没人改过名，这个值就一直停在创建那天；反过来一个荒废半年的夹子昨天被改了个名，它的 `updatedAt` 反而最新。
> - `sortKey = max(组内 session.updatedAt)` = **组内最近一次对话**的时间，这才是"最近活跃过"的字面含义。
>
> 用 sortKey 还有两个附带好处：① 它与首页的文件夹排序同源，所以"选最近活跃的同名夹" = "选列表里排更上面的那个"，用户看到的结果与直觉一致；② **不需要新算**——2.6 / 3.2 已规定该值在 `groupedSessions` 那次 O(n) 遍历里随 sortKey/红点一并产出，这里直接取用。
>
> 全空的同名夹（都没有成员，sortKey 均为空）退回按 `created_at` 取最早的那个——它更可能是用户"原本那个"夹子。

这样开关关闭时行为与今天**逐字节一致**（prompt 不追加、schema 不变），开启也不增加请求数——只多几十 token 的 folder 清单。

#### "可以不分组"是硬要求，prompt 必须显式撑住

子模型在"给一个封闭选项列表"时有强烈的**必选倾向**，会硬塞一个最不像错的答案。既有 `category` 字段就是活证据：16 个枚举值里有个 `other` 兜底，仍然只驱动一个行图标——错了代价小。而 folder 判断错了是**数据被移进错夹**，代价高一个量级。

所以 prompt 里必须：
- 明写 `folder` 可以为 `null`，且**给出 null 的判据**（"只有当会话主题明确属于某个已有分组时才填；有任何不确定就填 null"）；
- example JSON **给一个 folder 为 null 的样例**（few-shot 里只出现填了值的例子，等于在诱导必填）；
- 不要提供"新建分组"能力——自动路径**只并入已有夹，不自动造夹**。造夹是不可逆的结构变更，且会导致夹子随对话数量野蛮增殖；新建仍走 2.2 的人工确认路径。

#### 时序与边界

- **无已有文件夹时直接跳过**：一个夹都没有就不追加 prompt 段、不解析 folder 字段（否则等于让模型在空列表里选）。这也自然覆盖了功能刚上线时的冷启动。
- **只在首次生成标题时归类，不做后续重分类**。标题生成本身就有 `session.title != nil` 的幂等短路（`:100-107`），自动分组挂在同一个 Task 内，天然继承这个"只跑一次"语义。
- **手动优先**：若用户已经手动把该会话放进某夹（理论上首次生成标题前很难发生，但草稿转正 + 2.1.3c「在此分组新建会话」正好构成这条路径），自动结果**不得覆盖**。写回时判 `folder_id IS NULL` 才写。这条必须显式实现——`updateSessionTitle` 现在是无条件覆盖 category 的。
- **`applyFallbackTitle` 路径不带分组**（`:159-168`）：那是模型调用失败后的本地降级（截断首条用户消息），根本没有模型判断可用，folder 一律 nil。
- **失败静默**：folder 名字解析失败/匹配不到任何夹 → 当作 null，标题照常写。绝不能让分组解析的异常回退掉标题——标题是主功能。指向不存在的夹也天然被 3.3 的"孤儿引用视同未分组"兜住。

#### 与 `regenerateSessionTitle` 的关系

`regenerateSessionTitle`（`:175`）是用户主动"重新生成标题"，走同一个 `callSubModelForTitle`。**建议它不改动 folder 归属**：用户在那个入口的心智是"标题不好听，换一个"，顺手把会话搬走会是惊吓。实现上即忽略返回的 folder 字段。

### 2.4 列表展示形态（三选，推荐 A）

| 方案 | 实现复杂度 | 说明 |
|---|---|---|
| **A. 可折叠文件夹 Section（推荐）** | 低-中 | 现有列表就是 `Section + sectionHeader` 结构（`:1188-1265`），文件夹只是新的一类 Section：头部显示 名称+聚合红点+最新时间，点击折叠/展开（折叠态存 UserDefaults `Set<folderId>`）。折叠 = 该 section 的 ids 数组置空，`groupedSessionIDs` 投影天然支持。桶间顺序：Pinned → 文件夹（按 max(updatedAt) 降序互相排）与未分组日期桶按各自 sortKey 混排（见 2.8）。**展开态的具体视觉见 2.5（上下虚化夹层 + 内层复用首页时间 section），头部图标见 2.6（top3 会话图标合成）** |
| B. 彩色标签 + 筛选（不改顺序） | 低 | 行尾加标签 chip + 顶部 filter；列表结构零改动。但"分组跟随最新消息排序、聚合红点"这两条核心诉求都体现不出来——标签只是过滤器，不满足需求 |
| C. Tab/分段控件切换 | 中-高 | 顶部加 folder tab，每 tab 一个过滤列表。iPad splitList 双列结构下 tab 层级混乱；文件夹多时 tab 溢出；与现有搜索/多选交互交叉成本高 |

### 2.5 展开态视觉：原地展开 + 上下虚化夹层（2026-08-01 用户需求）

**需求**：点开文件夹的效果要像"打开一个文件夹"——展开区域的**上下**有半透明模糊过渡，表达"它是从首页这条 list 里就地撑开的"；展开后的内层列表**沿用首页同一套时间 section**（Today / Yesterday / This Week / …）。

这是对 2.4-A 的**加强**，不是换方案：仍然不做全屏 push、不做 Tab。原地展开保住了"从哪来回哪去"的空间连续性——这正是上下虚化要表达的东西；真 push 一个新页面反而把这个隐喻打断了。

#### 结构

```
┌─ 首页 List ─────────────────┐
│  Pinned / Today / …（正常行）│
│  ▸ 📁 工作  (12)  ← header  │
│  ░░░░ 上缘虚化夹层 ░░░░      │  ← 表示"上面还有首页内容"
│    Today                    │  ← 内层复用同一套 section
│      · 会话 A               │
│      · 会话 B               │
│    This Week                │
│      · 会话 C               │
│  ░░░░ 下缘虚化夹层 ░░░░      │
│  （首页后续行继续）           │
└─────────────────────────────┘
```

#### 内层 section 直接复用 `groupedSessions`

好消息：`groupedSessions(_ list:)`（`ContentView.swift:1005-1050`）**已经是一个对任意 `[ChatSession]` 的纯函数**——它不读 `self.sessions`，分桶逻辑全在入参上。所以内层列表就是：

```swift
groupedSessionIDs(sessionsInFolder)   // :1069，同样已是纯函数
```

零改动、零复制。日期桶语义、Pinned 优先、排序规则天然与首页一致——用户要的"按照首页一样的时间逻辑"字面成立。

⚠️ 两个细节：
- **Pinned 桶在夹内的含义**：`groupedSessions` 会把 `isPinned` 的会话单独提到 "Pinned" 桶。夹内保留这个行为是对的（置顶是会话自身属性），但要确认视觉上不会让人误以为"这是首页的置顶区"——内层 section header 建议比外层**降一级字重/缩进**。
- **仍然走 id 投影**：内层 `ForEach` 必须同样吃 `[String]` 而非 `[ChatSession]`，否则 `[T-ios-session-list-equatable-jank]` 那个 O(N) `Array<ChatSession>.==` 会在夹内重演。用现成的 `groupedSessionIDs` + `sessionForRow(_:)`（`:1088`）即可。

#### 上下虚化夹层怎么做

**推荐：两条固定高度（约 12-16pt）的渐变遮罩，贴在展开区首尾。**

- 实现用 `LinearGradient` 遮罩而非 `.blur`——**这条是性能红线**。`.blur` 是离屏渲染，挂在一个随滚动不断重排的 List 区域上会持续吃 GPU；而这个列表已经是 `ios_scroll_jank_contextmenu_trace` / `ios_firstmount_measure_storm` 两个已归档性能事故的现场，不该再往里加离屏。
- 想要"毛玻璃"质感就用 `.ultraThinMaterial` 配 gradient mask（材质是系统合成的，比 `.blur` 便宜得多）。既有 `selectionToolbar` 就是 `.background(.ultraThinMaterial)`（`:2628`），观感上也一致。
- 上缘遮罩 `.mask(LinearGradient(colors: [.clear, .black], …))`，下缘反向。目的是让内容**渐隐进夹层**，而不是画两条硬边。

⚠️ **List 里嵌 List 是禁止项**。内层不能是独立的可滚动 `List`/`ScrollView`——嵌套滚动容器在 iOS 上手势打架、自适应高度失效，且这个页面 iPad 下还是 splitList 结构。正确做法是：内层 row 与 section **作为首页同一个 List 的行插入**（展开 = 把这些行 append 进 `groupedSessionIDs` 的输出流），虚化夹层是两个特殊的 `listRow`。这样只有一个滚动容器，虚化条随内容自然滚动，"从 list 里撑开"的隐喻也才成立。

#### 折叠态存储

折叠/展开状态存 UserDefaults `Set<folderId>`（2.4-A 已定）。**不进 iCloud 同步**——这是纯 UI 视图状态，跟 `SessionBadgeStore` 的 `.unread` 不持久化同理（`:18`），跨设备同步展开状态没有价值反而制造 sync 噪音。

#### 动画

展开/折叠用 SwiftUI 默认的 List section 动画即可，**不要**自己写 matchedGeometry 或自定义 transition。这个列表对额外的 layout 计算极其敏感（见上述两个归档事故），能用系统 diff 动画就别自造。

### 2.6 文件夹图标：Group 图标 + 组内 top N 会话图标合成（2026-08-01 用户需求）

**需求**：文件夹图标不是一个静态文件夹符号，而是由**组内前几个会话的分类图标**组合而成，外面套一个 group 容器形态——一眼看出"这个夹里装的是什么类型的东西"。

#### 素材已经现成

每个会话行左侧的图标来自 `SessionRow.categoryIcon`（`ContentView.swift:4073-4092`）：16 个 category 各映射一组 `(SF Symbol, Color)`，例如 `code → ("terminal.fill", .orange)`、`health → ("heart.fill", .red)`。这套映射就是合成素材，**不需要新画任何资源**。

⚠️ 但它现在是 `SessionRow` 的 **private 计算属性**，且直接读 `session.category`。合成图标要用，必须先把它**提成一个纯函数**（`static func categoryIcon(for category: String?) -> (String, Color)`）供两处共用。注意 `:4217` 处还有一份**同名的重复实现**（`RemoteSessionRow` 里），提取时一并合并，别留两份漂移。

#### 合成规则

- **取 top 3**（不是更多）：2×2 网格里 3 个图标 + 一个留白，视觉上比塞满 4 个更透气，也给"还有更多"留了想象空间。数量再多就糊成噪点，缩到 28-32pt 的行高里根本分辨不出。
- **"top" 的定义 = 按 `updatedAt` 降序取前 3 个会话**，与夹子自身的排序键（`max(updatedAt)`）同源，语义一致：图标反映的是"这个夹最近在忙什么"。
- **按 category 去重**：3 个会话若都是 `code`，画三个一样的终端图标毫无信息量。去重后取前 3 个**不同** category；不足 3 个就画几个是几个（1 个就居中放大，2 个就并排）。
- 外框用一个统一的圆角矩形容器（复用行图标既有的 `iconBackgroundColor` 处理手法，`:4103`），底色取**第一个 category 的颜色**做低透明度填充，让夹子整体有一个主色调。
- 空夹兜底：没有成员时退回静态 `folder.fill`（灰）。

#### 性能约束（这条比视觉更要紧）

合成图标出现在 folder section header 上，而 header 在这个列表里是**高频重算**路径。必须：

- **纯派生、不缓存进 DB**：图标由成员 category 算出，成员一变就该变。但——
- **不要在 header 的 body 里现算**。计算需要"取该夹前 3 个会话 + 去重 category"，这是一次对成员数组的遍历。放 body 里等于每次 AttributeGraph 重算都跑一遍 × 夹子数量。正确位置是**和 2.3 的 sortKey/红点聚合同一次 O(n) 遍历**（`groupedSessions` 那一轮），把 `[(symbol, color)]` 结果一起产出，header 只做绘制。
- 这与 3.2 已定的"聚合全部落在 `groupedSessions` 一个函数"是同一条原则，顺手带上即可，不增加遍历。

### 2.7 组内会话状态透传到文件夹头（2026-08-01 用户需求）

**需求**：组内若有会话正在**运行中**或处于**暂停**状态，折叠态的文件夹头要能体现出来——不然夹子一收起来，里面有任务在跑/被中断这件事就完全看不见了。

这条与 1.3 的红点聚合是**同一类派生**（组内 any → 头部显示），实现上顺理成章；但状态源有三个，且各自的"新鲜度"语义不同，不能一把抓。

#### 状态源盘点（三个，各有归属）

| 状态 | 来源 | 语义 | 现有行渲染 |
|---|---|---|---|
| **运行中** | `SessionActivityTracker.shared.isActive(sessionId)`（`ChatLifecycleSupport.swift:20` 的 `activeSessions: Set<String>`） | agent 正在跑 | 行的 `isActive`（`ContentView.swift:1207,1300,3816`） |
| **暂停** | `SessionBadgeStore.topCornerBadge(...) == .paused`（`SessionBadgeStore.swift:21`） | 后台被系统挂起、"Interrupted — tap Resume" | 图标右下角橙色 `!` 角标 |
| **未读** | `SessionBadgeStore.hasUnread(...)` | 后台任务完成有新消息 | 图标右上角红点 |

未读已在 1.3 定了聚合规则，这里补前两个。

#### 聚合与优先级

在 `groupedSessions` 那次 O(n) 遍历里，对每个 folder 顺手求三个 any：`anyActive` / `anyPaused` / `anyUnread`（与 sortKey、2.6 的合成图标同一趟，**不新增遍历**）。

显示优先级 **运行中 > 暂停 > 未读**：

- 运行中优先，因为它是**当下正在发生**的事，且会自行结束——用户看到它是在等一个进行中的结果。
- 暂停次之：它是**卡住了、需要用户介入**的状态，比"有新消息"更需要注意。
- 未读垫底（沿用既有红点）。

⚠️ 但**暂停不能被运行中完全吞掉**。一个夹里可能同时有"A 在跑"和"B 被挂起等你恢复"——只显示转圈会让 B 永远得不到注意。既有 `SessionBadgeStore` 的设计本身就是**队列而非单标志**,注释明写了 "multiple concurrent statuses can coexist"(`:7-9`),且 `.paused`(右下角)与 `.unread`(右上角)刻意占**不同的角**以便共存。folder 头照抄这个思路:**运行中指示器与暂停角标占不同位置**,可以同时出现，而不是二选一。

#### 渲染形态

- **运行中**：文件夹图标上叠一个小的进行指示（与行的 `isActive` 表现保持一致即可，别自创新语汇）。
- **暂停**：复用 `.paused` 那个橙色 `!` 角标的视觉，挂在文件夹图标的**同一个角**（右下），与会话行形成一致的语言——用户在行上学会的符号，在夹子上不用重新学。
- 三态皆无时，文件夹头就是 2.6 的合成图标本体。

⚠️ **展开态下不要重复显示**。夹子展开后，组内每一行本来就各自带着自己的状态指示，头部再聚合一次就是噪音，还会让用户困惑"头上这个 ! 指的是哪一条"。**聚合指示只在折叠态出现**——这也正是它存在的理由：折叠把内部状态藏起来了，才需要一个代理。

#### 性能：这条是唯一需要小心的地方

`SessionActivityTracker` 与 `SessionBadgeStore` 都是 `@ObservedObject`,而 `activeSessions` 在 agent 跑动时**变化频繁**。把它们接进 folder 头意味着:**每次任一会话的活动状态变化，都会驱动所有 folder 头重算**。

这个列表已经是 `ios_scroll_jank_contextmenu_trace` / `ios_firstmount_measure_storm` / `[T-ios-session-list-equatable-jank]` 三处性能事故的现场，所以:

- 聚合结果必须是**预计算好的轻量值**（三个 Bool），随 `groupedSessions` 的输出一起下发,**不要**在 folder 头的 body 里现读 tracker/store 再对成员数组做 `contains`。后者等于每次重算 × 夹子数 × 组内会话数。
- 注意 `SessionActivityTracker` 还有个 `currentToolStatus` / `sessionToolInfo`（`:27,39`）是**高频字符串更新**（工具名/状态每步都变）。folder 头**只订阅 `activeSessions` 的 any 结果**,绝不要把 toolStatus 透传上来——那会把一个每秒多次的字符串流接到列表头上。
- 既有 `updateToolInfo` 已经带了节流（`throttledUpdateWorkItem`,`:43`），说明这条路径的更新频率历史上就是要压的。

### 2.8 未分组会话

**保持平铺（推荐）**：未分组会话继续按现在的日期桶展示，与文件夹 Section 按 sortKey 自然混排（一个活跃的未分组会话可以排在不活跃文件夹之上——符合"最新的在上面"直觉）。不做"默认收纳文件夹"：强制兜底组会让不用此功能的用户首页多一层无意义嵌套，也违背"不推倒现有列表"的约束。简单版取舍：若混排实现发现与日期桶标签逻辑纠缠，可退为"文件夹区（按活跃度排）固定在 Pinned 之后、日期桶之前"，实现更简单，牺牲少许排序纯度。

### 2.9 只看分组模式（2026-08-01 用户需求）

**需求**：混排的代价是**文件夹会被活跃的散会话冲到列表底部**——夹子的 sortKey 是"组内最近一条"，一个上周整理好的夹子在今天聊了十条新会话之后就沉下去了，想找它得一路滚。需要一个"只看分组"的模式。

这条需求实际上是对 2.8 混排决策的合理反驳：混排在排序纯度上是对的，但**牺牲了文件夹的可达性**。加一个筛选态比推翻混排更划算。

#### 落点：`filteredSessions` 是唯一漏斗，不新增列表结构

`filteredSessions`（`ContentView.swift:999-1003`）现在只做搜索过滤：

```swift
private var filteredSessions: [ChatSession] {
    guard let matchedIds = searchMatchedIds else { return sessions }
    return sessions.filter { matchedIds.contains($0.id) }
}
```

两个 List（`:1188` sidebar / `:1280` splitList）都吃它的输出。**"只看分组"就是在这里再加一层过滤**（`folder_id != nil`），下游的分桶、渲染、多选、拖拽全部零改动。

⚠️ 与搜索是**串联**而非互斥：开着"只看分组"再搜索，应当是"在分组内搜索"。实现上就是两个 filter 依次作用，天然成立——但要确认空态文案能区分三种空（无搜索结果 / 没有任何分组 / 该模式下无匹配），`:1260` 的 `emptyState` 现在只判了 `isSearching`。

#### 入口形态（三选，推荐 A）

| 方案 | 说明 | 评价 |
|---|---|---|
| **A. 列表顶部分段控件（推荐）** | 列表最上方一个 `Picker(.segmented)`：`全部 / 分组`。常驻可见、一眼可切、状态自明 | 可发现性最好；但占一行垂直空间 |
| B. 工具栏图标切换 | `sidebarToolbarContent`（`:1271,1389`）加一个 `folder` 图标按钮，点击切换，激活态填充显示 | 不占列表空间；但"当前处于筛选态"这件事只靠一个图标的填充/描边表达，容易让用户忘了自己开着筛选——**这是筛选类 UI 的经典陷阱** |
| C. 搜索栏旁的筛选 chip | 复用搜索 FAB 那套浮层（`:2425-2470`） | 与搜索强绑定，但"只看分组"不是搜索的子功能，语义错位 |

推荐 A，并且**只在用户至少有一个文件夹时才显示**这个分段控件——一个夹子都没有的用户不该看到这个切换（也避免了切过去是空列表的尴尬）。

#### 状态与记忆

- 用 `@AppStorage("sessionListFilterMode")` 持久化，**跨启动记住**。理由：这是一个"我现在想按分组组织"的工作模式，不是一次性动作；每次启动重置回"全部"会让常用分组的用户每次都要重切。
- ⚠️ 但持久化筛选态有个已知风险：**用户忘了自己开着筛选，以为会话丢了**。缓解手段是入口用方案 A（常驻可见的分段控件，当前态一目了然），而不是 B 那种只有图标状态的隐式表达。这也是我不推荐 B 的主要原因。

#### 该模式下显示什么

只看分组时，列表内容 = **只有文件夹 Section**，按 sortKey 降序。此时：

- 未分组会话全部隐去（这就是该模式的目的）。
- **Pinned 桶怎么办？** 建议**保留置顶的散会话**——置顶是用户显式表达的"这条最重要"，被一个筛选模式吞掉会很意外。折中：Pinned 区保留，其下只有文件夹。
- 折叠态沿用 2.5 的 UserDefaults 记忆，不因切换模式而重置。

#### 与 2.5 展开态的关系

只看分组模式下，用户更可能连续展开多个夹子浏览。此时 2.5 的"上下虚化夹层"仍然成立（它表达的是"从列表撑开"，与筛选无关），但**多个夹子同时展开时会出现多组虚化条**——需要真机看一眼观感，如果显得碎，可以在该模式下改为"同时只展开一个夹子"（手风琴式）。这条留到实现时用真机决定，不预设。

---

## 3. 现有代码影响面评估

### 3.1 AI 生成分组名——复用可行性：高

这里有**两条不同的 AI 路径**，别混为一谈：

| | 2.2 手动 "✨AI 分组" | 2.3 自动分组 |
|---|---|---|
| 触发 | 用户多选后主动点 | 开关开启时，随标题生成自动 |
| 能力 | 可**新建**夹（含起名/选图标） | **只并入已有夹**，或不分组 |
| 调用 | 独立一次子模型调用 | **复用标题那一次**，扩 schema，不新增往返 |
| 确认 | 必须有确认 sheet | 无（静默，因为只是并入且可撤销） |
| 落点 | 新建 `FolderNameGeneration` | 改 `callSubModelForTitle` 本身 |

- 手动路径复用点：`callSubModelForTitle` 的**形态**而非函数本身（它耦合了标题 JSON schema 与写回逻辑）。建议在 `AIChatViewModel+TitleGeneration.swift` 旁新建 `FolderNameGeneration`（static 函数即可，参照 `regenerateSessionTitle:175` 的 static 调用方式，不依赖具体 VM 实例）。
- 自动路径则相反——**直接改 `callSubModelForTitle` 的 prompt 与返回元组**（详见 2.3）。因为它要的正是"和标题同一次判断"，抽出去反而白花一次调用。
- 需注意的既有坑（注释都在原文件里）：`thinkingLevel: .off` 是 load-bearing（`:281-294`）；子模型 entry 解析走 `makeAgentProvider`（`:296`）。

### 3.2 排序/未读改造——影响面：小且集中

- **SQL 层不动**（`listSessions` 继续 `updated_at DESC`，只是 SELECT/decode 多带 `folder_id` 列，`:1119-1145` + `:1213-1221`）。
- 聚合全部落在 `ContentView.groupedSessions`（`:1005-1051`）一个函数 + `sectionHeader`（`:2517`）渲染。红点聚合读 `SessionBadgeStore.hasUnread`，不改 store 本身。
- 连带检查点：`ChatSession.==`（`:83-92`）加字段；新 mutator（仿 `toggleSessionPin:1818-1848`）必须 `invalidateSessionListCache()` + `markDirty`；`SessionsOffloadBridge.querySessions`（`:20`）可选加 folder 字段让 agent 工具面可见（V1 可不做）。

### 3.3 iCloud 同步——建议 V1 就带上，接线点明确

有完整 V2 同步机制。**建议 Folder 实体 V1 即同步**（分组是跨设备强诉求，且晚同步再迁移更痛）。两部分：

1. `sessions.folder_id` 作为 SessionV2 新 field：`SyncedTypes.swift:31-41` 的 fields 列表加 `F.optionalString("folderId", ...)`，冲突走既有 lastWriteWinsByField，**version 需 bump 并确认旧设备读到未知字段的降级行为**（参考 `pinnedAt` 当年的加法）。
2. 新记录类型 `FolderV2`，六个接线点一个不能少（memory `icloud_new_v2_type_checklist` 的教训——漏一个静默不同步）：
   - `SyncedTypes.swift` mirror struct + `registerAll()`（`:723`）
   - `ICloudSharedZoneTransport.zoneByRecordType`（`:40`，进 `minis-shared`）
   - fetch 列表 `typesAndKeys`（`:630`，**CloudKit Dashboard 要把 sortKey 标 queryable+sortable**）
   - `ChatStore.v2SyncRecordTypes` 白名单（`:4860`）
   - `ChatStoreSyncHydrators` builder/merger/deletionApplier（`:22`）
   - 删除走 `deleted_record_tombstones`（`:687`）
- 冲突语义：Folder 改名 LWW（by updatedAt）；**删除文件夹 ≠ 删除会话**——本地删 folder 时把组内 `folder_id` 置 NULL 并各自 markDirty；远端收到 FolderV2 tombstone 同样只清引用。孤儿引用防御：hydrate/列表侧把"folder_id 指向不存在的 folder"视同未分组（对抗 fetchRecentV2 乱序到达——会话先到、folder 后到的窗口，memory 里 `icloud_deleted_session_resurrection` 显示该乱序真实存在）。

#### 3.3.1 多端冲突矩阵（2026-08-01 决策后补全）

前提：`folders.id` 是**本地生成的 UUID**（1.1 的 DDL）。id 唯一性由生成算法保证，**不需要任何跨端协调**——这正是多端离线场景下 id 优于名字当主键的根本原因（名字的唯一性需要全局协调，而离线恰恰没有协调）。因此**"同 id 冲突"在本设计里不会发生**；两端各建同名夹得到的是两个不同 UUID + 相同 name。

| 并发场景 | 归属机制 | 结果 | 用户可感知？ |
|---|---|---|---|
| 两端各建同名「工作」 | 不同 UUID，各自独立记录 | **两个夹并存**（已决策：不自动合并、不提示，用户想收拾就多选移入+解散旧的） | 是，列表出现两个同名夹 |
| 同一会话两端移入不同夹 | `SessionV2.folder_id` 走既有 `lastWriteWinsByField(\.updatedAt)`（`SyncedTypes.swift:42`） | 晚写的赢，与 `pinned_at` 同款语义 | 是，但这是 LWW 固有语义 |
| 两端同时改同一夹的名字 | `FolderV2.name` 单字段 LWW | 晚的赢，**成员一行不动** | 轻微 |
| A 解散夹 + B 往该夹归档 | tombstone 与成员写入是两条独立记录，无引用计数 | B 归档的会话成为**孤儿引用** → 按上文规则视同未分组 | 是，会话静默掉回未分组 |
| 会话先到、folder 后到 | 同上孤儿规则 | 临时未分组，folder 到达后自动归位 | 短暂，自愈 |

最后两行是同一条兜底规则覆盖的两种成因（**已删** vs **晚到**），本地既不需要也无法区分它们——这正是"孤儿视同未分组"比"缓存起来等 folder 到达"更稳的地方：后者在"folder 被真删、永远不会到"时会永久挂住。

**唯一用户可感知的异常是第 4 行**：会话从夹子里静默掉出来。接受这个代价，不做引用计数或墓碑复活——那条路复杂度高一个量级，而后果只是用户重新拖一次。

### 3.4 明确不动的东西

- `SessionBadgeStore` 的存储与生命周期（`.unread` 不持久化的设计保持）。
- `groupedSessionIDs` 的 `[(label, [String])]` 投影与 `sessionsByIdCache` 行查找（`:1069-1092`）。
- ContextMenu 值语义/Equatable 约束（新 submenu 必须遵守）。
- 现有日期分桶逻辑本身（只在其前面加文件夹桶）。

---

## 4. MVP（V1）范围建议

**V1 —— "手动为主、AI 点缀"的完整闭环（预估 2-3 个工作日）：**
1. `folders` 表 + `sessions.folder_id` 列 + `ChatFolder` 模型 + mutator（含 `==`/缓存失效/markDirty 全套）。
2. 列表：可折叠文件夹 Section，sortKey/红点运行时聚合，未分组平铺混排（或简化为固定文件夹区）；**加「只看分组」筛选模式**（2.9——混排会把夹子冲到底部，这是它的必要配套；实现就是 `filteredSessions` 再加一层 `folder_id != nil`，下游零改动）。展开态按 2.5——**原地展开、上下虚化夹层、内层直接复用 `groupedSessions` 的时间分桶**（该函数已是纯函数，零改动）；单一滚动容器，禁止 List 套 List。头部图标按 2.6——**组内 top3 会话的 category 图标去重合成**，与 sortKey/红点在同一次 O(n) 遍历里产出。折叠态还要按 2.7 **透传组内"运行中/暂停"状态**（同一趟聚合出 anyActive/anyPaused，展开态不重复显示；只订阅 `activeSessions` 的 any 结果，绝不透传高频的 toolStatus）。
3. 入口（2.1.1~2.1.4）：多选操作栏 "移入文件夹" sheet（含新建）+ 行长按 "移入文件夹"（Button 弹同一 sheet，非 submenu）；文件夹头长按：改名 / 解散 / 删除全部会话 / 在此分组新建会话；**长按拖拽入夹**（`.draggable` + `.dropDestination`，与 contextMenu 系统仲裁共存；可延后，非能力增益）。
4. AI 辅助两条路径：① 多选 sheet 里的 "✨AI 建议"（可新建夹，带确认步）；② **自动分组**——设置-外观-分组设置开关，默认 OFF，开启后随标题生成同一次调用回填**夹名**（本地解析成 id 落库），只并入已有夹、允许 null（2.3）。
5. 同步：`folder_id` field + `FolderV2` 类型，六接线点齐活。

**留到 V2+：**
- 文件夹**拖拽重排**（`sort_index` 已预留）——注意「拖会话入夹」已提到 V1（2.1.4），留在 V2 的只是拖动夹子本身调顺序
- 独立"管理文件夹"页面
- 全库 AI 自动整理（"把我所有会话归类"batch 流程——prompt 上下文、分页、确认 UI 都复杂一个量级）
- 多标签（多对多）、文件夹嵌套
- 其余文件夹级操作（一键全部已读、批量导出、按夹静音通知）——注意「解散」「删除全部会话」「组内新建」三条已在 V1 落地，见 2.1.3
- `category` → 文件夹的一键种子化（"按已有 category 自动建夹"，作为 AI 整理的廉价替代先试水价值）

---

## tl;dr

1. **多对一 `sessions.folder_id` + 新 `folders` 表**，照抄 `pinned_at` 的完整先例路径；别忘 `ChatSession.==`（`ChatStore.swift:83-92`）这个列表刷新暗坑。命名用 **Folder**，避开与 ModelGroup 的三重 "group" 冲突。**主键用本地 UUID、`name` 不加 UNIQUE、允许多端同名夹并存**——UUID 的唯一性无需跨端协调（同 id 冲突不会发生），而名字当主键会让改名退化成跨端撕裂的删+建+迁移。冲突全景见 3.3.1。
2. **排序/红点纯运行时派生**：列表本来就全量在内存分桶（`ContentView.groupedSessions:1005`），同一个 O(n) 里顺手聚合 max(updatedAt)/anyUnread，个人应用量级不需要 groupSummary 缓存表。
3. **交互 = 三入口，共用一个 picker sheet**（2.1.1~2.1.3）：① 多选操作栏 "移入文件夹"（基建全在，`ContentView.swift:2558`）；② 行长按菜单 "移入文件夹"——**用 Button 弹同一个 sheet，不做内联 submenu 列文件夹**（菜单体是 226s hang 的历史现场，`:1913`）；③ 文件夹头长按 = **解散分组**（只清引用不删会话）/ **删除分组及全部会话**（真删，复用 `computeDeleteInfo` 与现有多选删除链路）/ **在此分组新建会话**（草稿机制下 folder 归属须延到转正落库时写，不能在建草稿时写）。前两者并列是最高误操作风险点——靠文案带数量、只有后者染红、destructive 沉底三重区分。展示用**可折叠文件夹 Section，原地展开 + 上下虚化夹层**（`.ultraThinMaterial` + gradient mask，**不用 `.blur`**——离屏渲染在这个已有两起性能事故的列表上是红线；且禁止 List 套 List，内层行插进同一个滚动容器）；内层时间分桶**直接复用 `groupedSessions`**（已是纯函数）；folder 头图标 = 组内 top3 会话 category 图标去重合成（`categoryIcon` 需先从 `SessionRow` 提成纯函数，注意 `:4217` 有重复实现要一并合并）。未分组会话保持平铺混排，不做兜底组，但**必须配一个「只看分组」筛选模式**（2.9）——否则夹子会被活跃的散会话冲到列表底部；落点是 `filteredSessions`（`:999`）这个唯一漏斗，入口用常驻分段控件而非工具栏图标（持久化的隐式筛选态会让用户以为会话丢了）。
4. **AI 分两条路径**：手动 "✨AI 分组" 复刻 `callSubModelForTitle` 形态（可新建夹，**必须带确认步**）；**自动分组**（设置-外观开关，默认 OFF）则直接扩 `callSubModelForTitle` 的 schema 为 `{title, category, folder|null}`——**模型层收发夹名、存储层仍用 id 主键**（名字当主键会让改名退化成跨端会撕裂的删+建+迁移）——与标题同一次调用，不新增往返，**只并入已有夹、prompt 必须显式撑住"可以不分组"**（无夹时跳过、手动归属不覆盖、解析失败不能带崩标题）。
5. **V1 就带 iCloud 同步**（folder_id 走 SessionV2 field LWW；FolderV2 新类型六接线点缺一不可）；删夹只清引用不删会话，孤儿 folder_id 视同未分组。V2 再做拖拽、批量 AI 整理、多标签。
