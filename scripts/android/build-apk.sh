#!/usr/bin/env bash
set -uo pipefail
export JAVA_HOME=$HOME/.local/toolchains/jdk-21.0.12.1+1
export PATH=$JAVA_HOME/bin:$PATH
export ANDROID_HOME=/ssd/software/android-studio/Android/SDK
export ANDROID_SDK_ROOT=$ANDROID_HOME
unset ANDROID_NDK_HOME ANDROID_NDK_ROOT
cd /tmp/openminis/repo/src/android
echo "== start $(date)"
time ./gradlew :app:assembleRelease --console=plain --stacktrace "$@"
rc=$?
echo "== end $(date) rc=$rc"
ls -la app/build/outputs/apk/release/ 2>/dev/null
echo "GRADLE_EXIT=$rc"
