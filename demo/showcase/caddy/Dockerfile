# The public face of the showcase: Caddy with the Cloudflare DNS module (for the wildcard
# certificate the per-session hostnames need) and the built MobileGym with the nanoMuse app
# installed and pointed at the gateway.
#
# Build context is the repository root (see docker-compose.yml), so the nanoMuse app module can
# be copied straight from demo/mobilegym/apps/nanoMuse.

FROM node:22-bookworm-slim AS site
ARG MOBILEGYM_REPO=https://github.com/Purewhiter/mobilegym.git
ARG MOBILEGYM_REF=main
ARG NANOMUSE_DEMO=/api/demo
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --depth 1 --branch "${MOBILEGYM_REF}" "${MOBILEGYM_REPO}" mobilegym
COPY demo/mobilegym/apps/nanoMuse mobilegym/apps/nanoMuse
WORKDIR /src/mobilegym
RUN npm ci --no-audit --no-fund \
 && VITE_NANOMUSE_DEMO="${NANOMUSE_DEMO}" npm run build

FROM caddy:2-builder AS caddy-build
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2
COPY --from=caddy-build /usr/bin/caddy /usr/bin/caddy
COPY --from=site /src/mobilegym/dist /srv/site
