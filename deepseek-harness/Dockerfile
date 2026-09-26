# DeepSeek Harness (dsh) for max2, PBI-2. Version pinned by package-lock.json.
# Runs as an unprivileged user with no host credentials; networking is restricted by the
# compose network (internal) plus host iptables, see README.md.
FROM node:24-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends python3 make g++ ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/dsh
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM node:24-slim
# bubblewrap: dsh's preferred Linux command sandbox; git/python3/procps: tools the agent uses in its workspace.
RUN apt-get update && apt-get install -y --no-install-recommends bubblewrap git python3 procps socat ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home --shell /bin/bash dsh \
 && mkdir -p /data /workspace && chown dsh:dsh /data /workspace
COPY --from=build /opt/dsh /opt/dsh
RUN ln -s /opt/dsh/node_modules/.bin/dsh /usr/local/bin/dsh
COPY entrypoint.sh /usr/local/bin/dsh-entrypoint
USER dsh
ENV DSH_HOME=/data HOME=/home/dsh
WORKDIR /workspace
ENTRYPOINT ["dsh-entrypoint"]
CMD ["web", "--host", "127.0.0.1", "--port", "3080", "--no-open", "--trusted-host", "deepseek.jp-visser.nl"]
