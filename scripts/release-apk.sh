#!/usr/bin/env bash
# Build, sign, name and (optionally) publish a nanoMuse release APK.
#
#   scripts/release-apk.sh <version> [--publish] [--publish-only] [--target COMMIT]
#                          [--notes FILE] [--allow-debug-key] [--prerelease]
#
# 1. checks that android/src/android/app/build.gradle.kts carries versionName <version>
#    (scripts/rebrand.py sets it),
# 2. makes sure the native artifacts and rclone.aar exist (scripts/android/build-natives.sh),
# 3. ./gradlew :app:assembleRelease — signed with android/keystore.properties when present,
# 4. verifies the signature and refuses the debug key unless --allow-debug-key,
# 5. writes dist/nanoMuse-<version>-arm64.apk and .sha256,
# 6. with --publish: tags v<version> (annotated, at --target or HEAD, unless the tag already
#    exists), pushes the tag, then gh release create v<version> --latest with the APK, the
#    checksum and the notes (default docs/releases/v<version>.md); --prerelease marks it as
#    one instead and leaves Latest alone.
#
# --publish-only skips 1-5 and publishes the dist/ APK that is already there — for a version
# whose sources are an older commit (pass --target <commit> so the tag lands on it). The APK
# is still checked: its badging must say <version>, the .sha256 must match, debug key refused.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/android/env.sh"

version="${1:-}"
[ -n "$version" ] || { echo "usage: $0 <version> [--publish] [--publish-only] [--target COMMIT] [--notes FILE] [--allow-debug-key] [--prerelease]" >&2; exit 2; }
shift
publish=0 publish_only=0 allow_debug=0 prerelease=0 notes="" target=""
while [ $# -gt 0 ]; do
  case "$1" in
    --publish) publish=1 ;;
    --publish-only) publish=1; publish_only=1 ;;
    --target) target="$2"; shift ;;
    --allow-debug-key) allow_debug=1 ;;
    --prerelease) prerelease=1 ;;
    --notes) notes="$2"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

build_tools="$(ls -d "$ANDROID_HOME"/build-tools/* | sort -V | tail -1)"
out="$NM_ROOT/dist/nanoMuse-$version-arm64.apk"

# Signature + badging of one APK; exits on the debug key unless allowed.
inspect_apk() {
  local apk="$1"
  echo "== signature"
  local certs
  certs="$("$build_tools/apksigner" verify --print-certs "$apk")"
  echo "$certs" | grep -E "Signer #1 certificate (DN|SHA-256)"
  if echo "$certs" | grep -q "CN=Android Debug" && [ $allow_debug = 0 ]; then
    echo "signed with the debug key — android/keystore.properties is missing (or pass --allow-debug-key for a local test build)" >&2
    exit 1
  fi
  "$build_tools/aapt" dump badging "$apk" | grep -E "^package:|application-label:" | head -2
}

if [ $publish_only = 0 ]; then
  gradle_file="$NM_GRADLE_DIR/app/build.gradle.kts"
  grep -q "versionName = \"$version\"" "$gradle_file" || {
    echo "build.gradle.kts does not carry versionName \"$version\" — set VERSION_NAME in scripts/rebrand.py and run it" >&2
    exit 1
  }

  bash "$NM_ROOT/scripts/android/build-natives.sh"

  echo "== assembleRelease"
  ( cd "$NM_GRADLE_DIR" && ./gradlew :app:assembleRelease --console=plain -q )
  apk="$NM_GRADLE_DIR/app/build/outputs/apk/release/app-release.apk"
  [ -f "$apk" ] || { echo "no APK at $apk" >&2; exit 1; }
  inspect_apk "$apk"

  mkdir -p "$NM_ROOT/dist"
  cp "$apk" "$out"
  ( cd "$NM_ROOT/dist" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256" && cat "$(basename "$out").sha256" )
  ls -la "$out"
else
  [ -f "$out" ] && [ -f "$out.sha256" ] || { echo "publish-only needs $out and its .sha256 — build first" >&2; exit 1; }
  echo "== dist/$(basename "$out")"
  ( cd "$NM_ROOT/dist" && sha256sum -c "$(basename "$out").sha256" )
  badging="$("$build_tools/aapt" dump badging "$out")"   # a variable, not a pipe: grep -q + pipefail would SIGPIPE aapt
  echo "$badging" | grep -q "versionName='$version'" || {
    echo "$out is not versionName $version:" >&2
    echo "$badging" | grep -E "^package:" >&2
    exit 1
  }
  inspect_apk "$out"
  ls -la "$out"
fi

if [ $publish = 1 ]; then
  notes="${notes:-$NM_ROOT/docs/releases/v$version.md}"
  [ -f "$notes" ] || { echo "release notes not found: $notes (see docs/release-notes-template.md)" >&2; exit 1; }
  title="$(head -1 "$notes" | sed 's/^# *//')"
  tag="v$version"

  cd "$NM_ROOT"
  if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    echo "== tag $tag exists at $(git rev-parse --short "$tag^{commit}")"
    [ -z "$target" ] || [ "$(git rev-parse "$tag^{commit}")" = "$(git rev-parse "$target^{commit}")" ] || {
      echo "tag $tag already points elsewhere than --target $target" >&2; exit 1; }
  else
    target="${target:-HEAD}"
    echo "== tag $tag -> $(git rev-parse --short "$target^{commit}")"
    git tag -a "$tag" "$target" -m "nanoMuse $version"
  fi
  git push origin "refs/tags/$tag"

  if gh release view "$tag" >/dev/null 2>&1; then
    echo "release $tag already exists on GitHub — nothing published" >&2
    exit 1
  fi
  if [ "$prerelease" = 1 ]; then kind="--prerelease"; else kind="--latest"; fi
  echo "== gh release create $tag $kind"
  gh release create "$tag" "$out" "$out.sha256" --verify-tag $kind --title "$title" --notes-file "$notes"
fi
