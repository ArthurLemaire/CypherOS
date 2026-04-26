# syntax=docker/dockerfile:1
# The phone's Linux: the root file system the Android app unpacks and runs nanoMuse in.
#
# Alpine (musl, small) for arm64, with python3, the nanomuse wheel and its dependencies in
# /opt/nanomuse, Node.js + npm for the skills that are Node programs (lark-cli, tmeet,
# 12306-mcp), git/curl/ssh for the shell tool, and tzdata. Built by scripts/rootfs/build.sh
# (docker buildx, QEMU for arm64), exported as a tar and compressed with xz.
#
# The wheel is built once on the build machine's own architecture (first stage); only the
# install runs under emulation.
ARG ALPINE=3.21
ARG NODE=1

FROM --platform=$BUILDPLATFORM python:3.12-alpine AS wheel
WORKDIR /src
COPY pyproject.toml README.md README_zh.md LICENSE ./
COPY config/config.example.toml ./config/config.example.toml
COPY nanomuse ./nanomuse
RUN pip install --no-cache-dir --quiet build && python -m build --wheel --outdir /wheels

FROM alpine:${ALPINE} AS rootfs
ARG NODE
ARG PIP_INDEX_URL=https://pypi.org/simple
# a mirror for `apk add` inside the build (the phone gets the standard one plus the switcher)
ARG APK_MIRROR=
RUN if [ -n "$APK_MIRROR" ]; then sed -i "s|https://dl-cdn.alpinelinux.org|$APK_MIRROR|" /etc/apk/repositories; fi \
 && apk add --no-cache \
      python3 py3-pip \
      bash coreutils curl git openssh-client ca-certificates tzdata \
      libstdc++ libgcc libffi openssl \
      jq \
 && if [ "$NODE" = "1" ]; then apk add --no-cache nodejs npm; fi \
 && if [ -n "$APK_MIRROR" ]; then sed -i "s|$APK_MIRROR|https://dl-cdn.alpinelinux.org|" /etc/apk/repositories; fi

COPY --from=wheel /wheels /tmp/wheels
# nanomuse in its own venv, so `pip install` from a task never touches it. There is no
# compiler in here: a dependency that needs one and has no musl/arm64 wheel fails the build,
# which is the point; pure-Python sdists (http-ece) build fine.
RUN python3 -m venv /opt/nanomuse \
 && /opt/nanomuse/bin/pip install --no-cache-dir --index-url "$PIP_INDEX_URL" \
      --prefer-binary /tmp/wheels/nanomuse-*.whl \
 && rm -rf /tmp/wheels \
 # the venv's own pip is not needed once nanomuse is in; the system python keeps its pip
 && rm -rf /opt/nanomuse/lib/python3*/site-packages/pip* /opt/nanomuse/lib/python3*/site-packages/setuptools* /opt/nanomuse/bin/pip* \
 && /opt/nanomuse/bin/python -m compileall -q -o 0 /opt/nanomuse/lib >/dev/null \
 && ln -s /opt/nanomuse/bin/nanomuse /opt/nanomuse/bin/nanomuse-device /opt/nanomuse/bin/nanomuse-browser /opt/nanomuse/bin/nanomuse-open /usr/local/bin/

COPY scripts/rootfs/inside/ /
# trim: tests, tk, idle, ensurepip's wheels, pip's cache, docs, locales
RUN chmod 755 /usr/local/bin/nanomuse-serve /usr/local/bin/nanomuse-mirror \
 && mkdir -p /root/workspace /root/.nanomuse /tmp && chmod 1777 /tmp \
 && rm -rf /usr/lib/python3*/test /usr/lib/python3*/idlelib /usr/lib/python3*/tkinter \
           /usr/lib/python3*/ensurepip /usr/lib/python3*/lib2to3 \
           /opt/nanomuse/lib/python3*/site-packages/pip/_vendor/*/tests \
           /root/.cache /var/cache/apk/* /usr/share/man /usr/share/doc /usr/share/info \
           /usr/share/locale /usr/share/misc /usr/lib/node_modules/npm/docs /usr/lib/node_modules/npm/man \
           /usr/lib/node_modules/npm/node_modules/*/docs /usr/lib/node_modules/npm/node_modules/*/*.md \
 && find / -xdev \( -path '*/site-packages/*/tests' -o -path '*/site-packages/*/test' \) -type d -prune -exec rm -rf {} + 2>/dev/null || true

# what the app reads to know what it unpacked
ARG ROOTFS_VERSION=dev
RUN printf 'version=%s\npython=%s\nnode=%s\nalpine=%s\n' \
      "$ROOTFS_VERSION" "$(python3 -c 'import platform;print(platform.python_version())')" \
      "$(command -v node >/dev/null && node --version || echo none)" "$(cat /etc/alpine-release)" \
      > /etc/nanomuse-rootfs
