#!/usr/bin/env sh
# Install the nanoMuse app into a MobileGym checkout.
#
#   demo/mobilegym/install.sh /path/to/mobilegym
#
# MobileGym discovers apps by convention (apps/<Dir>/manifest.ts, *App.tsx, state.ts), so
# this only copies the module; nothing in the checkout is edited. Run it again to update.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
target=${1:-}

if [ -z "$target" ]; then
  echo "usage: $0 /path/to/mobilegym" >&2
  exit 2
fi
if [ ! -f "$target/os/createAppStore.ts" ] || [ ! -d "$target/apps" ]; then
  echo "$target does not look like a MobileGym checkout (no os/createAppStore.ts)" >&2
  exit 1
fi

rm -rf "$target/apps/nanoMuse"
cp -R "$here/apps/nanoMuse" "$target/apps/nanoMuse"
echo "installed apps/nanoMuse into $target"
# the module's one dependency beyond MobileGym's own: it renders the phone's screenshot in the
# tab. --no-save leaves the checkout's package.json and lockfile untouched.
if [ -d "$target/node_modules" ] && [ ! -d "$target/node_modules/modern-screenshot" ]; then
  (cd "$target" && npm install --no-save --no-audit --no-fund modern-screenshot@^4.7.0)
fi
echo "next: (cd $target && npm install && npm install --no-save modern-screenshot && npm run dev), then open the nanoMuse app on the phone."
