#!/bin/bash
# Unpacks Arial for CL2K from the vendored installer into CONFIG_DIR/fonts; never fails the start.
set -u

exe="${CHUB_FONT_INSTALLER:-/usr/share/chub/fonts/arial32.exe}"
dest="${CONFIG_DIR:-/config}/fonts"

[ -f "$exe" ] || exit 0  # lean image: no CL2K, no installer
[ -s "$dest/arial.ttf" ] && [ -s "$dest/arialbd.ttf" ] && exit 0

if ! mkdir -p "$dest" || ! tmp="$(mktemp -d "$dest/.unpack.XXXXXX")"; then
  echo "WARNING: cannot write $dest; CL2K text uses the fallback font." >&2
  exit 0
fi
trap 'rm -rf "$tmp"' EXIT

if cabextract -q -L -F 'arial*.ttf' -d "$tmp" "$exe" >/dev/null 2>&1 \
  && mv "$tmp/arial.ttf" "$tmp/arialbd.ttf" "$dest/"; then
  echo "Unpacked Arial for CL2K into $dest"
else
  echo "WARNING: could not unpack Arial into $dest; CL2K text uses the fallback font." >&2
fi
exit 0
