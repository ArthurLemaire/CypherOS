#!/usr/bin/env sh
# Build the phone for local development of the showcase: MobileGym with the nanoMuse app
# installed and pointed at the gateway. Production builds the same thing inside
# caddy/Dockerfile; this is for running the gateway on your machine with SITE_DIR.
#
#   demo/showcase/site/build.sh [/path/to/mobilegym]     # default: ./site/mobilegym (cloned)
#   SITE_DIR=$PWD/demo/showcase/site/dist python -m showcase_gateway
set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
checkout=${1:-$here/mobilegym}
gateway=${NANOMUSE_DEMO:-/api/demo}

if [ ! -d "$checkout" ]; then
  git clone --depth 1 "${MOBILEGYM_REPO:-https://github.com/Purewhiter/mobilegym.git}" "$checkout"
fi
cd "$checkout"
[ -d node_modules ] || npm ci --no-audit --no-fund
"$root/demo/mobilegym/install.sh" "$checkout"
VITE_NANOMUSE_DEMO="$gateway" npm run build
rm -rf "$here/dist"
cp -R dist "$here/dist"
echo "site built: $here/dist (gateway at $gateway)"
