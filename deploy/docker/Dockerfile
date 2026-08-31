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
FROM node:24.20.0-trixie-slim@sha256:50c3b2f6988dfc307b86e5301d69611af31f4789bdf232863b07d3b02fe55ae0 AS node

# -------------------------
# Stage 1a: Frontend bundle (BUILD platform, never emulated)
# -------------------------
# dist is architecture-independent JS/CSS, so this must NOT run under QEMU: on
# 2026-07-29 the arm64 leg of the release build sat at rolldown's "rendering
# chunks..." for 2h55m (its threaded Rust binding deadlocks under qemu-user)
# until the 6h job timeout. Pinned to $BUILDPLATFORM, one bundle serves both
# target arches. `npm ci` keeps optional native bindings strict per the lockfile.
FROM --platform=$BUILDPLATFORM node:24.20.0-trixie-slim@sha256:50c3b2f6988dfc307b86e5301d69611af31f4789bdf232863b07d3b02fe55ae0 AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim@sha256:cae66f2ef0ec51a9891263eeee7f987dacf0a9879e8aa9353d5606e0530619a5 AS builder
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
# Stage 1b: builder + the :full image's Python deps
# -------------------------
# psd-tools (.psd export), Wand (ImageMagick bindings) and the cairosvg pin
# for SVG logo rendering — requirements-cl2k.txt is the one place they're
# pinned. Only the `full` runtime copies this stage's site-packages.
FROM builder AS builder-full
COPY requirements-cl2k.txt .
RUN pip3 install --no-cache-dir -r requirements-cl2k.txt

# -------------------------
# Stage 2: shared runtime base — everything except site-packages
# -------------------------
FROM python:3.14-slim@sha256:cae66f2ef0ec51a9891263eeee7f987dacf0a9879e8aa9353d5606e0530619a5 AS runtime-base

WORKDIR /app

# Install minimal runtime dependencies. jdupes comes from Debian instead
# of being built from codeberg source — sidesteps recurring codeberg
# outages, and libjodycode is pulled in automatically as a dep.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git tzdata jdupes && \
    rm -rf /var/lib/apt/lists/*

# Copy rclone binary (installed to /usr/bin by rclone install script)
COPY --from=builder /usr/bin/rclone /usr/bin/rclone

# Copy built frontend assets
COPY --from=builder --chown=99:100 /app/frontend/dist ./frontend/dist

# .dockerignore only filters the host context, not --from=builder, so drop the
# builder's node_modules. --chown here: a later `chown -R` duplicates /app (45MB).
COPY --from=builder --chown=99:100 /app .
RUN rm -rf /app/frontend/node_modules

# Frontend build output into /app/public (served via STATIC_DIR). This RUN creates
# the files, so it chowns them here — a later layer would duplicate the bytes.
RUN mkdir -p /app/public && \
    cp frontend/dist/index.html /app/public/index.html && \
    cp -r frontend/dist/assets /app/public/assets && \
    if [ -d frontend/dist/icons ]; then cp -r frontend/dist/icons /app/public/icons; fi && \
    if [ -d frontend/dist/img ]; then cp -r frontend/dist/img /app/public/img; fi && \
    if [ -d frontend/dist/posters ]; then cp -r frontend/dist/posters /app/public/posters; fi && \
    chown -R 99:100 /app/public

# uid 99 / gid 100 matches PUID/PGID, so start.sh's stat check skips its sweep.
# -o is required on both: gid 100 is already `users` in the base image.
# Bytecode is baked here and PYTHONDONTWRITEBYTECODE stops runtime .pyc writes,
# so /app never needs to be writable and start.sh can skip chowning it.
RUN python3 -m compileall -q /app/backend /app/main.py

RUN groupadd -o -g 100 dockeruser && \
    useradd -o -u 99 -g 100 dockeruser && \
    chown 99:100 /app && \
    unreadable="$(find /app \( -type f ! -perm -o=r \) -o \( -type d ! -perm -o=x \) | head -20)"; \
    if [ -n "$unreadable" ]; then echo "not world-readable:"; echo "$unreadable"; exit 1; fi

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
ENV PYTHONDONTWRITEBYTECODE=1
# platformdirs-based libraries otherwise write app state to a home dir that is
# not on a volume; keep it in /config alongside everything else.
ENV XDG_CONFIG_HOME=/config/.config
ENV XDG_CACHE_HOME=/config/.cache
ENV XDG_DATA_HOME=/config/.local/share

ENTRYPOINT ["bash", "scripts/start.sh"]

# -------------------------
# Stage 3: :full — the lean runtime plus the CL2K toolchain
# -------------------------
FROM runtime-base AS full

# imagemagick (Wand's libMagickWand), librsvg2-2 (so IM can read SVG clear
# logos), fonts-dejavu-core (guaranteed fallback font), and cabextract to
# unpack the vendored Arial below. No `contrib` component or
# ttf-mscorefonts-installer: that package downloads MS fonts from SourceForge
# at build time, and a flaky mirror failed the whole image build.
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        imagemagick librsvg2-2 fonts-dejavu-core \
        fontconfig cabextract; \
    rm -rf /var/lib/apt/lists/*

# Real Microsoft Arial (regular + bold) for CL2K text rendering, extracted at
# build from the vendored, unmodified arial32.exe (deploy/docker/fonts/) — so
# the build never touches the network for fonts. Renamed to the msttcorefonts
# paths geometry.resolve_font() probes (Arial.ttf / Arial_Bold.ttf).
# Redistributing the original .exe is permitted by its EULA (shipped alongside
# as LICENSE-mscorefonts.txt); the extracted .ttf stays inside the image and is
# never committed to the repo.
COPY deploy/docker/fonts/arial32.exe /tmp/arial32.exe
RUN set -eux; \
    mkdir -p /usr/share/fonts/truetype/msttcorefonts /tmp/arialout; \
    cabextract -L -d /tmp/arialout /tmp/arial32.exe; \
    cp /tmp/arialout/arial.ttf   /usr/share/fonts/truetype/msttcorefonts/Arial.ttf; \
    cp /tmp/arialout/arialbd.ttf /usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf; \
    fc-cache -f; \
    rm -rf /tmp/arial32.exe /tmp/arialout

# Python deps from the full builder — the only place cl2k wheels exist.
COPY --from=builder-full /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder-full /usr/local/bin /usr/local/bin

# Turns every extension's functional hooks on (backend/extensions/__init__.py).
ENV CHUB_IMAGE_FLAVOR=full

# -------------------------
# Stage 4: :latest — lean runtime. LAST so a bare `docker build` builds it.
# -------------------------
FROM runtime-base AS runtime

# Python deps from the lean builder: no cl2k wheels anywhere in this image.
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Extensions' functional hooks off; config/tables stay registered so a config
# written under :full keeps loading and round-tripping here.
ENV CHUB_IMAGE_FLAVOR=lean
