#!/usr/bin/env bash
# Builds the phone's root file system (scripts/rootfs/Dockerfile) for arm64 and writes:
#
#   dist/rootfs/nanomuse-rootfs-<version>-aarch64.tar.xz   what the app unpacks
#   dist/rootfs/nanomuse-rootfs-<version>-aarch64.json     version, sizes, sha256, what is inside
#   dist/rootfs/SHA256SUMS
#
# and, unless --no-install, copies them to android/app/src/local/assets/rootfs.tar.xz and
# rootfs.json, where the `local` flavour of the APK picks them up.
#
#   scripts/rootfs/build.sh                       # arm64 (needs QEMU: docker run --privileged tonistiigi/binfmt --install arm64)
#   scripts/rootfs/build.sh --platform linux/amd64 --no-install   # the same image for the build machine, to try it
#   NODE=0 scripts/rootfs/build.sh                # without Node.js
#
# Env: NODE (1), ALPINE (3.21), PIP_INDEX_URL, APK_MIRROR (a mirror for the build only),
# ROOTFS_MAX_MB (the size gate on the compressed file, 80).
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"

platform="linux/arm64"; install=1
while [ $# -gt 0 ]; do
  case "$1" in
    --platform) platform="$2"; shift 2 ;;
    --no-install) install=0; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
arch="aarch64"; case "$platform" in *amd64*|*x86_64*) arch="x86_64" ;; esac
version="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
node="${NODE:-1}"
stamp="$(git -C "$root" rev-parse --short=8 HEAD 2>/dev/null || echo local)"
rootfs_version="${version}+${stamp}"
out="$root/dist/rootfs"; mkdir -p "$out"
name="nanomuse-rootfs-${version}-${arch}"
tar="$out/$name.tar"

echo "building $name ($platform, node=$node) …"
docker buildx build --platform "$platform" -f scripts/rootfs/Dockerfile \
  --build-arg NODE="$node" --build-arg ALPINE="${ALPINE:-3.21}" \
  --build-arg ROOTFS_VERSION="$rootfs_version" \
  ${PIP_INDEX_URL:+--build-arg PIP_INDEX_URL="$PIP_INDEX_URL"} \
  ${APK_MIRROR:+--build-arg APK_MIRROR="$APK_MIRROR"} \
  --output "type=tar,dest=$tar" .

# Buildx's tar carries the image as one file system; drop what the app never needs
# (Docker's own /etc/hostname etc. are absent already), then compress. xz -7: a 16 MB
# dictionary decodes on a phone with little memory and loses ~1 % to -9.
uncompressed=$(stat -c %s "$tar")
# what is inside, from the image's own stamp (scripts/rootfs/Dockerfile writes it last)
inside="$(tar -xOf "$tar" etc/nanomuse-rootfs 2>/dev/null || true)"
rm -f "$tar.xz"
xz -T0 -7 --keep -c "$tar" > "$tar.xz"
rm -f "$tar"
compressed=$(stat -c %s "$tar.xz")
sha=$(sha256sum "$tar.xz" | cut -d' ' -f1)
mb=$(( compressed / 1048576 ))
echo "rootfs: $(( uncompressed / 1048576 )) MB unpacked, $mb MB compressed, sha256 $sha"

python_v="$(printf '%s\n' "$inside" | sed -n 's/^python=//p')"
node_v="$(printf '%s\n' "$inside" | sed -n 's/^node=//p')"
alpine_v="$(printf '%s\n' "$inside" | sed -n 's/^alpine=//p')"

cat > "$out/$name.json" <<EOF
{
  "name": "$name.tar.xz",
  "version": "$rootfs_version",
  "nanomuse": "$version",
  "arch": "$arch",
  "alpine": "${alpine_v:-unknown}",
  "python": "${python_v:-unknown}",
  "node": "${node_v:-none}",
  "size": $compressed,
  "unpacked": $uncompressed,
  "sha256": "$sha",
  "built": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
(cd "$out" && sha256sum "$name.tar.xz" "$name.json" > SHA256SUMS)
cat "$out/$name.json"

max="${ROOTFS_MAX_MB:-80}"
if [ "$mb" -gt "$max" ]; then
  echo "rootfs is $mb MB compressed, over the $max MB budget" >&2
  exit 1
fi

if [ "$install" = 1 ] && [ "$arch" = "aarch64" ]; then
  assets="$root/android/app/src/local/assets"
  mkdir -p "$assets"
  cp "$tar.xz" "$assets/rootfs.tar.xz"
  cp "$out/$name.json" "$assets/rootfs.json"
  echo "installed into $assets"
fi
