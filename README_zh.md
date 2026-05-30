<p align="center">
  <img src="web/public/icon.svg" width="88" alt="OpenMuse">
</p>

<h1 align="center">OpenMuse</h1>

<p align="center">
  Meta <a href="https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/">Muse</a> 的开源实现：一个在手机上替你做事的个人 Agent，关掉 App 也会继续干活，做任何不可撤销的事之前先问你。自托管，模型任选。
</p>

<p align="center">
  <a href="https://github.com/OpenMuseAgent/OpenMuse/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/OpenMuseAgent/OpenMuse/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/openmuse/"><img alt="PyPI" src="https://img.shields.io/pypi/v/openmuse.svg"></a>
  <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue.svg">
  <br>
  <a href="README.md">English</a> · 简体中文
</p>

<p align="center">
  <img src="docs/demo.gif" width="300" alt="手机上的 OpenMuse：一个任务从提出到做完，中途只审批一次">
</p>
<p align="center">
  <sub>一个任务从头到尾：<em>“给我做一份京都 4 天的行李清单……然后提交到我的 kyoto-notes 仓库。”</em> Agent 先在工作区里找到仓库，在第一条 <code>git</code> 命令前停下来问一次——选“本次任务内允许”，后面的提交就不用再点——写出一页可以在手机上逐项打勾的清单，提交，回复里直接链到这个文件。DeepSeek V4.1 Flash 上的真实运行，共 52 秒，剪掉了中间等待的部分。</sub>
</p>

<p align="center">
  <img src="docs/screenshots/chat-approval.png" width="24%" alt="带审批卡片的聊天">
  <img src="docs/screenshots/goal-detail.png" width="24%" alt="目标与计划">
  <img src="docs/screenshots/ideas.png" width="24%" alt="Ideas 页签">
  <img src="docs/screenshots/settings.png" width="24%" alt="Sentinel 设置与沙箱">
</p>

## 从这里开始

| 你想… | 看这里 |
|---|---|
| 安装并在手机上打开 | [安装](#安装) → [快速开始](#快速开始) |
| 在终端里用 | [CLI](docs/cli.md) |
| 接 DeepSeek、OpenAI、Ollama 或公司网关 | [模型](#模型) · [配置](docs/configuration.md) |
| 搞清楚它什么会直接做、什么会先问 | [Sentinel](#sentinel) · [docs/sentinel.md](docs/sentinel.md) |
| 接邮箱、日历、通讯录、浏览器或 MCP 服务器 | [配置 → Connectors](docs/configuration.md#connectors) |
| 读代码 | [架构](#架构) · [docs/architecture.md](docs/architecture.md) |
| 用 Docker 跑 | [部署](docs/deployment.md) |
| 在（模拟）手机上把它当成一个 App 用，通知也有 | [demo/mobilegym](demo/mobilegym/README.md) |

## 它能做什么

Meta 的 Muse 不是聊天机器人，而是一个动手的 Agent：查资料、做计划、写文件、发邮件、花几周推进一个目标，而每个有风险的动作都要经过一个独立的守门人。OpenMuse 把这套东西在开源世界里重做了一遍：

- 一条和你的 Agent 之间的长对话，外加处理独立任务的侧边聊天。工具调用以内联小块展示，点开可看参数和输出。可以从手机直接发照片和文件——一张收据、一份合同 PDF、一个表格——Agent 按里面的内容干活；图片会交给能看图的模型，看不了图的模型则会被明确告知，不会瞎猜。
- 审批卡片。任何难以撤销的事（一条 shell 命令、一封邮件、读过私密数据之后的网络请求）都会停下来等你点一下。每次授权都有范围——仅此一次、本次任务、重启前、24 小时、始终——并且绑定到具体对象：`git` 命令、发给某个地址的邮件、某个网站。你授予过的每项权限都列在头像下面，可以单独撤销。
- 比对话活得更久的目标。Agent 把目标拆成步骤，边做边更新，还能在 App 关闭时按定时器继续推进，并把进展发到主聊天里。
- Ideas：基于你的目标、记忆和近期对话给出的下一步建议。
- 你能看、能改的记忆。Agent 记下的关于你的长期事实在页签里一览无余，点一下就能让它忘掉。事实变了就更新原条目而不是再加一条；定期整理会合并意思相同的条目、去掉并非事实的内容——每处改动都列出来，可一键撤销。召回既按关键词，也可按含义——接上任意 OpenAI 兼容的向量接口（比如 DeepSeek 旁边跑一个 Ollama 的 `qwen3-embedding`），“写邮件给房东”就能找到 “the landlord is Bob Li”。
- Sentinel 守门人、凭据保险库、污点追踪和只追加的审计日志。见 [Sentinel](#sentinel)。
- Skills（技能）：把一件事怎么做写下来，一次就够。内置五个（每周回顾、旅行计划、收件箱分拣、多选项对比、会议准备）；请求对得上时 Agent 自己会选，你也可以直接输入 `/trip-plan 十一月去京都`。一件事做顺了，说一句“把这个存成技能”，它就把步骤写下来——先经你同意。用的是 [Agent Skills](https://agentskills.io) 的 `SKILL.md` 格式，给其他智能体写的技能在这里同样能用。
- 工具：文件、shell、Python、网页搜索（开箱即用 DuckDuckGo；想要始终可用的搜索，可换成 Brave、Tavily 或你自己的 SearXNG）与抓取、邮件（一次性验证码在模型看到之前就被抹掉）、日历（通过私密 `.ics` 链接读取；它提议的日程会变成一张卡片，点一下加入日历）、通讯录（导入 `.vcf` 或在聊天里告诉它——写信前先查人，不猜地址）、可选的 Playwright 浏览器，以及任何 [MCP](https://modelcontextprotocol.io) 服务器。
- 任何 OpenAI 兼容模型都能跑：DeepSeek、OpenAI、OpenRouter、Ollama、vLLM，或者带自定义请求头的公司网关。

## 为什么是 OpenMuse

- **它是一个 Muse，不是 bot 框架。** 一个有名字有头像的 Agent，一个带 Chat / Feed / Ideas / Goals / Library 页签的手机 App，审批卡片，后台干活。如果你想要的是 Telegram 或 Discord 里的机器人，看看[相关项目](#相关项目)。
- **安全是架构，不是一个开关。** Agent 从不直接碰工具。独立的 `Sentinel` 对每次调用裁决 allow / ask / deny，在执行前替换 `{{vault:NAME}}` 占位符（密钥不进模型），追踪污点（读过私密数据后，新的网络目的地需要审批），并记录一切。
- **模型自带。** Chat Completions 或 Responses API，流式输出，`<think>` 处理，原生或基于提示词的工具调用。
- **小到能读完。** 约 7k 行带类型标注的 Python 和 3k 行 TypeScript，底下没有编排框架。

## 安装

需要 Python 3.11 或更新。手机 App 已预先构建并打进包里，只有改 `web/` 时才需要 Node。

```bash
uv tool install openmuse
# 或：pip install openmuse
```

要最新的 git 版本：`uv tool install git+https://github.com/OpenMuseAgent/OpenMuse.git`。从源码开发：

```bash
git clone https://github.com/OpenMuseAgent/OpenMuse.git && cd OpenMuse
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

可选：`openmuse[browser]` 增加 Playwright 浏览器工具（然后 `playwright install chromium`）。

## 快速开始

```bash
openmuse config init                 # 生成 config/config.toml
export DEEPSEEK_API_KEY=sk-...       # 默认配置用 DeepSeek，其他见下方“模型”
openmuse serve --host 0.0.0.0        # 打印链接和二维码
```

用手机扫码（同一 Wi-Fi），或在本机打开链接。链接里带一次性访问令牌；把页面添加到主屏幕，它就像一个 App。然后试试：

- *“对比 Sony WH-1000XM6 和 Bose QuietComfort Ultra 哪个更适合长途飞行，把简短对比写到 headphones.md”*
- *“看看这台机器还有多少磁盘空间”*——这一条会弹出审批卡片。
- *“建一个目标：12 月去京都之前学会日常日语对话，每天 30 分钟”*——然后打开 Goals 页签。

更习惯终端？`openmuse chat` 给你同一个 Agent，审批在控制台里完成；`openmuse run "任务"` 跑一件事就退出。哪里不对？`openmuse doctor` 会检查配置、模型和各项连接，并告诉你该修什么。见 [docs/cli.md](docs/cli.md)。

## App

`openmuse serve` 启动一个常驻的 Agent，并在同一个进程里提供移动端优先的 Web App（FastAPI + WebSocket 推送实时事件；客户端是 React，打进 Python 包里）。

<p align="center">
  <img src="docs/screenshots/chat-research.png" width="24%" alt="带工具小块和文件产物的调研">
  <img src="docs/screenshots/skills.png" width="24%" alt="技能：内置的和你自己的">
  <img src="docs/screenshots/memory.png" width="24%" alt="Memory 页签">
  <img src="docs/screenshots/calendar-event.png" width="24%" alt="Agent 起草的日程，点一下加入日历">
</p>

| 页面 | 内容 |
|---|---|
| Chat | 消息式对话、流式回复、可展开的工具小块、文件产物（回复里提到的文件点一下就打开）、审批与提问卡片、侧边聊天。Agent 干活时你可以继续输入，新消息会并入正在进行的这一轮。它用浏览器时会出现一张实时的浏览器卡片，每一步之后都能看到页面——点开围观，*接管*自己登录或处理需要人的事，交还后 agent 接着干。 |
| Feed | 你不在时发生了什么：每次后台推进的结果、它生成的文件，以及任何聊天里仍在等你处理的卡片。“Next up” 告诉你下一次会做什么。 |
| Ideas | 五条建议，按需重新生成。点一下就作为消息发出。 |
| Goals | 按生活领域（健康、财务、职业、学习……）分类的目标，每个都有计划、步骤状态与备注、目标日期，以及可选的打卡提醒——到点发一条简短消息，仅此而已。当 agent 了解到的情况和计划不再吻合时，它会提出调整方案，由你接受或保留自己的计划。主动性档位（关 / 低 / 默认 / 高）和安静时段决定你不在时它多久推进一次、什么时候才出声——没什么可说的那一轮只留一行小字，不会变成一条消息。 |
| 提醒 | “六点提醒我给妈妈打电话”——到点在你说这句话的那个聊天里发一条消息，仅此而已。“每个工作日 07:30 查一下路上的天气，一句话”——这是例程：agent 到点用工具把事做了再汇报。不受主动性等级和免打扰时段影响；在“即将进行”里和终端里都能看到。 |
| 技能 | Agent 照着做的配方：内置的五个、你手写或粘贴链接导入的，以及它在一件事做顺之后自己存下来的（会先问你）。聊天里输入 `/` 就能挑；任何一个都可以关掉；你的同名技能会替代内置的那个。 |
| 触发器 | 由外界事件而非时间启动的工作。“房东回信时，帮我总结并起草回复”（新邮件）、“任何评审开始前半小时给我一份简报”（日历）、“我的部署脚本调用你时，检查网站是否正常”（任何程序都能 `POST` 的 Webhook 地址）。邮件、日程或请求本身就是 agent 的上下文——只当数据、绝不当指令——结果出现在动态里。 |
| Library | Agent 做出来的一切——网页、文档、追踪表、图片——直接在 App 里打开。网页在沙箱里渲染，拿不到你的 token，也调不了 API。 |
| 头像 | 菜单：跨所有聊天的审批队列、活动记录、你授予的权限（可逐条撤销）、即将进行的事（后台工作、打卡、提醒、触发器）、记忆、技能、连接，以及设置（名字、头像、性格、Sentinel 模式、后台工作、语言）。 |
| 连接 | 在手机上接入一切：模型（服务商预设、密钥直接进 vault、一键测试）、邮箱（收发邮件，保存时校验登录）、日历（Google / Outlook / iCloud / Fastmail 的私密 `.ics` 链接，保存在 vault 里；当天日程显示在 Feed 里）、通讯录（上传 `.vcf` 导出；写信前 agent 先查人，审批卡上直接显示收件人是谁）、浏览器、MCP 服务器，以及 vault 本身。密钥和密码永远不会经过模型。 |

第一次打开时会先走一段简短的引导：你的名字、你的 Muse 的名字和风格、模型和密钥、可选的邮箱、日历和通讯录。`config.toml` 已经写全的话可以直接跳过。

把它添加到主屏幕并在设置里打开通知：agent 需要审批、有问题要问、后台做完了一件事，或者到了提醒、打卡的时间，手机就会响——走浏览器标准的 Web Push，不用在任何地方注册账号——图标上还会显示有几张卡片在等你。需要 `https://` 或 `localhost`，见 [部署说明](docs/deployment.md)。

App 走一套很小的 REST + WebSocket API，见 [docs/app.md](docs/app.md)，其他前端可以基于同一个服务端构建。

想看 Muse 本来该有的样子——手机上众多 App 里的一个，需要你时从通知栏冒出来——[demo/mobilegym](demo/mobilegym/README.md) 把 OpenMuse 作为原生 App 装进 [MobileGym](https://github.com/Purewhiter/mobilegym)（一个跑在浏览器里的 Android 模拟器）。一个浏览器标签页，不需要设备。

## Sentinel

每次工具调用在执行前都要经过 `Sentinel`。工具声明风险等级（`safe` / `moderate` / `sensitive`），并可对特定调用升级（`shell` 遇到 `rm -rf`，`python_execute` 的代码访问网络或环境变量，`web_fetch` 遇到内网 IP——包括重定向之后）。裁决顺序，首个匹配生效：

1. `deny_tools` → 拒绝
2. 对参数做 glob 匹配的 `[[sentinel.rules]]` → 规则指定的动作
3. `always_allow_tools` / `always_ask_tools`
4. 污点：本会话读过私密数据（邮件、记忆、工作区外文件）**且**本次调用向 `egress_allowlist` 之外的主机发送数据 → 询问
5. 风险 × 模式：`ask` 对 sensitive 询问，`strict` 对 moderate 也询问，`auto` 放行一切未被拒绝的调用
6. 带警告的调用（`sudo`、`curl | sh`、会删文件的代码）无论什么模式都会询问；只有显式规则能放行

```toml
[sentinel]
mode = "ask"                              # ask | strict | auto
always_ask_tools = ["send_email", "shell"]
egress_allowlist = ["*.wikipedia.org", "github.com", "*.github.com"]

[[sentinel.rules]]
tool   = "shell"
match  = { command = "*rm -rf*" }
action = "deny"
```

密钥存在 Fernet 加密的保险库里（`openmuse vault set EMAIL_PASSWORD`，或在 App 的「连接」页填写）。配置和工具参数用 `{{vault:EMAIL_PASSWORD}}` 引用；Sentinel 在执行前一刻替换真实值，并在工具输出里把它脱敏，模型始终看不到。Shell 命令和 Python 脚本运行时会剥掉所有看起来像凭据的环境变量。每次裁决都追加到 `~/.openmuse/audit.jsonl`。细节，以及一份坦白的「不覆盖什么」清单，见 [docs/sentinel.md](docs/sentinel.md)；漏洞报告见 [SECURITY.md](SECURITY.md)。

## 模型

编辑 `config/config.toml` 里的 `[llm]`，任何 OpenAI 兼容接口都行：

```toml
[llm]
provider = "openai"                    # Chat Completions；Responses API 用 "openai_responses"
model    = "deepseek-flash"
base_url = "https://api.deepseek.com"
api_key  = "${DEEPSEEK_API_KEY}"

# OpenAI:      model = "gpt-5.6-sol"  base_url = "https://api.openai.com/v1"   api_key = "${OPENAI_API_KEY}"
# Ollama:      model = "qwen3:8b"     base_url = "http://localhost:11434/v1"   api_key = "ollama"
# OpenRouter:  model = "deepseek/deepseek-flash"  base_url = "https://openrouter.ai/api/v1"
# 需要自定义请求头的网关：  extra_headers = { "X-End-User-Id" = "openmuse" }
# 静默忽略 `tools` 字段的端点：  tool_mode = "prompt"   （直接拒绝 tools 的端点由默认的 "auto" 自动降级处理）
```

同样的设置也可以用 `OPENMUSE_LLM_MODEL`、`OPENMUSE_LLM_BASE_URL`、`OPENMUSE_LLM_API_KEY`、`OPENMUSE_LLM_PROVIDER` 覆盖。完整参考：[docs/configuration.md](docs/configuration.md)。

本地模型可用：Ollama 上的 `qwen3:8b` 以原生工具调用通过了[模型检查脚本](scripts/provider_check.py)的五个日常任务，`gemma3:4b` 通过提示词降级模式通过。结果与设置见 [docs/configuration.md → Local models](docs/configuration.md#local-models)；运行 `python scripts/provider_check.py` 一分钟内就能知道你的模型表现如何。

## 架构

```mermaid
flowchart LR
    P([手机 / 浏览器]) <-- WebSocket + REST --> S[MuseService<br/>线程、调度器、Ideas]
    C([终端]) <--> A
    S <--> A[MuseAgent 循环]
    A <--> LLM[(任意 OpenAI 兼容模型)]
    A --> G{{Sentinel}}
    G -- allow --> T[工具]
    G -- ask --> P
    G --> AU[(audit.jsonl)]
    G <--> V[(vault.enc)]
    T --> F[files · shell · python]
    T --> W[web_search · web_fetch · browser]
    T --> E[email · calendar · contacts]
    T --> MCP[MCP 服务器]
    T <--> M[(memory.db)]
    T <--> GO[(goals.db)]
```

| 模块 | 文件 |
|---|---|
| Agent 循环、系统提示、上下文窗口 | `openmuse/agent/core.py`、`openmuse/prompts.py` |
| Sentinel：策略、审批、污点、审计 | `openmuse/sentinel/` |
| 凭据保险库 | `openmuse/vault/` |
| 工具与 MCP 适配 | `openmuse/tools/` |
| LLM 提供方、`<think>` 过滤、提示词工具调用 | `openmuse/llm/` |
| 记忆与目标（SQLite） | `openmuse/memory/`、`openmuse/goals/` |
| App 服务端：服务、REST/WebSocket API、时间线 | `openmuse/server/` |
| 手机 App（React、Vite、Tailwind） | `web/` → 构建到 `openmuse/server/static/` |
| 终端 UI 与 CLI | `openmuse/console.py`、`openmuse/cli.py` |

更多见 [docs/architecture.md](docs/architecture.md)。

## OpenMuse 与 Meta Muse

| Meta Muse | OpenMuse |
|---|---|
| 每个用户一台 Secure VM | 跑在你的机器或 Docker 里；Linux 上每次 `shell` / Python 调用都有独立的 [bubblewrap](https://github.com/containers/bubblewrap) 命名空间——只能写工作区、看不到主目录、不需要网络就没有网络 |
| Sentinel 审批敏感动作 | `Sentinel` 策略引擎：allow / ask / deny、规则、污点追踪、出站白名单 |
| 凭据不进模型 | 加密保险库 + `{{vault:NAME}}` 占位符 + 输出脱敏 |
| 记得你 | Agent 维护、你可编辑的 SQLite 记忆 |
| 后台推进目标 | 带步骤的目标；调度器推进并向聊天汇报 |
| 带聊天、目标、审批的手机 App | `openmuse serve` 提供的移动端优先 Web App，可添加到主屏幕 |
| Meta 自家模型 | 任意 OpenAI 兼容模型 |
| 闭源 | MIT |

## 文档

- [配置](docs/configuration.md)：所有设置、环境变量覆盖、连接器、MCP
- [Sentinel](docs/sentinel.md)：裁决顺序、规则、污点追踪、保险库、审计
- [App 与 API](docs/app.md)：手机访问、令牌、线程、审批、接口
- [CLI](docs/cli.md)：`chat`、`run`、`serve`、`daemon`、`goals`、`memory`、`vault`、`audit`、`config`
- [架构](docs/architecture.md)：源码地图与扩展点
- [部署](docs/deployment.md)：Docker、Compose、常驻运行
- [排障](docs/troubleshooting.md)

## 路线图

- [x] Agent 循环、Sentinel、保险库、审计、记忆、目标、工具、MCP、CLI
- [x] 移动端优先 App：Chat · Feed · Ideas · Goals · Library、带作用域授权的审批卡片、侧边聊天、后台推进目标
- [x] 有审批等待或目标有进展时的推送通知
- [x] 浏览器视图：实时观看 Agent 浏览网页，登录时接管
- [x] 本地模型（Ollama），自动降级到提示词工具模式
- [x] 触发器：新邮件、日程、webhook 都能启动工作；定时的部分由例程负责
- [x] 日历连接器：任意私密 `.ics` 链接或文件；日程、空闲时间、起草的日程以“加入日历”卡片给出
- [x] 联系人连接器：`.vcf` 导出与链接、agent 自己的名册、审批卡上显示收件人是谁
- [x] 记忆保持整洁：按稀有词召回、更新而非重复、定期整理并可撤销
- [x] 按含义召回：记忆通过任意 OpenAI 兼容的 `/embeddings` 接口只向量化一次，与关键词召回合并排序
- [x] `shell` 与 `python_execute` 每次调用独立沙箱（Linux 上用 bubblewrap）
- [x] Skills：Agent Skills `SKILL.md` 格式的可复用任务配方——内置的、你写的、Agent 自己存下来的
- [x] App 简体中文界面（设置 → 应用语言）；欢迎补充更多语言——每种语言一个字典文件

## 参与

拿它做一件真事，报告哪里坏了，然后挑一个具体的点改进。开发环境见 [CONTRIBUTING.md](CONTRIBUTING.md)；CI 跑 `ruff`、`pytest` 和前端构建。

## 相关项目

- [nanobot](https://github.com/HKUDS/nanobot)：一个轻量的个人助手框架，活在聊天软件里（Telegram、Discord、Slack、微信……）。想在已有的频道里放一个 bot，选它。OpenMuse 是一个按 Muse 的产品形态和安全模型做的单一 Agent，不打算做频道框架。
- [OpenClaw](https://github.com/openclaw/openclaw)：很多助手项目沿用的常驻网关思路。
- [browser-use](https://github.com/browser-use/browser-use)：浏览器工具里元素标注的做法来自这里。
- [Model Context Protocol](https://modelcontextprotocol.io)：OpenMuse 不用逐个写连接器的原因。

## 声明

OpenMuse 是独立的社区项目，与 Meta Platforms, Inc. 及其 Muse 产品无关，未获其认可，也不派生自它们。

## 许可证

[MIT](LICENSE)
