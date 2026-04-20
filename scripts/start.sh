#!/bin/bash

set -euo pipefail

# Default UID/GID if not passed via environment
PUID=${PUID:-100}
PGID=${PGID:-99}
UMASK=${UMASK:-002}
BRANCH=${BRANCH:-master}

export RCLONE_CONFIG="${CONFIG_DIR}/rclone/rclone.conf"

VERSION=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['.'])" "$(dirname "$0")/../.release-please-manifest.json")

echo "
═════════════════════════════════════════════════════════

     ██████╗██╗  ██╗██╗   ██╗██████╗
    ██╔════╝██║  ██║██║   ██║██╔══██╗
    ██║     ███████║██║   ██║██████╔╝
    ██║     ██╔══██║██║   ██║██╔══██╗
    ╚██████╗██║  ██║╚██████╔╝██████╔╝
     ╚═════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝

          Chodeus' Media Script Hub

─────────────────────────────────────────────────────────
        PUID:           ${PUID}
        PGID:           ${PGID}
        UMASK:          ${UMASK}
        BRANCH:         ${BRANCH}
        DOCKER:         ${DOCKER_ENV}
        VERSION:        ${VERSION}
        CONFIG_DIR:     ${CONFIG_DIR}
        RCLONE_CONFIG:  ${RCLONE_CONFIG}
        LOG_DIR:        ${LOG_DIR}
═════════════════════════════════════════════════════════
"

echo "Setting umask to ${UMASK}"
umask "$UMASK"

echo "Starting CHUB as $(whoami) with UID: $PUID and GID: $PGID"
if [ "$(id -u)" = "0" ]; then
  groupmod -o -g "$PGID" dockeruser
  usermod -o -u "$PUID" dockeruser
  chown -R "${PUID}:${PGID}" "${CONFIG_DIR}"
  # Only recursive-chown /app when ownership doesn't match (avoids 10-30s delay on every restart)
  # The Dockerfile already sets ownership; this only runs if PUID/PGID changed
  if [ "$(stat -c '%u:%g' /app 2>/dev/null)" != "${PUID}:${PGID}" ]; then
    chown -R "${PUID}:${PGID}" /app
  fi
  chmod -R 777 "${CONFIG_DIR}"
  [ -f "${CONFIG_DIR}/config.yml" ] && chmod 660 "${CONFIG_DIR}/config.yml"
  exec su -s /bin/bash -c "python3 main.py" dockeruser
else
  exec python3 main.py
fi