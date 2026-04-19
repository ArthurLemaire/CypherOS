#!/usr/bin/env bash
set -euo pipefail
export GOROOT=$HOME/.local/toolchains/go GOPATH=$HOME/go
export PATH=$HOME/.local/toolchains/go/bin:$HOME/go/bin:$PATH
export GOPROXY=https://goproxy.cn,direct GOFLAGS=-mod=mod
export ANDROID_NDK_HOME=$HOME/.local/toolchains/android-ndk-r27c
export ANDROID_HOME=/ssd/software/android-studio/Android/SDK
export JAVA_HOME=$HOME/.local/toolchains/jdk-21.0.12.1+1
export PATH=$JAVA_HOME/bin:$PATH
cd /tmp/openminis/repo
echo "== gomobile init"; time gomobile init
echo "== go mod download (rclone-mobile)"; (cd deps/rclone-mobile && time go mod download)
echo "== gomobile bind"; time bash deps/build_rclone_android.sh
ls -la deps/build/rclone/rclone.aar && echo RCLONE_AAR_DONE
