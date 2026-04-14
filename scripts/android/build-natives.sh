#!/usr/bin/env bash
# Build everything the Gradle build needs but does not build itself:
#   proot (our fork, submodule android/deps/proot)  -> assets/proot-aarch64 + jniLibs
#   the Alpine root file system                      -> assets/alpine-minirootfs.tar.gz
#   rclone.aar (gomobile, deps/rclone-mobile)        -> app/libs/rclone.aar
# All three are git-ignored build artifacts. Each step is skipped when its
# output exists; pass --force to rebuild.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

force=0
[ "${1:-}" = "--force" ] && force=1
ASSETS="$NM_APP_MAIN/assets"
JNI="$NM_APP_MAIN/jniLibs/arm64-v8a"
LIBS="$NM_GRADLE_DIR/app/libs"

if [ ! -f "$NM_ANDROID/deps/proot/GNUmakefile" ] && [ ! -f "$NM_ANDROID/deps/proot/src/GNUmakefile" ]; then
  echo "== proot submodule"
  (cd "$NM_ROOT" && git submodule update --init android/deps/proot)
fi

if [ $force = 1 ] || [ ! -f "$ASSETS/proot-aarch64" ] || [ ! -f "$JNI/libproot-loader.so" ]; then
  echo "== proot (NDK: ${ANDROID_NDK_HOME:-unset})"
  (cd "$NM_ANDROID" && bash deps/build_proot.sh)
else
  echo "== proot: present"
fi

if [ $force = 1 ] || [ ! -f "$ASSETS/alpine-minirootfs.tar.gz" ]; then
  echo "== alpine root file system"
  # proot-aarch64 already exists, so the script only downloads the rootfs.
  (cd "$NM_ANDROID" && bash scripts/prepare_android_sandbox.sh)
else
  echo "== rootfs: present"
fi

if [ $force = 1 ] || [ ! -f "$LIBS/rclone.aar" ]; then
  echo "== rclone.aar (gomobile)"
  command -v gomobile >/dev/null || go install golang.org/x/mobile/cmd/gomobile@latest
  command -v gobind >/dev/null || go install golang.org/x/mobile/cmd/gobind@latest
  gomobile init
  (cd "$NM_ANDROID" && bash deps/build_rclone_android.sh)
  mkdir -p "$LIBS"
  cp "$NM_ANDROID/deps/build/rclone/rclone.aar" "$LIBS/rclone.aar"
else
  echo "== rclone.aar: present"
fi

ls -la "$ASSETS/proot-aarch64" "$ASSETS/alpine-minirootfs.tar.gz" "$JNI"/*.so "$LIBS/rclone.aar"
