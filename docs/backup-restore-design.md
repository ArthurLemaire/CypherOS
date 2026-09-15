# Minis 全量数据备份 / 恢复（迁移）设计

> 状态：设计文档，未动任何业务代码。基于 2026-08-01 对 v1.10-dev 双端代码盘点（iOS + Android，关键结论均带 file:line 引用）。
> 目标：为 Minis 增加**用户可选类别、可加密**的全量数据备份与恢复，兼顾跨设备迁移与最强的版本/平台兼容性。（增量备份已明确不做，见 §6。）
> 术语：本文的"备份包"指导出产物 `.minisbak` 文件；"类别（Category）"指备份/恢复界面上用户可勾选的数据分组。

---

## 0. 现状盘点（为什么不能简单拷文件）

### 0.1 数据分布全景

两端的数据都散落在 **4 种介质** 上，且互相耦合：

| 介质 | iOS | Android |
|---|---|---|
| SQLite | `minis.db`（会话，WAL）、`provider-config.db`（user_version=2）、`skills.db`（**无 WAL**，SkillStore+MCPStore 共用）、`voice-correction.db`、`minis-config-audit.db`、`alarm-labels.db`、rootfs `meta.db` | Room：`databases/minis.db`（v10，9 个 Migration）、`databases/provider.db`（v3）；裸 SQLite：`databases/skills.db`、`databases/mcp.db`、**`files/minis-config-audit.db`、`files/voice-correction.db`（不在 databases/ 目录！）** |
| 文件 | 会话工作区 `Library/MinisChat/minis/<sid>/{attachments,offloads,workspace,browser}`；App Group `MinisFileProvider/{skills,memory}`（`SKILL.md`/`GLOBAL.md`/`SOUL.md`/daily）；App Group `MinisConfig/mcp-servers/servers.json`；rootfs `Documents/alpine-rootfs/` | `files/minis-sessions/<sid>/…`、`files/media/<yyyy>/<MM>/<dd>/…`、`files/minis-global/{skills,memory,mcp-servers}`、`files/alpine-rootfs/` |
| KV 设置 | UserDefaults standard（100+ 键，**大量运行时插值键**如 `cloudSync.device.\(id).enabled`，无法静态枚举）+ App Group suite；部分注册在 `ConfigRegistry`（`Shared/Config/ConfigRegistry.swift:3`，仅覆盖 agent 可见面） | ~35 个 SharedPreferences 文件，**无中央注册表**；未用 DataStore |
| 密钥 | Keychain 9 个 service：`com.openminis.app.provider.<instanceId>`（`ProviderConfigStore.swift:2916`）、`.envvar`、`.mcp-oauth`、三个 legacy OAuth、`.device`（设备身份，**随重装存活**） | EncryptedSharedPreferences（AndroidKeystore 主密钥）：`provider_secrets`、`oauth_prefs`、`mcp_oauth_secrets`、`env_var_values`、`minis_device_identity` |

### 0.2 已有代码的可用性结论

| 已有物 | 结论 |
|---|---|
| iOS `ICloudBackupManager.swift` | **死代码且部分是坏的**：整个文件 `#if DEBUG`（`:1`），全代码库无引用；备份的 skills/memory 路径是**过期路径** `Library/MinisChat/{skills,memory}`（`:120-121`），真实位置已迁至 App Group（`AIChatViewModel+RequestBudget.swift:267-275`）——即"Skills & Memories"备份实际抓不到东西。覆盖面也只有 minis.db + skills.db。**可复用其骨架**：staging → WAL checkpoint（`:239-253`）→ zip（`NSFileCoordinator(.forUploading)`，`:255-270`）→ 恢复时删 `-wal`/`-shm` → `reloadDatabase()`（`:490-610`）。 |
| iOS V2 Sync `SyncedTypes.swift` | **最大的现成资产**：12 个记录类型（SessionV2/MessageV2/CompactMarkerV2/SessionFileV2/SkillV2/ProviderConfigV2/MCPServersV2/EnvVarV2/SyncDeviceV2/SoulV2/MemoryGlobalV2/MemoryDailyV2）已是设备可移植的 Codable 序列化，且已把设备本地字段（`error_info`、`part_flags`，`ChatStore.swift:534-546`）排除干净。导出格式直接复用其编码器。 |
| Android `ChatExporter.kt` | 流式分页（BATCH_SIZE=50）导出 ZIP 的成熟先例，staging 模式照抄。 |
| Android `ProviderRepository.kt:1900-1990` | provider 实例导出 JSON **已刻意使用与 iOS 一致的字段名**（`apiKey`/`manualOAuthToken`/`oauthToken`/`oauthEmail`/`oauthGcpProject`，base64）——跨平台凭据格式以此为基准，不再发明第二套。 |
| Android Manifest | **现存 bug**：`allowBackup="true"` 且无 `dataExtractionRules`/`fullBackupContent`（`AndroidManifest.xml:156`）。Google 自动备份会抓多 GB rootfs（超 25MB 配额→整备份静默失败）；更糟：恢复时 Tink keyset 还原而 Keystore 主密钥不还原 → `AEADBadTagException`，`EncryptedPrefsFactory` 的自愈是**删光凭据**（`util/EncryptedPrefsFactory.kt:14-18,47-53`）。**与本功能无关也应先修（阶段 0）。** |

---

## 1. 核心决策：导出逻辑数据，不拷 DB 二进制

| 维度 | 拷 DB 文件 | 导出逻辑行（JSONL） |
|---|---|---|
| 跨平台 iOS↔Android | ❌ 两端 schema 完全不同 | ✅ |
| 向前/向后版本兼容 | ❌ 旧 app 打不开新 DB | ✅ 未知字段忽略、缺失字段给默认值 |
| 选择性恢复（按类别/按会话） | ❌ 全有或全无 | ✅ |
| WAL 一致性陷阱 | ⚠️ 必须 checkpoint 或三文件原子拷贝 | ✅ 无关 |
| 实现成本 | 低 | 中 |

**结论：JSONL 逻辑导出。** 不选 SQL dump —— SQL 把恢复端锁死在导出时的表结构上（列改名即 import 失败），JSONL 天然容忍 schema 演进；且 iOS 侧 `SyncedTypes` 已是 Codable，零成本对接。

二进制拷贝仅保留一个场景：rootfs 的可选备份（§7，本来就是不透明块）。

---

## 2. 备份包格式 `.minisbak`

一个标准 ZIP（内层文件可加密，见 §5），扩展名注册给 App 以支持"点开即导入"。每个 `.minisbak` 都是**自包含的全量包**——恢复只需要这一个文件：

```
backup-20260801-1432.minisbak
├── manifest.json              # 永远明文（见 2.1）
├── data/                      # 结构化数据，按类别分文件（可加密）
│   ├── sessions.jsonl         # 每行一个 SessionV2
│   ├── messages.jsonl         # 每行一个 MessageV2（分片：messages-0001.jsonl…，单片 ≤64MB）
│   ├── compact_markers.jsonl
│   ├── webapp_shortcuts.jsonl
│   ├── skills.jsonl           # 元数据（skills.db 行）
│   ├── mcp_servers.json       # servers.json（$$VAR 占位保留，硬编码密钥重定向到 secrets）
│   ├── provider_config.json   # 结构（实例/模型条目/模型组/agent-loop 绑定），凭据不在此
│   ├── env_vars.json          # 仅元数据（名称/描述），值在 secrets
│   ├── voice_correction.jsonl
│   ├── mounted_folders.readonly.json  # 只读清单：曾挂载过哪些路径（不恢复，仅展示）
│   ├── memory/                # GLOBAL.md / SOUL.md / YYYY-MM-DD.md 原文
│   └── skills/<skillId>/      # SKILL.md + 附属文件原文
├── secrets.enc                # 凭据段：独立子密钥加密，独立勾选（见 §5.4）
├── blobs/
│   └── <sha256 前 2 位>/<sha256>   # 内容寻址：附件/媒体/offload 文件（可加密）
└── blobs.index.jsonl          # sha256 → 逻辑路径 + 大小 + 所属会话 + mime
```

要点：

- **blob 内容寻址**：同一附件被多会话/多消息引用时包内只存一份，消息 parts 里的 MediaRef 经 `blobs.index` 间接寻址。
- **messages 分片**：单 JSONL 文件封顶 64MB，避免恢复端整读爆内存（iOS 侧已有 readFile jetsam 教训）。导出与恢复全程流式（每行独立 JSON）。
- 每个 `data/*` 文件对应一个类别（§3），**恢复端按需解压按需解密**，不勾选的类别根本不触碰。

### 2.1 manifest.json（永远明文）

明文是刻意的：用户在输入口令**之前**就要能看到"这个包是什么"。

```jsonc
{
  "format": "minisbak/1",            // 格式大版本；不认识 → 拒绝导入并提示升级
  "created_at": "2026-08-01T14:32:05Z",
  "app": { "platform": "ios", "version": "1.11", "build": "…" },
  "device_name": "iPhone 11",         // 展示用；不含 deviceId
  "backup_id": "uuid",
  "categories": {                     // 每类别：条目数 + 字节数 + 是否加密
    "chats":      { "entries": 342, "bytes": 128000000, "encrypted": true },
    "skills":     { "entries": 17,  "bytes": 240000,    "encrypted": true },
    "credentials":{ "entries": 9,   "bytes": 4100,      "encrypted": true },
    "...": {}
  },
  "encryption": {                     // 无加密时整段缺省
    "scheme": "minisbak-enc/1",
    "kdf": { "alg": "argon2id", "m_kib": 65536, "t": 3, "p": 1, "salt": "b64…" },
    "verifier": "b64…"                // §5.2，用于"口令错误"即时反馈
  },
  "integrity": {                      // 每个包内文件的 SHA-256（密文态哈希）
    "data/sessions.jsonl.enc": "…",
    "blobs.index.jsonl.enc": "…"
  },
  "manifest_mac": "b64…"              // §5.3，加密包对 manifest 本身的认证
}
```

### 2.2 兼容性规则（定死，写进代码注释与测试）

1. **format 大版本**不认识 → 拒绝导入，提示"请升级 App"。
2. 同大版本内：**未知 JSON 字段一律忽略；缺失字段一律给默认值**（两端解析器都必须用宽容模式 —— iOS 用带默认值的 Codable，Android 用 `org.json`/kotlinx 宽容配置）。禁止任何"字段必须存在"的断言。
3. 每条 JSONL 记录自带 `"t"`（类型）与 `"v"`（记录版本）字段，恢复端按 `t` 分发、按 `v` 做记录级迁移。**单条解析失败跳过并计数，不中断整体恢复**，结束后报告"N 条无法识别（可能来自更新版本）"。
4. 跨平台：格式即按平台无关设计（字段语义对齐 V2 SyncedTypes + Android provider 导出 JSON）。平台特有数据（如 iOS `SessionFileV2`）对方端导入时落到"已保留但本平台不使用"名单，不报错。

---

## 3. 类别划分（备份、恢复两侧同一套勾选）

| 类别 | 内容 | 默认 | 体积 | 敏感 |
|---|---|---|---|---|
| **Chats** 会话 | sessions/messages/compact_markers + 消息引用的 attachments（blob） | ✅ | L–XL | 低 |
| **Chat Artifacts** 会话重产物 | offloads / workspace / browser 截图 | ⬜ | XL | 中 |
| **Skills** | skills.db 元数据 + `SKILL.md` 及附属文件 | ✅ | S | 中 |
| **Memory & Soul** | `GLOBAL.md` / daily / `SOUL.md` | ✅ | S | **高（个人）** |
| **Providers & Models** | provider 结构、模型条目、模型组、agent-loop 绑定 | ✅ | S | 低（不含凭据） |
| **Credentials** 凭据 | API key、OAuth token、env var 值 | ⬜ **独立二次确认** | XS | **最高** |
| **MCP Servers** | servers.json | ✅ | XS | 中 |
| **Voice Corrections** | 学习词表/纠错字典 | ✅ | S | 中 |
| **Browser** | 历史、tab 状态 | ⬜ | S | 高 |
| **Rootfs** | Alpine 环境（§7） | ⬜ | XL | 中 |
| **WebApp Shortcuts** | webapp_shortcuts 行 + icon blob | ✅ | S | 低 |

### 3.1 永不备份名单（不给勾选，直接排除）

| 项 | 理由 |
|---|---|
| 设备身份：iOS Keychain `com.openminis.app.device` / Android `minis_device_identity` | 恢复到第二台设备 → 两台抢同一 CloudKit zone，直接损坏同步（`DeviceIdentity.swift:5-8`） |
| `minis.db` 全部 `sync_*` / `remote_*` / `deleted_*_tombstones` 表（`ChatStore.swift:636-779`）、`sync_state.json`、`cloud-sync-v2/`、`cloudSync.*` 键 | 纯同步脚手架；恢复等于冒充源设备的同步状态 |
| `mounted-folders.json`（两端） | security-scoped bookmark / SAF URI 跨设备必然失效；改为导出只读清单 `mounted_folders.readonly.json` 供用户参考重新挂载 |
| Cookie 备份目录（iOS 已自行排除，`CookieBackupStore.swift:398-400`）、`_plain_fallback` prefs（Android） | 会话密钥/明文密钥泄漏 |
| crash-loop / hang-detector / a11y / bash-install 计数、`alarm-labels.db` | 设备本地诊断态；alarm label 指向本机 AlarmKit/AlarmManager id，恢复即孤儿 |
| 隐私同意标志（`voiceCorrectionCollectionEnabled`、`aiDataSharingConsentAccepted` 等） | 同意属于"这台设备这次安装"，不随包迁移 |
| Caches、Logs、`debug_server_token`、`minis-config-audit.db` | 可再生 / 日志类，恢复价值≈0 |

---

## 4. Settings（UserDefaults / SharedPreferences）：**明确不在范围内**

> 决策（2026-08-01）：KV 设置**不备份、不同步、暂不考虑**。两端键空间不通用（iOS 100+ 键且大量运行时插值键无法静态枚举；Android ~35 个 prefs 文件无注册表），且多为设备/安装本地偏好，迁移价值低、denylist 维护成本高。本功能只做**通用数据**——两台设备（含跨平台）都能导入导出的内容。

若日后重启此项，历史方案（全量快照 + 前缀 denylist + `ConfigRegistry` 补显示名 / Android 显式 allowlist）见本文 git 历史初版（`96d2f496`）。

---

## 5. 加密机制设计（minisbak-enc/1）

### 5.1 目标与非目标

- 目标：① 口令加密整包数据与 blob；② **凭据段独立密钥**，可导出"不含凭据的可分享包"；③ 解密前可完整性验真 + 口令即时校验；④ 全部算法双端标准库/成熟库可得（iOS CryptoKit、Android Tink/JCA + argon2 绑定）。
- 非目标：不做公钥/多接收者加密（备份是给自己的）；不做防离线暴破之外的对抗（拿到包 + 弱口令仍可暴破 —— 用 Argon2id 参数把成本抬高并在 UI 强制口令强度）。

### 5.2 密钥层级

```
用户口令 passphrase
   │  Argon2id(m=64MiB, t=3, p=1, salt 16B 随机)      ← 参数明文写入 manifest.encryption.kdf
   ▼
KEK (32B)                                              ← 仅存在于内存
   │
   ├─ HKDF-SHA256(KEK, info="minisbak/verify")   → verifier_key
   │      manifest.verifier = HMAC(verifier_key, "minisbak-v1")[0..16]
   │      （口令错误 → verifier 不匹配 → 立即提示，不去碰数据）
   │
   ├─ HKDF-SHA256(KEK, info="minisbak/data")     → K_data     （data/* 与 blobs）
   ├─ HKDF-SHA256(KEK, info="minisbak/secrets")  → K_secrets  （secrets.enc 专用）
   └─ HKDF-SHA256(KEK, info="minisbak/mac")      → K_mac      （manifest 认证）
```

- Argon2id 双端一致优先；若 iOS 侧引入 argon2 依赖受阻，降级路径为 PBKDF2-HMAC-SHA256 600k 迭代，`kdf.alg` 字段区分 —— **解析端两种都必须支持**，格式不锁实现。
- KEK/子密钥只在导出/恢复过程驻留内存，完成即清零；口令不落任何持久层。可选"记住到系统 Keychain/Keystore（仅本机）"便于周期性自动备份（§6.1），存的是 KEK 而非口令。

### 5.3 文件加密格式

包内每个受保护文件（`data/*.jsonl` → `.enc`、`secrets.enc`、`blobs/*`）：

```
[ magic "MBK1" | 4B ] [ nonce 12B ] [ AES-256-GCM ciphertext | tag 16B ]
```

- **AES-256-GCM**，每文件独立 nonce。GCM 的 AAD = 该文件在包内的路径字符串（防止包内文件被调换位置重放，例如把旧 sessions.jsonl.enc 换名成 skills.jsonl.enc）。
- 大文件（blob、messages 分片）按 **4MiB 段** 独立 GCM 封装（段序号进 AAD：`"<path>#<seq>"`），支持流式加解密，避免整读内存 + 防段级截断/重排。
- blob 与其他文件一样使用**随机 nonce**（不做增量后无需跨包密文恒定）；包内去重发生在加密之前——同一 sha256 只加密、打包一次。
- `manifest.integrity` 记录**密文态** SHA-256：恢复端先验完整性（无需口令），再验 verifier（口令对不对），最后才解密。
- `manifest_mac = HMAC-SHA256(K_mac, canonical_json(manifest 除 manifest_mac 外))`：防 manifest 本身被篡改（如把 `categories.credentials` 从清单里抹掉、改 KDF 参数降级攻击）。无加密的包没有此字段，UI 明确标示"未加密备份，内容未认证"。

### 5.4 凭据段 secrets.enc

- 内容：按 §0.1 密钥清单，从 iOS Keychain / Android EncryptedSharedPreferences **在进程内解密读出明文**，组装为跨平台 JSON（字段名基准 = `ProviderRepository.kt:1900-1990` 已有的 iOS 对齐格式），再用 `K_secrets` 加密。
- **绝不搬运密文容器**：Android 的 EncryptedSharedPreferences XML 跨设备即密文垃圾，且 `EncryptedPrefsFactory` 遇解密失败会删库自愈（`:47-53`）；iOS Keychain item 本就不可导出。只有"明文中转 + 备份密钥再加密"一条路。
- 结构（示意）：

```jsonc
{
  "v": 1,
  "providers": [ { "instanceId": "…", "apiKey": "b64…", "oauthToken": "b64…", "oauthEmail": "…" } ],
  "envVars":   [ { "name": "…", "value": "b64…" } ],
  "mcpOAuth":  [ { "serverId": "…", "token": "b64…" } ]
}
```

- 策略约束：
  - 勾选 Credentials 时**强制要求已设口令**（无口令备份不允许包含凭据段——UI 直接联动禁用）。
  - 恢复凭据需**独立二次确认**，并明确提示：OAuth refresh token 可能设备绑定/已失效，失败时引导重新登录（恢复流程对每个 provider 做一次静默 token 有效性探测，失败标记"需重新授权"而非报错中断）。
  - 分享场景：UI 提供"导出副本（移除凭据）"一键动作 —— 因凭据是独立文件独立密钥，实现只是从 ZIP 剔除 `secrets.enc` 并重写 manifest，无需重新加密其余内容。

### 5.5 威胁模型小结

| 威胁 | 对策 |
|---|---|
| 备份文件落入他手 | AES-256-GCM + Argon2id 高成本 KDF + UI 口令强度门槛 |
| 篡改包内容（换文件/改清单/降级 KDF） | per-file AAD + manifest_mac + 密文态 integrity 哈希 |
| 恢复端被喂恶意包 | 解析全程宽容但有界（路径穿越检查：ZIP entry 路径必须匹配白名单模式，禁止 `../`；单条记录大小上限；恢复写入只落在既定目录） |
| 凭据被顺手分享出去 | 凭据独立文件独立密钥独立勾选 + 无口令不许含凭据 + 移除凭据一键导出 |
| 口令遗忘 | 无后门（明确告知用户）；manifest 明文让用户至少知道丢了什么 |

---

## 6. 增量备份：**明确不做**

> 决策（2026-08-01）：`.minisbak` 只做**自包含全量包**。每次备份独立完整，恢复只需一个文件，包之间无任何依赖。

理由：增量需要链管理（base+各环缺一不可）、本机水位线状态、删除事件捕捉（且受 tombstone 30 天 TTL 约束）、跨包 blob 寻址——复杂度全部转嫁给恢复端和用户的文件保管；而全量包配合 blob 内容寻址与流式导出，体积与内存已可控。若日后重启此项，链式多包方案（水位线 + `"external"` blob 指针 + 自动全量化）见本文 git 历史（`2ccec229`）。

### 6.1 （可选，后期）周期自动备份

KEK 存本机 Keychain/Keystore 后，可加"每日/每周自动**全量**备份到用户指定目录（iOS：Files/iCloud Drive；Android：SAF 目录授权），保留最近 N 份自动轮换"。不在首发范围。

---

## 7. Rootfs 的特殊处理

- rootfs 是**匹配对**：`meta.db` + `data/` 树必须同时同状态备份，任何一半单独恢复都会损坏 fakefs（iOS `RootfsManager.swift:36-48`；Android 同构）。
- 默认不备份（可从 bundle 资产再生，3.7–3.8MB 种子），提供两档可选：
  - **仅用户主目录**：`data/root/`（+ 对应 meta.db 行导出为 tar 流内嵌路径+mode 信息，绕开 meta.db 整库拷贝）。Android 已有先例 `RootfsManager.kt:191`（`rootfs-backup-root`，reset 时保 /root）。`data/var/minis/skills` 不备——它只是 App Group skills 的镜像，恢复后由 `SkillStore` 重新镜像（`SkillStore.swift:1561-1564`）。
  - **完整 rootfs**：整树 + meta.db 打成单一 tar.zst 进 blob（此处允许二进制拷贝——本就是不透明块，无跨版本 schema 问题；iSH fakefs 格式即其自身格式）。
- **恢复必须冷装**：写入 staging → 提示并要求重启 App 后由启动流程完成替换（`RootfsManager.didResetWhileBooted`（`:31`）已证明 kernel 无法在进程内重挂载）。`.arch` 标签随包携带，架构不匹配时拒绝恢复该类别并说明。

---

## 8. 恢复设计

### 8.1 流程

```
选包 → 读 manifest（明文）→ 展示包概要 + 类别勾选（含每类条目数/体积）
  → 若加密：要口令 → verifier 即时校验
  → 完整性校验（integrity 哈希，流式）
  → 预检（版本兼容、磁盘空间、rootfs 架构）
  → 快照当前状态到 staging（可回滚点，仅覆盖将被改动的类别）
  → 逐类别流式导入（按 §8.2 模式）
  → 各 store reload / 冷装项提示重启
  → 报告（成功 N 条 / 跳过 M 条 / 无法识别 K 条 / 需重新授权的 provider 列表）
失败任一步 → 从 staging 回滚 → 报告失败原因
```

### 8.2 每类别三种模式（默认 Merge）

| 模式 | 语义 |
|---|---|
| **Merge**（默认） | 按 id 匹配；`updated_at` 新者胜。会话冲突可选"两个都保留"（导入侧改新 id + 标题后缀） |
| **Replace** | 清空该类别后导入；红色确认 |
| **Skip existing** | 只补本机缺失的 id |

### 8.3 恢复端硬性规则

- 导入的会话/消息**不携带**任何 sync 状态 → 落库后走正常的 dirty 标记流程,由本机 sync 引擎按自己的设备身份重新上云（等价于本机新产生的数据）。**绝不**写入 `sync_pushed_records`/tombstone。
- blob 恢复：按 `blobs.index` 将内容寻址文件落回逻辑路径（`attachments/…` 等），消息 parts 中的 MediaRef 相对路径两端各自映射（iOS `Library/MinisChat/minis/<sid>/…` ↔ Android `files/minis-sessions/<sid>/…` + `files/media/…`）。
- Chat Artifacts 未包含时（默认如此）：悬空的 offload 引用渲染为"此内容未包含在备份中"占位（UI 层处理，不改数据）。
- 凭据恢复后逐 provider 静默探测有效性（§5.4）。
- webapp_shortcuts 的 `icon_cache_path`/`html_path` 是路径耦合列：恢复时按本机路径重写。
- 事务边界：每类别一个事务;跨类别失败只回滚未完成类别 + 报告，已成功类别保留（staging 快照支持整体回滚由用户选择）。

---

## 9. 落地路线

| 阶段 | 内容 | 备注 |
|---|---|---|
| **0** | 修 Android `allowBackup`：加 `dataExtractionRules`/`fullBackupContent`，排除 rootfs/cache/加密 prefs/`minis_device_identity` | **现存 bug，独立先行**（§0.2） |
| **1** | 格式定义 + manifest + 全量导出（Chats/Skills/Memory/Providers/MCP/Voice/Shortcuts，无加密无凭据）；blob 内容寻址**此时就位**（后补=返工） | iOS 先行,复用 SyncedTypes 编码器 |
| **2** | 恢复：Merge 模式 + 完整性校验 + staging 回滚 + 报告 | 与 1 同端联调 |
| **3** | 加密（§5 全量）+ Credentials 类别 + 移除凭据一键导出 | |
| **4** | Android 对等实现（导出+恢复+加密）；跨平台字段对齐联测 | 复用 ChatExporter 流式模式 |
| **5** | Replace / Skip existing 恢复模式 | |
| **6** | Rootfs 两档可选备份 + 冷装恢复；（可选）周期自动备份 | |

### 测试要点（每阶段随行）

- 宽容解析：注入未知字段/缺失字段/坏行的包必须正常导入并正确计数。
- 加密向量：双端各自实现对同一测试向量（固定 KEK/nonce/明文）产出逐字节一致的密文（参照 debug-server v1 的 test-vector 做法）。
- WAL/并发：导出期间持续写入会话,校验导出快照自洽（行与其引用的 blob 一致,不因并发写产生悬空引用）。
- 恢复回滚：每类别注入中途失败,验证 staging 回滚无残留。
- 跨平台：iOS 导出 → Android 恢复 → 再导出 → iOS 恢复,diff 语义等价。
- 大包：10 万消息 + 2GB blob 的内存水位（流式验证,峰值 <150MB）。

---

## 10. 已知开放问题（需产品拍板）

1. **offloads 默认排除**（当前设计）导致悬空引用以占位符呈现 —— 是否可接受？备选：默认包含但单文件大小封顶。
2. 跨平台迁移是否列为阶段 4 的**验收目标**（当前：格式支持、实现排期在 Android 对等实现之后）。
3. 备份包的存放/流转 UI：iOS 走 Files/分享面板、Android 走 SAF 另存 —— 是否还要内置 WebDAV/网盘直传（建议：首发不做,导出到文件系统由用户自选渠道）。
4. 口令策略：最小长度/强度门槛的具体数值（建议 ≥10 字符或通过 zxcvbn 强度 3）。
