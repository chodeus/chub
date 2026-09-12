# Vendored fonts

## arial32.exe

Microsoft's original, unmodified "Arial" self-extracting installer from the
SourceForge `corefonts` project (the same file Debian's
`ttf-mscorefonts-installer` downloads).

- Source: https://downloads.sourceforge.net/corefonts/arial32.exe
- md5: `9637df0e91703179f0723ec095a36cb5`
- Size: 554208 bytes

Vendored so no build or start fetches fonts over the network (the SourceForge
mirrors are flaky and have broken CI). The `:full` image ships this file and
the EULA in `/usr/share/chub/fonts/`; `scripts/install_fonts.sh` unpacks Arial
and Arial Bold into `/config/fonts` on each host at container start, for CL2K
text rendering (see `backend/util/cl2k/geometry.py`).

## Licensing

Redistribution of the **original, unmodified** `.exe` is permitted by the
Microsoft "TrueType core fonts for the Web" EULA, provided each copy is
complete and accompanied by that agreement — see `LICENSE-mscorefonts.txt`.
The **extracted `.ttf`** files are NOT redistributable: never bake them into an
image or commit them to this repo — they are unpacked only on the user's host.
