# Vendored fonts

## arial32.exe

Microsoft's original, unmodified "Arial" self-extracting installer from the
SourceForge `corefonts` project (the same file Debian's
`ttf-mscorefonts-installer` downloads).

- Source: https://downloads.sourceforge.net/corefonts/arial32.exe
- md5: `9637df0e91703179f0723ec095a36cb5`
- Size: 554208 bytes

Vendored so the Docker image build never fetches fonts over the network at
build time (the SourceForge mirrors are flaky and have broken CI). The
`deploy/docker/Dockerfile` runtime stage `cabextract`s it and installs Arial +
Arial Bold for CL2K text rendering (see `backend/util/cl2k/geometry.py`).

## Licensing

Redistribution of the **original, unmodified** `.exe` is permitted by the
Microsoft "TrueType core fonts for the Web" EULA, provided each copy is
complete and accompanied by that agreement — see `LICENSE-mscorefonts.txt`.
The **extracted `.ttf`** files are NOT redistributable: they are unpacked only
inside the built image and must never be committed to this repo.
