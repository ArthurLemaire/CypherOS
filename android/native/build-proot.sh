#!/usr/bin/env bash
# Builds PRoot for the phone with the Android NDK.
#
# PRoot (GPL-2.0, https://proot-me.github.io) is what lets the app run its Alpine root file
# system without root: a user-mode chroot over ptrace. It is built from the Termux fork,
# which carries the Android fixes (ashmem, link2symlink, the F2FS bug, Android's linker), and
# talloc (LGPL-3.0), which PRoot needs, from samba.org. Both are fetched at pinned versions
# and checked against their SHA-256; nothing of theirs is kept in this repository. The
# binaries are separate programs the app starts with exec — an aggregate, not a derivative —
# and THIRD_PARTY_NOTICES.md names them and where their source is.
#
# The two results go where Android installs an app's native libraries, the one place under
# /data an app may exec from (W^X):
#
#   android/app/src/local/jniLibs/arm64-v8a/libproot.so          the proot binary
#   android/app/src/local/jniLibs/arm64-v8a/libproot-loader.so   its loader, found via PROOT_LOADER
#
# Needs: an NDK (ANDROID_NDK_HOME, ANDROID_NDK_LATEST_HOME or $ANDROID_HOME/ndk/<version>),
# python3 (talloc's waf), make, curl. Run from anywhere:
#
#   android/native/build-proot.sh                 # into android/app/src/local/jniLibs
#   android/native/build-proot.sh /some/dir       # into /some/dir/arm64-v8a
set -euo pipefail

PROOT_VERSION="5.1.107.94"   # the Termux fork's tag
PROOT_SHA256="3fa4c57253463c3d595984d997b407b0b6bdb46d290b2a111959a2efd609e839"
TALLOC_VERSION="2.4.3"
TALLOC_SHA256="dc46c40b9f46bb34dd97fe41f548b0e8b247b77a918576733c528e83abd854dd"
API="26"                     # the app's minSdk

here="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$here/../app/src/local/jniLibs}/arm64-v8a"
work="${PROOT_BUILD_DIR:-${TMPDIR:-/tmp}/nanomuse-proot-build}"
mkdir -p "$out" "$work"

# ---------------------------------------------------------------- the toolchain
ndk="${ANDROID_NDK_HOME:-${ANDROID_NDK_LATEST_HOME:-}}"
if [ -z "$ndk" ] && [ -n "${ANDROID_HOME:-}" ] && [ -d "$ANDROID_HOME/ndk" ]; then
  ndk="$(ls -d "$ANDROID_HOME"/ndk/* | sort -V | tail -1)"
fi
[ -n "$ndk" ] && [ -d "$ndk" ] || { echo "no NDK: set ANDROID_NDK_HOME" >&2; exit 1; }
host="linux-x86_64"; [ "$(uname -s)" = "Darwin" ] && host="darwin-x86_64"
tc="$ndk/toolchains/llvm/prebuilt/$host/bin"
export CC="$tc/aarch64-linux-android${API}-clang"
export AR="$tc/llvm-ar" STRIP="$tc/llvm-strip" OBJCOPY="$tc/llvm-objcopy" OBJDUMP="$tc/llvm-objdump" RANLIB="$tc/llvm-ranlib"
[ -x "$CC" ] || { echo "no compiler at $CC" >&2; exit 1; }
echo "NDK: $ndk"

fetch() { # url sha256 file
  if [ ! -f "$3" ] || ! echo "$2  $3" | sha256sum -c --quiet - 2>/dev/null; then
    curl -fsSL -o "$3" "$1"
    echo "$2  $3" | sha256sum -c --quiet -
  fi
}

# ---------------------------------------------------------------- talloc (static)
talloc_src="$work/talloc-$TALLOC_VERSION"
talloc_prefix="$work/talloc-prefix"
if [ ! -f "$talloc_prefix/lib/libtalloc.a" ]; then
  fetch "https://www.samba.org/ftp/talloc/talloc-$TALLOC_VERSION.tar.gz" "$TALLOC_SHA256" "$work/talloc.tar.gz"
  rm -rf "$talloc_src" && tar -xzf "$work/talloc.tar.gz" -C "$work"
  cd "$talloc_src"
  # waf cannot run test programs for another CPU; these are the answers for Bionic/arm64
  cat > cross-answers.txt <<'EOF'
Checking uname sysname type: "Linux"
Checking uname machine type: "aarch64"
Checking uname release type: "dontcare"
Checking uname version type: "dontcare"
Checking simple C program: OK
building library support: OK
Checking for large file support: OK
Checking for -D_FILE_OFFSET_BITS=64: OK
Checking for WORDS_BIGENDIAN: NO
Checking for C99 vsnprintf: OK
Checking for HAVE_SECURE_MKSTEMP: OK
rpath library support: OK
-Wl,--version-script support: FAIL
Checking correct behavior of strtoll: OK
Checking correct behavior of strptime: OK
Checking for HAVE_IFACE_GETIFADDRS: OK
Checking for HAVE_IFACE_IFCONF: OK
Checking for HAVE_IFACE_IFREQ: OK
Checking getconf LFS_CFLAGS: OK
Checking for large file support without additional flags: OK
Checking for working strptime: OK
Checking for HAVE_SHARED_MMAP: OK
Checking for HAVE_MREMAP: OK
Checking for HAVE_INCOHERENT_MMAP: OK
Checking getconf large file support flags work: OK
EOF
  ./configure --prefix="$talloc_prefix" --disable-python --disable-rpath \
    --cross-compile --cross-answers=cross-answers.txt >"$work/talloc-configure.log" 2>&1 \
    || { tail -30 "$work/talloc-configure.log" >&2; exit 1; }
  make -j"$(nproc)" >"$work/talloc-make.log" 2>&1 || { tail -30 "$work/talloc-make.log" >&2; exit 1; }
  mkdir -p "$talloc_prefix/lib" "$talloc_prefix/include"
  "$AR" rcs "$talloc_prefix/lib/libtalloc.a" bin/default/talloc*.o
  cp talloc.h "$talloc_prefix/include/"
  echo "talloc $TALLOC_VERSION built"
fi

# ---------------------------------------------------------------- proot
proot_src="$work/proot-$PROOT_VERSION"
fetch "https://github.com/termux/proot/archive/v$PROOT_VERSION.zip" "$PROOT_SHA256" "$work/proot.zip"
rm -rf "$proot_src" && (cd "$work" && unzip -q -o proot.zip)
cd "$proot_src/src"
# - PROOT_UNBUNDLE_LOADER: the loader is a file of its own (PROOT_LOADER names it at run
#   time) instead of being written to a temp dir and exec'd, which Android forbids
# - HAS_LOADER_32BIT= : no 32-bit loader; the root file system has no 32-bit programs
# - ARG_MAX: Bionic has no such constant
# - -include string.h: one extension leaves it out, which NDK clang treats as an error; the
#   loader is freestanding and gets no such header, so it is built first, on its own
# (flags go in through the environment: the makefile appends its own to them, which a
# command-line assignment would replace)
common=(PROOT_UNBUNDLE_LOADER="/proc/self/cwd" HAS_LOADER_32BIT= CC="$CC" STRIP="$STRIP" OBJCOPY="$OBJCOPY" OBJDUMP="$OBJDUMP")
CPPFLAGS="-DVERSION=\\\"$PROOT_VERSION\\\"" \
make -j"$(nproc)" loader/loader "${common[@]}" >"$work/proot-make.log" 2>&1 \
  || { tail -40 "$work/proot-make.log" >&2; exit 1; }
# arm64 needs the loader's pokedata_workaround offset compiled in; the makefile derives it
# with gawk's strtonum, which not every awk has, so it is derived here the same way
sym() { "$tc/llvm-readelf" -s loader/loader | awk -v n="$1" '$8 == n { print $2 }' | head -1; }
start=$(( 16#$(sym _start) )); poke=$(( 16#$(sym pokedata_workaround) ))
[ "$start" -gt 0 ] && [ "$poke" -gt 0 ] || { echo "loader symbols not found" >&2; exit 1; }
printf '#include <unistd.h>\nconst ssize_t offset_to_pokedata_workaround=%d;\n' "$((poke - start))" > loader/loader-info.c
CPPFLAGS="-I$talloc_prefix/include -include string.h -DARG_MAX=131072 -DVERSION=\\\"$PROOT_VERSION\\\"" \
LDFLAGS="-L$talloc_prefix/lib" \
make -j"$(nproc)" proot "${common[@]}" >>"$work/proot-make.log" 2>&1 \
  || { tail -40 "$work/proot-make.log" >&2; exit 1; }
"$STRIP" -o "$out/libproot.so" proot
"$STRIP" -o "$out/libproot-loader.so" loader/loader
chmod 755 "$out"/libproot.so "$out"/libproot-loader.so

cat > "$out/../proot-version.json" <<EOF
{"proot": "$PROOT_VERSION", "proot_source": "https://github.com/termux/proot/archive/v$PROOT_VERSION.zip", "talloc": "$TALLOC_VERSION", "api": $API}
EOF
ls -la "$out"
file "$out"/*.so 2>/dev/null || true
echo "proot $PROOT_VERSION built into $out"
