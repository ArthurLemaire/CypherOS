# OpenMuse in a container: the agent sees only /data and /workspace.
#
#   docker build -t openmuse .
#   docker run -d -p 8787:8787 --env-file .env -v openmuse-data:/data -v $PWD/workspace:/workspace openmuse
#   docker run -it --rm --env-file .env -v openmuse-data:/data -v $PWD/workspace:/workspace openmuse chat
#
FROM python:3.12-slim

# Override for a regional PyPI mirror, e.g.
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    OPENMUSE_DATA_DIR=/data \
    OPENMUSE_WORKSPACE=/workspace \
    OPENMUSE_CONFIG=/app/config/config.toml

RUN useradd --create-home --uid 1000 muse \
 && mkdir -p /data /workspace /app/config \
 && chown -R muse:muse /data /workspace /app

WORKDIR /app
COPY --chown=muse:muse pyproject.toml README.md README_zh.md LICENSE ./
COPY --chown=muse:muse openmuse ./openmuse
COPY --chown=muse:muse config/config.example.toml ./config/config.example.toml

RUN pip install --no-cache-dir . \
 && ln -s /workspace /app/workspace \
 && cp config/config.example.toml config/config.toml

USER muse
VOLUME ["/data", "/workspace"]
EXPOSE 8787

ENTRYPOINT ["openmuse"]
# The phone app. Override with `chat`, `run "..."`, `daemon`, ...
CMD ["serve", "--host", "0.0.0.0", "--no-qr"]
