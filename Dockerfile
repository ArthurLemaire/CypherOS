# nanoMuse in a container: the agent sees only /data and /workspace.
#
#   docker build -t nanomuse .
#   docker run -d -p 8787:8787 --env-file .env -v nanomuse-data:/data -v $PWD/workspace:/workspace nanomuse
#   docker run -it --rm --env-file .env -v nanomuse-data:/data -v $PWD/workspace:/workspace nanomuse chat
#
# With a browser (Chromium + Playwright, ~400 MB more; the browser tool is on):
#   docker build --build-arg WITH_BROWSER=1 -t nanomuse:browser .
#
FROM python:3.12-slim

# Override for a regional PyPI mirror, e.g.
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .
ARG PIP_INDEX_URL=https://pypi.org/simple
# 1 = bundle Chromium for the browser tool
ARG WITH_BROWSER=0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    NANOMUSE_DATA_DIR=/data \
    NANOMUSE_WORKSPACE=/workspace \
    NANOMUSE_CONFIG=/app/config/config.toml \
    NANOMUSE_IN_CONTAINER=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN useradd --create-home --uid 1000 muse \
 && mkdir -p /data /workspace /app/config \
 && chown -R muse:muse /data /workspace /app

WORKDIR /app
COPY --chown=muse:muse pyproject.toml README.md README_zh.md LICENSE ./
COPY --chown=muse:muse nanomuse ./nanomuse
COPY --chown=muse:muse config/config.example.toml ./config/config.example.toml

RUN if [ "$WITH_BROWSER" = "1" ]; then \
      pip install --no-cache-dir ".[browser]" \
      && playwright install --with-deps chromium \
      && chmod -R a+rX /ms-playwright \
      && rm -rf /var/lib/apt/lists/*; \
    else \
      pip install --no-cache-dir .; \
    fi \
 && ln -s /workspace /app/workspace \
 && cp config/config.example.toml config/config.toml

# the browser tool is on in the browser image ("1"); anything else leaves config.toml alone
ENV NANOMUSE_BROWSER_ENABLED=${WITH_BROWSER}

USER muse
VOLUME ["/data", "/workspace"]
EXPOSE 8787

ENTRYPOINT ["nanomuse"]
# The phone app. Override with `chat`, `run "..."`, `daemon`, ...
CMD ["serve", "--host", "0.0.0.0", "--no-qr"]
