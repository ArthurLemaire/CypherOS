#!/usr/bin/env sh
# Install the OpenMuse app into a MobileGym checkout.
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

rm -rf "$target/apps/OpenMuse"
cp -R "$here/apps/OpenMuse" "$target/apps/OpenMuse"
echo "installed apps/OpenMuse into $target"
echo "next: (cd $target && npm install && npm run dev), then open the OpenMuse app on the phone."
