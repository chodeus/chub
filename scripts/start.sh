#!/bin/bash

set -euo pipefail

# Default UID/GID if not passed via environment
PUID=${PUID:-99}
PGID=${PGID:-100}
UMASK=${UMASK:-002}
BRANCH=${BRANCH:-master}

# Rootless (`docker run --user uid:gid`): PUID/PGID can't be applied without root,
# so show the real ids in the banner.
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
  # Chowns only what is actually wrong, through NOFOLLOW directory fds: a
  # path-based chown follows an intermediate dir swapped for a symlink.
  python3 scripts/config_perms.py chown "${CONFIG_DIR}" "${PUID}" "${PGID}" || true
  # Fail closed on the outcome, not the chown: a per-file error can be benign
  # (foreign uids on a network mount), an unwritable CONFIG_DIR cannot.
  probe="${CONFIG_DIR}/.chub-write-probe.$$"
  if ! runuser -u dockeruser -- touch "${probe}" 2>/dev/null; then
    echo "FATAL: ${CONFIG_DIR} is not writable by ${PUID}:${PGID} after ownership correction."
    echo "Pre-chown it on the host: sudo chown -R ${PUID}:${PGID} /path/to/config"
    exit 1
  fi
  runuser -u dockeruser -- rm -f "${probe}"
  runuser -u dockeruser -- bash scripts/install_fonts.sh
  # /app stays root-owned (bytecode is baked). CONFIG_DIR relies on ownership + umask,
  # not 777; CHUB_LEGACY_CHMOD=1 restores the recursive 777 for mismatched-UID setups.
  if [ "${CHUB_LEGACY_CHMOD:-0}" = "1" ]; then
    chmod -R 777 "${CONFIG_DIR}"
  fi
  # fchmod on an O_NOFOLLOW descriptor: a path-based chmod follows a symlink
  # swapped in after the match.
  if ! python3 scripts/config_perms.py lock "${CONFIG_DIR}"; then
    echo "WARNING: could not restrict permissions on one or more files in ${CONFIG_DIR}."
    echo "Secrets there may be readable by other users on the host."
  fi
  # runuser, not su: no password prompt, and its own PAM config (/etc/pam.d/runuser).
  exec runuser -s /bin/bash -c "python3 main.py" dockeruser
else
  bash scripts/install_fonts.sh
  exec python3 main.py
fi