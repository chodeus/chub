# -------------------------
# Stage 1: Builder
# -------------------------
# Node comes from the official image rather than NodeSource's apt repo. That
# repo was a single external dependency in the critical path of every build:
# on 2026-07-27 deb.nodesource.com began returning 403 for the whole domain,
# `curl | gpg --dearmor` was handed an HTML error page, and every build in the
# repo died on "no valid OpenPGP data found" — including PRs that touched
# nothing. The official image needs no third-party apt repo and no GPG key.
#
# The tag tracks the SAME Debian release as the Python base (trixie, glibc
# 2.41) so the copied binaries link against an identical libc; node:24-slim is
# still bookworm/glibc 2.36 and would be a silent mismatch.
FROM node:24.19.0-trixie-slim@sha256:0711b541c1c33a8a530ac4f0d391baa9a15b3d804695b1b24a47daa5fb60e74d AS node

# -------------------------
# Stage 1a: Frontend bundle (BUILD platform, never emulated)
# -------------------------
# dist is architecture-independent JS/CSS, so this must NOT run under QEMU: on
# 2026-07-29 the arm64 leg of the release build sat at rolldown's "rendering
# chunks..." for 2h55m (its threaded Rust binding deadlocks under qemu-user)
# until the 6h job timeout. Pinned to $BUILDPLATFORM, one bundle serves both
# target arches. `npm ci` keeps optional native bindings strict per the lockfile.
FROM --platform=$BUILDPLATFORM node:24.19.0-trixie-slim@sha256:0711b541c1c33a8a530ac4f0d391baa9a15b3d804695b1b24a47daa5fb60e74d AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a AS builder
ARG NODE_MAJOR=24

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules

# Install build dependencies (Node.js 24 arrives above). libcairo2-dev + cairo
# runtime libs are needed at build time for cairosvg, which rasterizes the
# holiday border SVGs to PNGs.
RUN set -eux; \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates gnupg gcc wget curl unzip p7zip-full tzdata jq git build-essential \
        libcairo2-dev pkg-config && \
    ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx && \
    node --version && npm --version && \
    node -e "if (process.versions.node.split('.')[0] !== '${NODE_MAJOR}') process.exit(1)" && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Install rclone: fetch the current release and verify it against the official
# SHA256SUMS, instead of piping an unpinned install script into a root shell.
# Always-latest (like the old install.sh) but with integrity + no remote code.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    ver="$(curl -fsSL https://downloads.rclone.org/version.txt | awk '{print $2}')"; \
    zip="rclone-${ver}-linux-${arch}.zip"; \
    curl -fsSL -o "/tmp/${zip}" "https://downloads.rclone.org/${ver}/${zip}"; \
    curl -fsSL -o /tmp/SHA256SUMS "https://downloads.rclone.org/${ver}/SHA256SUMS"; \
    (cd /tmp && grep "${zip}" SHA256SUMS | sha256sum -c -); \
    unzip -j "/tmp/${zip}" "*/rclone" -d /usr/bin; \
    chmod 0755 /usr/bin/rclone; \
    rclone --version; \
    rm -f "/tmp/${zip}" /tmp/SHA256SUMS

# Copy full app source (including frontend)
COPY . .

# Rasterize holiday border SVGs to PNGs (cairosvg is a build-only dep).
# Runtime reads the PNGs directly, so the final image doesn't need cairo.
RUN pip3 install --no-cache-dir cairosvg && \
    python3 scripts/rasterize_borders.py && \
    pip3 uninstall -y cairosvg

# Frontend assets come from the native-platform `frontend` stage above — dist is
# just JS/CSS, so emulating the bundler for arm64 bought nothing and hung it.
COPY --from=frontend /app/frontend/dist ./frontend/dist

# -------------------------
# Stage 2: Final runtime image
# -------------------------
FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

WORKDIR /app

# Install minimal runtime dependencies. jdupes comes from Debian instead
# of being built from codeberg source — sidesteps recurring codeberg
# outages, and libjodycode is pulled in automatically as a dep.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git tzdata jdupes && \
    rm -rf /var/lib/apt/lists/*

# Copy only Python runtime and site-packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy rclone binary (installed to /usr/bin by rclone install script)
COPY --from=builder /usr/bin/rclone /usr/bin/rclone

# Copy built frontend assets
COPY --from=builder /app/frontend/dist ./frontend/dist

# Copy app source from the builder. .dockerignore only filters the host context,
# not --from=builder, so drop the builder's npm-ci node_modules to stay lean.
COPY --from=builder /app .
RUN rm -rf /app/frontend/node_modules

# Copy frontend build output into /app/public (served via STATIC_DIR env var)
RUN mkdir -p /app/public && \
    cp frontend/dist/index.html /app/public/index.html && \
    cp -r frontend/dist/assets /app/public/assets && \
    if [ -d frontend/dist/icons ]; then cp -r frontend/dist/icons /app/public/icons; fi && \
    if [ -d frontend/dist/img ]; then cp -r frontend/dist/img /app/public/img; fi && \
    if [ -d frontend/dist/posters ]; then cp -r frontend/dist/posters /app/public/posters; fi

# Create user/group for PUID/PGID support via start.sh.
# Also make /app world-readable + traversable so the container can be run
# rootless via `docker run --user uid:gid` with any uid — start.sh's chown
# only runs when started as root (the PUID/PGID path).
RUN groupadd -g 99 dockeruser && \
    useradd -u 100 -g 99 dockeruser && \
    chown -R 100:99 /app && \
    chmod -R a+rX /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=5 \
  CMD curl -f http://localhost:8000/api/health || exit 1

VOLUME /config

# Metadata and labels
LABEL description="CHUB — Chodeus' Media Script Hub" \
      org.opencontainers.image.source="https://github.com/chodeus/chub" \
      org.opencontainers.image.title="chub" \
      org.opencontainers.image.description="CHUB — Chodeus' Media Script Hub. Self-hosted media asset manager for Plex/ARR." \
      org.opencontainers.image.licenses="MIT"

# Branch and build number arguments
ARG BRANCH="master"
ARG BUILD_NUMBER=""
ENV BRANCH=${BRANCH}
ENV BUILD_NUMBER=${BUILD_NUMBER}
ENV CONFIG_DIR=/config
ENV LOG_DIR=/config/logs
ENV STATIC_DIR=/app/public
ENV TZ=America/Los_Angeles
ENV PORT=8000
ENV HOST=0.0.0.0
ENV DOCKER_ENV=true
# Flush stdout/stderr per write so container logs stay chronologically
# ordered — without this, print() block-buffers to the pipe and interleaves
# out of order with the per-record-flushed logging handlers.
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["bash", "scripts/start.sh"]
