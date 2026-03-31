<p align="center">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/app-icon.png" width="128" alt="nanoMuse app icon">
</p>

<h1 align="center">nanoMuse</h1>

<p align="center">一个智能体，你的所有设备。完全开源，Muse 的形。今天是 Android。</p>

<div align="center">
  <p>
    <a href="https://github.com/nano-muse/nanoMuse/blob/main/README.md">English</a> |
    <a href="https://github.com/nano-muse/nanoMuse/blob/main/README_zh.md">简体中文</a> |
    <a href="https://nano-muse.github.io/">网站</a> |
    <a href="https://github.com/nano-muse/nanoMuse/releases/latest">下载</a>
  </p>
  <p>
    <a href="https://github.com/nano-muse/nanoMuse/releases"><img src="https://img.shields.io/github/v/release/nano-muse/nanoMuse?include_prereleases&label=release" alt="最新版本"></a>
    <a href="https://github.com/nano-muse/nanoMuse/releases"><img src="https://img.shields.io/badge/Android-8.0%2B%20arm64-3DDC84?logo=android&logoColor=white" alt="Android 8.0+ arm64"></a>
    <a href="https://github.com/nano-muse/nanoMuse/actions/workflows/android.yml"><img src="https://github.com/nano-muse/nanoMuse/actions/workflows/android.yml/badge.svg?branch=main" alt="Android 构建"></a>
    <a href="https://github.com/nano-muse/nanoMuse/blob/main/LICENSE"><img src="https://img.shields.io/github/license/nano-muse/nanoMuse" alt="GPL-3.0-or-later"></a>
    <a href="https://github.com/nano-muse/nanoMuse"><img src="https://img.shields.io/github/stars/nano-muse/nanoMuse?style=flat&logo=github" alt="GitHub stars"></a>
  </p>
</div>

nanoMuse 是一个 Meta [Muse](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/) 形状的个人 AI 智能体——一个有名字、有脸的智能体，做事而不是只回答，App 关掉了也继续干活，记得你，遇到无法撤销的操作先停下来问你——以自由软件的方式做出来，面向你的所有设备。今天它是一个 Android App，整个智能体跑在**手机上**：Linux 根文件系统、shell、浏览器、MCP、技能和定时任务都在 APK 里，模型由你自己带。接下来它会长出一双能碰没有 API 的 App 的手——经你允许后操作手机自己的屏幕——再之后伸到你的其他设备：在手机上说一句，事在电脑上办好。没有服务器，不用注册，GPL-3.0。

<p align="center">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/avatar-moods.png" width="88%" alt="同一只小龙的五种状态：休息、工作、等你、开心、抱歉">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/screenshots/chat-approval.png" width="23%" alt="对话：删除文件前停下来问你">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/screenshots/feed.png" width="23%" alt="动态：今天早上写给你的几条">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/screenshots/goals.png" width="23%" alt="目标：按时检查，还有例程">
  <img src="https://raw.githubusercontent.com/nano-muse/nanoMuse/main/docs/screenshots/avatar.png" width="23%" alt="形象：描述一句，你的图像模型画四张，你挑一张">
</p>

## 为什么是 nanoMuse

四件事定义这个项目。两件今天已经在 App 里，两件是接下来的版本。

| | | |
|---|---|---|
| **Muse 的形** | 今天 | 一个智能体，不是一箱工具：名字和脸、第一次对话、写给你的动态、后台推进的目标、能看能改的记忆、无法撤销的操作前先审批。Meta 发布的那个产品，一屏一屏重做出来。 |
| **完全开源** | 今天 | GPL-3.0-or-later，整个仓库。没有闭源组件，不用注册，没有必须信任的服务器，没有必须用的模型；每个版本从它的 tag 构建、手动安装。Muse、豆包、千问是给你用的产品；nanoMuse 是你自己拥有的。 |
| **通用：有没有 API 都能做** | 下一步 | 国内的一天大多跑在从来没有 API 的 App 里。智能体沿着一把梯子往上爬——先是技能、CLI 或 MCP 服务，再是带你登录态抓一页，再是应用内浏览器，最后在你允许时用设备自己的屏幕，像你一样看和点——付款、发送、删除前的审批一样不少。默认关着。下一版先出一个能用的 demo。 |
| **多端协同** | 再之后 | 一个智能体，你的每台设备都是它的一双手和一个入口：在手机上说，事在电脑上办；对眼镜说，两边一起办。先是手机；然后手机操作你的电脑；再往后是桌面 App、iOS、你自己机器上的网页版、眼镜。 |

和 Muse、和 App 所基于的运行时 OpenMinis 的差别：[见下](#与-meta-muse-和-openminis-的比较)。计划和理由：[docs/roadmap.md](docs/roadmap.md)。

## 安装

1. 从[最新版本](https://github.com/nano-muse/nanoMuse/releases/latest)下载 `nanoMuse-<版本>-arm64.apk`——Android 8.0 以上的 64 位手机。想校验就 `sha256sum -c nanoMuse-<版本>-arm64.apk.sha256`。
2. 打开安装。Android 会问一次是否允许；每个版本都用同一把签名，直接覆盖安装升级，数据不丢。
3. 添加一个模型：任何 OpenAI 兼容接口配你自己的 key，或者 App 自带的 OAuth 登录。第一次对话它会问你叫什么，并给自己起名字。
4. 可选——「设置 → 图像与视频模型」：图像模型（阿里云百炼的 qwen-image-3.0、gpt-image-1，或任何有 OpenAI images 接口的服务商）让它能换脸、画图；视频模型（百炼上的 MiniMax-H3）让脸动起来。Muse 这两样是官方自带的，nanoMuse 用你自己的，缺哪个它会开口告诉你。

App 会到本仓库的 Releases 检查更新。每个版本的说明在 [docs/releases/](docs/releases/) 和 [CHANGELOG](CHANGELOG.md)。

## 能做什么

| | |
|---|---|
| **动手做事** | Linux shell、浏览器、MCP 服务、[Agent Skills](https://agentskills.io) 格式的技能，以及——开了无障碍服务后——通过屏幕操作手机上的 App，用的是 OpenMinis 自带的无障碍 CLI（0.1.12 会把它做成一双正式的手：视觉、梯子、接管、审批）。它自己挑合适的那只手，每一步都是一张能点开的卡片。 |
| **关键处先问** | 删除、发送、付款前先停下——shell 里和浏览器里都是——审批范围由你定：只此一次、本次对话、或对这个收件人 / 域名 / 目录一直允许，在「权限」里随时撤销。密码和验证码永远由你自己输入。 |
| **一直在干** | 目标在对话里定下来，然后在自己的会话里按时检查；例程在 App 关着时照跑；操作手机时屏幕不灭；到 200 步问你「继续？」而不是草草收尾。 |
| **写给你的动态** | 每天早上三到六条短帖，来自它对你的了解和你让它盯的事，做成卡片：可以点赞、在旁聊里讨论、删除。一句话就能调它的方向。 |
| **记得你** | 它是谁（`SOUL.md`）、知道你什么（`USER.md`）、记住了什么（`GLOBAL.md` 和日记）、什么时候醒（`HEARTBEAT.md`），是 App 里能看能改的文件。别的助手记住的你，用「导入记忆」贴过来。 |
| **有一张脸** | 一句话描述；你的图像模型画四张；你挑一张。App 再给它摆出每种状态的姿势——工作、等你、开心、抱歉——它会随着智能体在做的事呼吸、点头、歪头、跳一下、抖一下；设了视频模型，每个状态是一段循环短片。默认是一只奶黄色的小龙，静态图和短片都内置。 |
| **点子与资料库** | 从目标和记忆里来的、接下来可以问的事；以及它做出来的所有东西，带预览。 |

以上每一项都是 Muse 的某个页面或行为，在手机上重做了一遍；OpenMinis 其余的部分——终端、应用内浏览器、MCP 与技能管理、模型组、token 用量、无障碍执行器、共享文件夹——都保留着，从同样的菜单进。

## 怎么工作

App 是修改过的 [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13：一个完整的端侧智能体——[proot](https://github.com/nano-muse/proot) 下的 Alpine Linux、shell、WebView 浏览器、MCP、技能、定时任务、无障碍执行器、任何 OpenAI 兼容模型——用 `git subtree` 放进 [`android/`](android/)，上游版本仍能合并。nanoMuse 加的东西都在 `io.github.nanomuse.*`：

| 包 | 内容 |
|---|---|
| `ui/home`、`ui/header` | 首页外壳：一条主聊天、抽屉里的旁聊、动态 · 点子 · 目标 · 资料库底栏，Muse 的页头——脸、名字胶囊、状态行 |
| `guard` | `ShellGuard` 与 `BrowserGuard` 给命令和页面动作分类；`RiskGate` 拦下工具调用并弹出审批卡；授权按范围记住 |
| `goals`、`ideas`、`library` | 目标是带计划和检查的定时会话；点子来自记忆和目标；资料库是它写出来的东西 |
| `feed`、`sysfiles` | 每天早上把 ` ```nanomuse-feed ` 段写进 `minis-global/nanomuse/feed/` 的例程、卡片、那句指示；系统文件页和记忆导入 |
| `avatar`、`ui/avatar` | 架在 OpenMinis 图像接口（`images/generations`、`images/edits`、DashScope 原生编辑）上的 `ImageGen`、形象页、`AvatarStore`，以及会动的 `AgentAvatar` |
| `status` | 两级状态（脸下面是工具标题，卡片上是动作 chips）、`KeepAwake`、每个步骤的最后一帧浏览器画面 |

改到上游文件的地方都标着 `// nanoMuse:`；每次 subtree 拉取之后 `scripts/rebrand.py` 重新套一遍品牌。从源码构建见 [CONTRIBUTING.md](CONTRIBUTING.md)。你的消息只发给你配置的模型；文件、记忆和形象图片都在 App 的私有存储里。

## 版本

按小版本逐个发布，每个都是一个 GitHub release 加一个 APK。计划和理由见 [docs/roadmap.md](docs/roadmap.md)。

| 版本 | 代号 | 加了什么 |
|---|---|---|
| [0.1.1](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.1) | Foundation | OpenMinis 变成 nanoMuse：图标、名字、品牌色、关于 / 反馈 / 更新源、GPL 声明、一把签名 |
| [0.1.2](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.2) | Identity | 小熊猫和 Muse 样式的页头；第一次对话里给它起名；每条通知都带名字和脸 |
| [0.1.3](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.3) | Home | 打开就是对话而不是列表；旁聊在抽屉里；点子、目标、资料库；目标在对话里定、按时检查 |
| [0.1.4](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.4) | Guardrails | 删除、发送、付款前带范围的审批；密码永远由你输 |
| [0.1.5](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.5) | Memory | 动态；SOUL / USER / MEMORY / HEARTBEAT 可看可改；记忆导入；屏幕常亮；「继续？」 |
| [0.1.6](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.6) | Avatar | 你描述、你的图像模型画、你挑的脸，摆好每种状态并动起来；页面淡入淡出、卡片落进来、红心会跳 |
| [0.1.7](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.7) | Welcome | 第一次运行：欢迎页带三步——服务商、它提供的模型、认识它 |
| [0.1.8](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.8) | Polish | 壳子对齐 Muse：字体排印、胶囊输入框、脸下只有名字、灰色气泡、Muse 样式的设置页 |
| [0.1.9](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.9) | Portrait | 换脸照 Muse 的路：对话里说「把虚拟形象换成…」，四张候选任选，姿势、分享卡；点脸进入它的资料页；形象大小五档；名字牌按 Muse 重测 |
| [0.1.10](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.10) | Motion | 三个模型说清楚——对话、图像、视频——在「设置 → 图像与视频模型」里，也在它自己知道的事里；设了视频模型，形象每个状态一段循环短片；按需生图生视频；缺模型时由它开口说明，不是写死的提示 |
| [0.1.11](https://github.com/nano-muse/nanoMuse/releases/tag/v0.1.11) | Hatch | 内置小龙——静态图和循环短片都在 APK 里；第一次对话由对话模型来读：你说了别的它先答、稍后再问名字，给自己提的名字跟着你的语言；一把百炼 key 跑三个模型，或者每个模型各接一个平台 |
| 0.1.12 | Hands *（计划）* | 手机屏幕当手，先出一个能用的 demo：它看屏幕和无障碍树，在没有 API 的 App 里点、打字、滑动；技能、CLI、MCP 服务或浏览器能做的先用它们；一个带「停止」的悬浮胶囊；登录和验证码由你接管；付款、发送、删除前的审批一样不少；默认关着 |
| 0.1.13 | Reach *（计划）* | 手机操作你的电脑，先出一个能用的 demo：在 App 里配对一台电脑，手机上的一句话在那边执行——shell、文件、浏览器——结果和审批回到手机上；暂时是单向的，手机到电脑 |
| 0.2.0 | Beta | 头几周使用后的打磨；第一个 beta |

**再之后**，依次：一个既是自己的智能体、也是手机那个的客户端的桌面 App；iOS；你自己机器——一台 VM、一台家里的服务器——上的网页版，任何浏览器都能打开；眼镜。每加一台设备，就是同一个智能体多一双手、多一个入口。项目起步时的 Python 线——智能体和它的 Sentinel、网页 App、模拟手机——冻结在 tag [`pre-openminis`](https://github.com/nano-muse/nanoMuse/releases/tag/pre-openminis)，文档在 [docs/](docs/)，是桌面和网页这两个入口的底座。

## 与 Meta Muse 和 OpenMinis 的比较

| | Meta Muse | OpenMinis | nanoMuse |
|---|---|---|---|
| 是什么 | 作为服务的个人智能体：iOS、Android、网页、WhatsApp、Mac 客户端，连着每个用户一台的云端 VM | 跑在设备上的智能体 App，iOS 和 Android：Linux 沙盒、浏览器、设备工具、技能、记忆、工作区 | Muse 的产品，放在 OpenMinis 的端侧运行时上，以自由软件的方式做，面向你的所有设备 |
| 智能体跑在哪 | Meta 的云端 VM | 装了它的那台手机 | 今天在手机上；下一步在你的一台电脑上；再之后你说在哪就在哪 |
| 形状 | 一个有名字、有脸的智能体，动态、目标、Sentinel | 会话、工具、设置——一个工作台 | Muse 的：一个智能体，名字和脸、第一次对话、动态、按时检查的目标、能改的记忆 |
| 无法撤销的操作前 | Sentinel 模型审批 | 按工具授权 | `RiskGate` 拦下调用：只此一次、本次对话、对这个收件人 / 域名 / 目录一直允许、或拒绝；密码和验证码从不由它输入 |
| 没有 API 的 App | 碰不到——VM 里有浏览器，但碰不到你的手机 | Android 上有一个模型可以调用的无障碍 CLI（`android-a11y-cli`） | 屏幕是一双正式的手：视觉加无障碍树、先试 API 的梯子、登录时由你接管、同一套审批——0.1.12 |
| 其他设备 | 多个客户端连一台 VM；VM 不碰你的设备 | 只有装了它的那一台 | 一个智能体跨你的设备：先是手机操作电脑（0.1.13），再是所有设备、双向 |
| 形象 | 一个干活时会换姿势的毛绒形象 | — | 你的图像模型画出并摆好姿势的脸，每个状态一段你的视频模型做的循环短片；默认是一只已经会动的小龙 |
| 模型 | Meta 的 | 自己带 | 自己带——对话、图像、视频三个模型，或一把百炼 key 全包；OpenMinis 自带的 OAuth 登录保留 |
| 许可 | 闭源 | GPL-3.0 | GPL-3.0-or-later，基于 OpenMinis——致谢；上游版本仍可合并 |

## 参与

拿它做一件真事，报告哪里坏了，然后挑一件小而具体的事做。[CONTRIBUTING.md](CONTRIBUTING.md) 有构建环境（[android/BUILDING.md](android/BUILDING.md) 和 `scripts/android/` 里的工具链脚本）、约定（包名 `com.openminis.app` 不动，新代码放 `io.github.nanomuse.*`，改上游处标 `// nanoMuse:`，提交带 `Signed-off-by`）和发版方式。[Issues](https://github.com/nano-muse/nanoMuse/issues) · [Pull requests](https://github.com/nano-muse/nanoMuse/pulls)。

## 致谢

nanoMuse 站在别人的工作之上；条款见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

- [OpenMinis](https://github.com/OpenMinis/OpenMinis)——App 所基于的端侧智能体：proot Linux、shell、浏览器、MCP、技能、定时任务、无障碍执行器。
- [proot](https://github.com/proot-me/proot)（经 [nano-muse/proot](https://github.com/nano-muse/proot)）与 [Alpine Linux](https://alpinelinux.org/)——APK 里的沙箱。
- [MobileGym](https://github.com/Purewhiter/mobilegym)、[MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench)、[PhoneHarness](https://github.com/lsdefine/PhoneHarness)、[CopilotKit/OpenMuse](https://github.com/CopilotKit/OpenMuse)、[Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM)、[ClawGUI](https://github.com/ClawGUI/ClawGUI-APP)——Python 线里的手机操作器、轨迹和产品思路。

## 声明

nanoMuse 是独立的社区项目，与 Meta Platforms, Inc. 及其 Muse 产品无关，未获其背书，也不派生自它；Muse 是 Meta Platforms, Inc. 的商标。小龙是本项目自己的。

## 许可

[GPL-3.0-or-later](LICENSE)。Android App 基于 OpenMinis 1.13（GPL-3.0），自 2026-09-24 起修改；见 [NOTICE](NOTICE) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。Python 线更早的版本以 MIT 发布（tag `pre-openminis`）。
