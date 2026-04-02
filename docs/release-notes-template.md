# nanoMuse <version> · <Codename>

<!-- The first line is the GitHub release title (scripts/release-apk.sh reads it).
     English first; the Chinese version of the same notes goes in the <details> block at the end.
     Codenames so far: Foundation, Identity, Home, Guardrails, Memory, Avatar, Welcome, Polish, Portrait, Motion. One word, capitalised. -->

<One paragraph: what this version adds, in plain words.>

## Added

- …

## Changed

- versionCode <n>; installs over <previous> without losing data.

## Kept, on purpose

- …

## Known issues

- arm64 only; for an x86 emulator, build a test APK yourself with `-Pnm.abi=x86_64`.

## Install

Download `nanoMuse-<version>-arm64.apk` (Android 8.0 or newer, arm64) and install it over the previous version — same signing key, your data is kept. Verify: `sha256sum -c nanoMuse-<version>-arm64.apk.sha256`.

## Source

Based on [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13 (GPL-3.0), modified since 2026-09-24. The complete corresponding source of this build is tag `v<version>` plus the `android/deps/proot` submodule ([nano-muse/proot](https://github.com/nano-muse/proot)). The whole repository is GPL-3.0-or-later. nanoMuse is not affiliated with Meta; Muse is a trademark of Meta Platforms, Inc.

<details>
<summary>简体中文</summary>

<一段话：这个版本加了什么。>

### 新增

- …

### 变更

- versionCode <n>；覆盖安装 <previous> 不丢数据。

### 有意保留

- …

### 已知问题

- 只有 arm64 包；x86 模拟器请自行用 `-Pnm.abi=x86_64` 打测试包。

### 安装

下载 `nanoMuse-<version>-arm64.apk`（Android 8.0+，arm64），覆盖安装，同一把签名，数据保留；校验：`sha256sum -c nanoMuse-<version>-arm64.apk.sha256`。

### 来源

基于 [OpenMinis](https://github.com/OpenMinis/OpenMinis) 1.13（GPL-3.0），自 2026-09-24 起修改；本版本的完整对应源码是 tag `v<version>` 加子模块 `android/deps/proot`（[nano-muse/proot](https://github.com/nano-muse/proot)）。整个仓库以 GPL-3.0-or-later 发布。nanoMuse 与 Meta 无关，Muse 是 Meta Platforms, Inc. 的商标。

</details>
