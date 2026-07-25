#!/bin/bash
set -e

# ============================================================================
# PRoot Android Build Script (OpenMinis fork)
# ============================================================================
# Cross-compiles a statically-linked libtalloc and the OpenMinis/proot fork
# for Android aarch64 using the Android NDK. Produces a single self-contained
# proot binary with the loader bundled, and installs it into
# `src/android/app/src/main/assets/proot-aarch64`.
#
# Repository: https://github.com/OpenMinis/proot (fork of termux/proot)
#
# Prerequisites:
#   - Android NDK r28+ (default path: ~/Library/Android/sdk/ndk/28.0.12433566,
#     or set $ANDROID_NDK_HOME)
#   - curl, tar, make, awk, sed
#
# Usage:
#   ./build_proot.sh           # incremental build
#   ./build_proot.sh clean     # clean all build artifacts and rebuild
#   ./build_proot.sh distclean # also remove vendored talloc source
#
# Output:
#   src/android/app/src/main/assets/proot-aarch64
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROOT_DIR="$SCRIPT_DIR/proot"
TALLOC_DIR="$SCRIPT_DIR/talloc"
BUILD_DIR="$SCRIPT_DIR/build/proot-android"
ASSETS_DIR="$PROJECT_ROOT/src/android/app/src/main/assets"
OUTPUT_BIN="$ASSETS_DIR/proot-aarch64"
# The APK also ships proot as a native library (extracted to
# app's nativeLibraryDir at install time). Keep both in sync.
JNILIBS_DIR="$PROJECT_ROOT/src/android/app/src/main/jniLibs/arm64-v8a"
JNILIBS_BIN="$JNILIBS_DIR/libproot.so"

# talloc version pinned to a known-good release. Single-file build avoids
# Samba's waf-based build system entirely (we just compile talloc.c).
TALLOC_VERSION="2.4.2"
TALLOC_TARBALL_URL="https://download.samba.org/pub/talloc/talloc-${TALLOC_VERSION}.tar.gz"

# Android target. minSdk=26 in src/android/app/build.gradle.kts.
ANDROID_API=26
ANDROID_ABI="arm64-v8a"
NDK_TRIPLE="aarch64-linux-android"

# ----------------------------------------------------------------------------
# Log helpers
# ----------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[build_proot] $1${NC}"; }
log_success() { echo -e "${GREEN}[build_proot] $1${NC}"; }
log_warn()    { echo -e "${YELLOW}[build_proot] $1${NC}"; }
log_error()   { echo -e "${RED}[build_proot] $1${NC}" >&2; exit 1; }

# ----------------------------------------------------------------------------
# Locate NDK + clang
# ----------------------------------------------------------------------------
resolve_ndk() {
    if [ -n "$ANDROID_NDK_HOME" ] && [ -d "$ANDROID_NDK_HOME" ]; then
        echo "$ANDROID_NDK_HOME"
        return
    fi
    if [ -n "$ANDROID_NDK_ROOT" ] && [ -d "$ANDROID_NDK_ROOT" ]; then
        echo "$ANDROID_NDK_ROOT"
        return
    fi

    # Auto-detect highest available NDK in the SDK folder
    local base="$HOME/Library/Android/sdk/ndk"
    if [ -d "$base" ]; then
        local latest
        latest=$(ls "$base" 2>/dev/null | sort -V | tail -n 1)
        if [ -n "$latest" ]; then
            echo "$base/$latest"
            return
        fi
    fi

    log_error "Android NDK not found. Set \$ANDROID_NDK_HOME or install via Android Studio."
}

setup_toolchain() {
    NDK_HOME="$(resolve_ndk)"
    log_info "Using NDK: $NDK_HOME"

    local host_tag
    case "$(uname -s)-$(uname -m)" in
        Darwin-*)         host_tag="darwin-x86_64" ;;
        Linux-x86_64)     host_tag="linux-x86_64" ;;
        *)                log_error "Unsupported host: $(uname -s) $(uname -m)" ;;
    esac

    TOOLCHAIN_BIN="$NDK_HOME/toolchains/llvm/prebuilt/$host_tag/bin"
    if [ ! -d "$TOOLCHAIN_BIN" ]; then
        log_error "Toolchain dir missing: $TOOLCHAIN_BIN"
    fi

    CC="$TOOLCHAIN_BIN/${NDK_TRIPLE}${ANDROID_API}-clang"
    AR="$TOOLCHAIN_BIN/llvm-ar"
    STRIP="$TOOLCHAIN_BIN/llvm-strip"
    OBJCOPY="$TOOLCHAIN_BIN/llvm-objcopy"
    OBJDUMP="$TOOLCHAIN_BIN/llvm-objdump"
    RANLIB="$TOOLCHAIN_BIN/llvm-ranlib"

    for tool in "$CC" "$AR" "$STRIP" "$OBJCOPY" "$OBJDUMP" "$RANLIB"; do
        if [ ! -x "$tool" ]; then
            log_error "Missing toolchain binary: $tool"
        fi
    done
    log_info "Clang: $CC"
}

# ----------------------------------------------------------------------------
# Stage: fetch talloc source (single-file build)
# ----------------------------------------------------------------------------
fetch_talloc() {
    if [ -f "$TALLOC_DIR/talloc.c" ] && [ -f "$TALLOC_DIR/talloc.h" ]; then
        log_info "talloc source already present, skipping download"
        return
    fi

    log_info "Downloading talloc $TALLOC_VERSION..."
    mkdir -p "$TALLOC_DIR"
    local tarball="$BUILD_DIR/talloc-${TALLOC_VERSION}.tar.gz"
    mkdir -p "$BUILD_DIR"
    if [ ! -f "$tarball" ]; then
        curl -fsSL "$TALLOC_TARBALL_URL" -o "$tarball"
    fi

    local tmp
    tmp=$(mktemp -d)
    tar xzf "$tarball" -C "$tmp"
    cp "$tmp/talloc-${TALLOC_VERSION}/talloc.c" "$TALLOC_DIR/"
    cp "$tmp/talloc-${TALLOC_VERSION}/talloc.h" "$TALLOC_DIR/"
    rm -rf "$tmp"

    # talloc.c expects Samba's `replace.h` — a compat shim that pulls in the
    # standard C + POSIX headers and provides a handful of fallback macros.
    # We ship a minimal standalone version so talloc builds against bionic
    # without needing the rest of Samba. Numbers must match talloc.h constants.
    cat > "$TALLOC_DIR/replace.h" <<'EOF'
#ifndef REPLACE_H
#define REPLACE_H

#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>
#include <stdbool.h>
#include <errno.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/auxv.h>

#define TALLOC_BUILD_VERSION_MAJOR   2
#define TALLOC_BUILD_VERSION_MINOR   4
#define TALLOC_BUILD_VERSION_RELEASE 2

#define HAVE_SYS_AUXV_H 1
#define HAVE_INTPTR_T 1
#define HAVE_VA_COPY 1

/* valgrind hooks are no-ops outside Samba */
#define VALGRIND_MAKE_MEM_UNDEFINED(p, n) do { (void)(p); (void)(n); } while (0)
#define VALGRIND_MAKE_MEM_DEFINED(p, n)   do { (void)(p); (void)(n); } while (0)
#define VALGRIND_MAKE_MEM_NOACCESS(p, n)  do { (void)(p); (void)(n); } while (0)

#ifndef ZERO_STRUCT
#define ZERO_STRUCT(x) memset((char *)&(x), 0, sizeof(x))
#endif

#ifndef discard_const
#define discard_const(ptr) ((void *)((uintptr_t)(ptr)))
#endif

#ifndef MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#endif
#ifndef MAX
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#endif

#define HAVE_CONSTRUCTOR_ATTRIBUTE 1

#endif /* REPLACE_H */
EOF

    log_success "talloc $TALLOC_VERSION unpacked into deps/talloc/"
}

# ----------------------------------------------------------------------------
# Stage: build libtalloc.a (static)
# ----------------------------------------------------------------------------
build_talloc() {
    local out="$BUILD_DIR/libtalloc.a"
    if [ -f "$out" ] && [ "$FORCE_REBUILD" != "1" ]; then
        log_info "libtalloc.a already built, skipping"
        return
    fi

    log_info "Compiling libtalloc.a for android-$ANDROID_API ($ANDROID_ABI)..."
    mkdir -p "$BUILD_DIR/talloc-obj"

    # talloc.c needs a small amount of Samba boilerplate that's gated by
    # HAVE_* defines. We define just enough for a standalone build against
    # bionic: the common Linux/POSIX features minus Samba-specific plumbing.
    local defines=(
        -DHAVE_STDARG_H=1
        -DHAVE_VA_COPY=1
        -DHAVE_UNISTD_H=1
        -DHAVE_INTPTR_T=1
    )

    "$CC" -c "$TALLOC_DIR/talloc.c" \
        -o "$BUILD_DIR/talloc-obj/talloc.o" \
        -I"$TALLOC_DIR" \
        -fPIC -O2 -Wall -std=gnu99 \
        "${defines[@]}"

    "$AR" rcs "$out" "$BUILD_DIR/talloc-obj/talloc.o"
    "$RANLIB" "$out"

    log_success "libtalloc.a built ($(du -h "$out" | awk '{print $1}'))"
}

# ----------------------------------------------------------------------------
# Stage: build proot
# ----------------------------------------------------------------------------
build_proot() {
    if [ ! -d "$PROOT_DIR/src" ]; then
        log_error "PRoot source missing at $PROOT_DIR. Did you clone OpenMinis/proot?"
    fi

    log_info "Building proot (aarch64)..."

    # proot's GNUmakefile has a quirk where `-f <path>` out-of-tree builds
    # double-prefix source paths via $(SRC)$<. Simpler to build in-tree under
    # src/ — object files land next to sources, cleaned by `make clean`.
    # Note: Makefile's default CPPFLAGS adds `-D_FILE_OFFSET_BITS=64
    # -D_GNU_SOURCE -I. -I$(VPATH)` — we must preserve -I. since proot
    # sources use paths like `#include "execve/elf.h"`.
    local cppflags="-D_FILE_OFFSET_BITS=64 -D_GNU_SOURCE -I. -DARG_MAX=131072 -I$TALLOC_DIR"
    local cflags="-O2 -Wall -Wextra -fPIE"
    local ldflags="-Wl,-z,noexecstack -pie -L$BUILD_DIR -ltalloc"

    (
        cd "$PROOT_DIR/src"
        if [ "$FORCE_REBUILD" = "1" ]; then
            make clean >/dev/null 2>&1 || true
        fi

        make \
            CC="$CC" \
            STRIP="$STRIP" \
            OBJCOPY="$OBJCOPY" \
            OBJDUMP="$OBJDUMP" \
            CPPFLAGS="$cppflags" \
            CFLAGS="$cflags" \
            LDFLAGS="$ldflags" \
            -j"$(sysctl -n hw.ncpu 2>/dev/null || nproc)"
    )

    local built="$PROOT_DIR/src/proot"
    if [ ! -f "$built" ]; then
        log_error "Build finished but $built is missing"
    fi

    "$STRIP" "$built"

    # Sanity-check: ELF aarch64 shared-object (PIE)
    if ! "$OBJDUMP" -a "$built" | grep -q 'aarch64'; then
        log_error "Output is not aarch64 ELF"
    fi

    log_success "proot built: $built ($(du -h "$built" | awk '{print $1}'))"
    BUILT_PROOT="$built"
}

# ----------------------------------------------------------------------------
# Stage: install into Android assets
# ----------------------------------------------------------------------------
install_asset() {
    if [ ! -f "$BUILT_PROOT" ]; then
        log_error "No proot binary to install"
    fi
    mkdir -p "$ASSETS_DIR"

    # No .bak of the previous binary: anything left in assets/ is packaged
    # into the APK, so a backup silently added ~260K of dead weight to every
    # build. The binary is reproducible from source — rerun this script.
    rm -f "$OUTPUT_BIN.bak"

    install -m 0755 "$BUILT_PROOT" "$OUTPUT_BIN"
    log_success "Installed: $OUTPUT_BIN ($(du -h "$OUTPUT_BIN" | awk '{print $1}'))"

    mkdir -p "$JNILIBS_DIR"
    install -m 0755 "$BUILT_PROOT" "$JNILIBS_BIN"
    log_success "Installed: $JNILIBS_BIN ($(du -h "$JNILIBS_BIN" | awk '{print $1}'))"
}

# ----------------------------------------------------------------------------
# Entry points
# ----------------------------------------------------------------------------
do_clean() {
    log_info "Cleaning build artifacts..."
    rm -rf "$BUILD_DIR"
    if [ -d "$PROOT_DIR/src" ]; then
        (cd "$PROOT_DIR/src" && make clean >/dev/null 2>&1 || true)
    fi
    log_success "Clean complete"
}

do_distclean() {
    do_clean
    rm -rf "$TALLOC_DIR"
    log_success "Distclean complete"
}

main() {
    case "${1:-}" in
        clean)     do_clean; FORCE_REBUILD=1 ;;
        distclean) do_distclean; FORCE_REBUILD=1 ;;
        "")        FORCE_REBUILD=0 ;;
        *)         log_error "Unknown argument: $1 (expected: clean|distclean)" ;;
    esac

    setup_toolchain
    fetch_talloc
    build_talloc
    build_proot
    install_asset

    log_success "All done. proot binary ready at $OUTPUT_BIN"
}

main "$@"
