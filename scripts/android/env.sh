#!/usr/bin/env bash
# Toolchain for building android/ (source this). Every variable can be set
# beforehand; the defaults below are only used when the path exists.
#
#   JAVA_HOME          JDK 17 or 21
#   ANDROID_HOME       Android SDK with platforms;android-36, build-tools;35+, cmake;3.22.1
#   ANDROID_NDK_HOME   NDK r27c (27.2.12479018) — also used by deps/build_proot.sh
#   GOROOT / GOPATH    Go 1.25+ with gomobile and gobind on PATH (rclone.aar)

_default() { # var path
  if [ -z "${!1:-}" ] && [ -e "$2" ]; then export "$1"="$2"; fi
}

_default JAVA_HOME "$HOME/.local/toolchains/jdk-21.0.12.1+1"
_default ANDROID_HOME "${ANDROID_SDK_ROOT:-/ssd/software/android-studio/Android/SDK}"
_default ANDROID_NDK_HOME "$HOME/.local/toolchains/android-ndk-r27c"
_default GOROOT "$HOME/.local/toolchains/go"
_default GOPATH "$HOME/go"

export ANDROID_SDK_ROOT="${ANDROID_HOME:-}"
export GOPROXY="${GOPROXY:-https://goproxy.cn,direct}"
export GOFLAGS="${GOFLAGS:--mod=mod}"
export PATH="${JAVA_HOME:+$JAVA_HOME/bin:}${GOROOT:+$GOROOT/bin:}${GOPATH:+$GOPATH/bin:}$PATH"

NM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export NM_ROOT
export NM_ANDROID="$NM_ROOT/android"
export NM_GRADLE_DIR="$NM_ANDROID/src/android"
export NM_APP_MAIN="$NM_GRADLE_DIR/app/src/main"
