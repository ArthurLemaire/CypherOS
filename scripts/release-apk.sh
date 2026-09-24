#!/usr/bin/env bash
# Build, sign, name and (optionally) publish a nanoMuse release APK.
#
#   scripts/release-apk.sh <version> [--publish] [--notes FILE] [--allow-debug-key]
#
# 1. checks that android/src/android/app/build.gradle.kts carries versionName <version>
#    (scripts/rebrand.py sets it),
# 2. makes sure the native artifacts and rclone.aar exist (scripts/android/build-natives.sh),
# 3. ./gradlew :app:assembleRelease — signed with android/keystore.properties when present,
# 4. verifies the signature and refuses the debug key unless --allow-debug-key,
# 5. writes dist/nanoMuse-<version>-arm64.apk and .sha256,
# 6. with --publish: gh release create v<version> --prerelease with the APK, the checksum
#    and the notes (default docs/releases/v<version>.md).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/android/env.sh"

version="${1:-}"
[ -n "$version" ] || { echo "usage: $0 <version> [--publish] [--notes FILE] [--allow-debug-key]" >&2; exit 2; }
shift
publish=0 allow_debug=0 notes=""
while [ $# -gt 0 ]; do
  case "$1" in
    --publish) publish=1 ;;
    --allow-debug-key) allow_debug=1 ;;
    --notes) notes="$2"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

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

build_tools="$(ls -d "$ANDROID_HOME"/build-tools/* | sort -V | tail -1)"
echo "== signature"
certs="$("$build_tools/apksigner" verify --print-certs "$apk")"
echo "$certs" | grep -E "Signer #1 certificate (DN|SHA-256)"
if echo "$certs" | grep -q "CN=Android Debug" && [ $allow_debug = 0 ]; then
  echo "signed with the debug key — android/keystore.properties is missing (or pass --allow-debug-key for a local test build)" >&2
  exit 1
fi
"$build_tools/aapt" dump badging "$apk" | grep -E "^package:|application-label:" | head -2

mkdir -p "$NM_ROOT/dist"
out="$NM_ROOT/dist/nanoMuse-$version-arm64.apk"
cp "$apk" "$out"
( cd "$NM_ROOT/dist" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256" && cat "$(basename "$out").sha256" )
ls -la "$out"

if [ $publish = 1 ]; then
  notes="${notes:-$NM_ROOT/docs/releases/v$version.md}"
  [ -f "$notes" ] || { echo "release notes not found: $notes (see docs/release-notes-template.md)" >&2; exit 1; }
  title="$(head -1 "$notes" | sed 's/^# *//')"
  echo "== gh release create v$version --prerelease"
  gh release create "v$version" "$out" "$out.sha256" --prerelease --title "$title" --notes-file "$notes"
fi
