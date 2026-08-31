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
  # Chown only what is actually wrong; an already-correct tree costs a stat pass
  # instead of a full rewrite of every inode.
  find "${CONFIG_DIR}" \( ! -user "${PUID}" -o ! -group "${PGID}" \) \
    -exec chown -h "${PUID}:${PGID}" {} + 2>/dev/null || true
  # Fail closed on the outcome, not the chown: a per-file error can be benign
  # (foreign uids on a network mount), an unwritable CONFIG_DIR cannot.
  probe="${CONFIG_DIR}/.chub-write-probe.$$"
  if ! runuser -u dockeruser -- touch "${probe}" 2>/dev/null; then
    echo "FATAL: ${CONFIG_DIR} is not writable by ${PUID}:${PGID} after ownership correction."
    echo "Pre-chown it on the host: sudo chown -R ${PUID}:${PGID} /path/to/config"
    exit 1
  fi
  runuser -u dockeruser -- rm -f "${probe}"
  # /app is deliberately NOT chowned: it only needs to be readable, and the image
  # bakes the bytecode so nothing writes there. See PYTHONDONTWRITEBYTECODE.
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
  # fchmod on an O_NOFOLLOW descriptor: a path-based chmod follows a symlink
  # swapped in after the match.
  python3 scripts/lock_config_perms.py "${CONFIG_DIR}" || locked=0
  if [ "${locked:-1}" != "1" ]; then
    echo "WARNING: could not restrict permissions on one or more files in ${CONFIG_DIR}."
    echo "Secrets there may be readable by other users on the host."
  fi
  # runuser instead of su: skips PAM, so the cap set documented in the
  # README (CHOWN/SETUID/SETGID/FOWNER) is sufficient — no need to grant
  # AUDIT_WRITE or DAC_OVERRIDE just for the user switch.
  exec runuser -s /bin/bash -c "python3 main.py" dockeruser
else
  exec python3 main.py
fi