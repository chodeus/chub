# -------------------------
# Stage 1: Builder
# -------------------------
FROM python:3.13-slim AS builder

# Install build dependencies (including Node.js and build tools)
RUN set -eux; \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc wget curl unzip p7zip-full tzdata jq git build-essential nodejs npm && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Install additional binaries/tools (rclone, jdupes)
RUN set -eux; \
    curl https://rclone.org/install.sh | bash && \
    git clone https://codeberg.org/jbruchon/libjodycode.git /tmp/libjodycode && \
    make -C /tmp/libjodycode && make -C /tmp/libjodycode install && \
    ldconfig && \
    git clone https://codeberg.org/jbruchon/jdupes.git /tmp/jdupes && \
    make -C /tmp/jdupes && make -C /tmp/jdupes install && \
    ln -s /usr/local/bin/jdupes /usr/bin/jdupes && \
    rm -rf /tmp/libjodycode /tmp/jdupes

# Copy full app source (including frontend)
COPY . .

# Build frontend assets
RUN cd frontend && npm install && npm run build

# -------------------------
# Stage 2: Final runtime image
# -------------------------
FROM python:3.13-slim

WORKDIR /app

# Install minimal runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl git tzdata && \
    rm -rf /var/lib/apt/lists/*

# Copy only Python runtime and site-packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy rclone binary (installed to /usr/bin by rclone install script)
COPY --from=builder /usr/bin/rclone /usr/bin/rclone

# Copy jdupes and libjodycode shared library
COPY --from=builder /usr/local/lib/libjodycode* /usr/local/lib/
RUN ldconfig

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

# Create user/group for PUID/PGID support via start.sh
RUN groupadd -g 99 dockeruser && \
    useradd -u 100 -g 99 dockeruser && \
    chown -R 100:99 /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
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

ENTRYPOINT ["bash", "scripts/start.sh"]