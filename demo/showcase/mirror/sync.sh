#!/bin/sh
# Keeps the project site's mirror current. Fetches nano-muse/nano-muse.github.io (the site
# behind https://nano-muse.github.io) into a shallow checkout and, when the tip moved, exports
# the tree — no dotfiles, no README — into the directory Caddy serves (mirror/nanomuse.cn.caddy).
# The systemd timer runs it every minute; a run with nothing new is one small request to GitHub
# and no output. Idempotent: the first run clones, later runs fetch.
#
#   WWW_ROOT   where sites live; the default is the showcase's www/ (docker-compose.yml mounts
#              the same directory at /srv/www)
#   MIRROR_*   the repository, its branch and the site's name, for a different site or fork
set -eu

repo=${MIRROR_REPO:-https://github.com/nano-muse/nano-muse.github.io.git}
branch=${MIRROR_BRANCH:-main}
name=${MIRROR_NAME:-nanomuse.cn}
root=${WWW_ROOT:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)/www}
src=$root/.src/$name
dst=$root/$name

fresh=
if [ ! -d "$src/.git" ]; then
	mkdir -p "$root/.src"
	git clone -q --depth 1 --single-branch --branch "$branch" "$repo" "$src"
	fresh=1
fi

cd "$src"
before=$(git rev-parse HEAD)
git fetch -q --depth 1 origin "$branch"
git reset -q --hard FETCH_HEAD
after=$(git rev-parse HEAD)

if [ -n "$fresh" ] || [ "$before" != "$after" ] || [ ! -f "$dst/index.html" ]; then
	mkdir -p "$dst"
	# --delay-updates stages every changed file first and renames them at the end, so a visitor
	# in the middle of an update sees the old site or the new one, not a mixture
	rsync -a --delete --delay-updates --exclude='.*' --exclude=README.md "$src/" "$dst/"
	echo "$name: $(git log -1 --format='%h %s') -> $dst"
fi
