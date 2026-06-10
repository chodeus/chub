# -------------------------
# Stage 1: Builder
# -------------------------
FROM python:3.13-slim@sha256:b04b5d7233d2ad9c379e22ea8927cd1378cd15c60d4ef876c065b25ea8fb3bf3 AS builder
ARG NODE_MAJOR=24

# Install build dependencies (including Node.js 24 and build tools).
# libcairo2-dev + cairo runtime libs are needed at build time for
# cairosvg, which rasterizes the holiday border SVGs to PNGs.
RUN set -eux; \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates gnupg gcc wget curl unzip p7zip-full tzdata jq git build-essential \
        libcairo2-dev pkg-config && \
    install -d -m 0755 /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    node --version && npm --version && \
    node -e "if (process.versions.node.split('.')[0] !== '${NODE_MAJOR}') process.exit(1)" && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Install rclone (jdupes is installed via apt in the runtime stage).
RUN curl https://rclone.org/install.sh | bash

# Copy full app source (including frontend)
COPY . .

# Rasterize holiday border SVGs to PNGs (cairosvg is a build-only dep).
# Runtime reads the PNGs directly, so the final image doesn't need cairo.
RUN pip3 install --no-cache-dir cairosvg && \
    python3 scripts/rasterize_borders.py && \
    pip3 uninstall -y cairosvg

# Build frontend assets.
# Use `npm ci` so platform-specific optional native bindings
# (e.g. @rolldown/binding-linux-arm64-gnu) are resolved strictly from the
# lockfile per buildx target arch — avoids npm/cli#4828 drift with npm install.
RUN cd frontend && npm ci && npm run build

# -------------------------
# Stage 2: Final runtime image
# -------------------------
FROM python:3.13-slim@sha256:b04b5d7233d2ad9c379e22ea8927cd1378cd15c60d4ef876c065b25ea8fb3bf3

WORKDIR /app

# Install minimal runtime dependencies. jdupes comes from Debian instead
# of being built from codeberg source — sidesteps recurring codeberg
# outages, and libjodycode is pulled in automatically as a dep.
#
# CL2K maker adds: imagemagick (Wand's libMagickWand), librsvg2-2 (so IM can
# read SVG clear logos), fonts-dejavu-core (guaranteed fallback font), and
# cabextract to unpack the vendored Arial below. No `contrib` component or
# ttf-mscorefonts-installer here: that package downloads MS fonts from
# SourceForge at build time, and a flaky mirror failed the whole image build.
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        curl git tzdata jdupes \
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

# Copy only Python runtime and site-packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy rclone binary (installed to /usr/bin by rclone install script)
COPY --from=builder /usr/bin/rclone /usr/bin/rclone

# Copy built frontend assets
COPY --from=builder /app/frontend/dist ./frontend/dist

# Copy app source files excluding node_modules etc (already filtered by .dockerignore)
COPY --from=builder /app .

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
