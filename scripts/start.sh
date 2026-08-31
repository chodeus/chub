#!/bin/bash

set -euo pipefail

# Default UID/GID if not passed via environment
PUID=${PUID:-99}
PGID=${PGID:-100}
UMASK=${UMASK:-002}
BRANCH=${BRANCH:-master}

# When started rootless (e.g. `docker run --user 99:100`), PUID/PGID env
# vars are ignored — we can't usermod without root. Show the real uid/gid
# in the banner so the operator sees what's actually running.
if [ "$(id -u)" != "0" ]; then
  PUID=$(id -u)
  PGID=$(id -g)
fi

export RCLONE_CONFIG="${CONFIG_DIR}/rclone/rclone.conf"

VERSION=$(cd "$(dirname "$0")/.." && python3 -c "from backend.util.version import get_version; print(get_version())")

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

umask "$UMASK"

if [ "$(id -u)" = "0" ]; then
  echo "Dropping privileges to dockeruser (PUID=${PUID}, PGID=${PGID})"
  groupmod -o -g "$PGID" dockeruser
  usermod -o -u "$PUID" dockeruser
  chown -R "${PUID}:${PGID}" "${CONFIG_DIR}"
  # Only recursive-chown /app when ownership doesn't match (avoids 10-30s delay on every restart)
  # The Dockerfile already sets ownership; this only runs if PUID/PGID changed
  if [ "$(stat -c '%u:%g' /app 2>/dev/null)" != "${PUID}:${PGID}" ]; then
    chown -R "${PUID}:${PGID}" /app
  fi
  # CONFIG_DIR is private to this container (owned by PUID:PGID above), so it
  # does not need world-writable 777. Cross-container sharing (e.g. Kometa
  # reading the assets mount) happens on OTHER mounts and works via umask 002
  # group perms. Lock down the secrets so the service-account key, DB and rclone
  # token aren't world-readable on the host; everything else relies on ownership
  # + umask. (Set CHUB_LEGACY_CHMOD=1 to restore the old recursive 777 if a
  # mismatched-UID container of yours depends on it.)
  if [ "${CHUB_LEGACY_CHMOD:-0}" = "1" ]; then
    chmod -R 777 "${CONFIG_DIR}"
  fi
  chmod 600 "${CONFIG_DIR}"/config.yml "${CONFIG_DIR}"/config.yml.legacy-* 2>/dev/null || true
  chmod 600 "${CONFIG_DIR}"/*.json 2>/dev/null || true
  chmod 660 "${CONFIG_DIR}"/chub.db "${CONFIG_DIR}"/rclone/rclone.conf \
    "${CONFIG_DIR}"/rclone.conf 2>/dev/null || true
  # runuser instead of su: skips PAM, so the cap set documented in the
  # README (CHOWN/SETUID/SETGID/FOWNER) is sufficient — no need to grant
  # AUDIT_WRITE or DAC_OVERRIDE just for the user switch.
  exec runuser -s /bin/bash -c "python3 main.py" dockeruser
else
  exec python3 main.py
fi