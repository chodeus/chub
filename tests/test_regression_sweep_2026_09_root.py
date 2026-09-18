"""Regression tests for the 2026-09 sweep, root batch — one per confirmed bug."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL_FONTS = ROOT / "scripts" / "install_fonts.sh"
ARIAL_EXE = ROOT / "deploy" / "docker" / "fonts" / "arial32.exe"


def _run_install(tmp_path, exe, path_prefix=None):
    env = {
        **os.environ,
        "CONFIG_DIR": str(tmp_path / "config"),
        "CHUB_FONT_INSTALLER": str(exe),
    }
    if path_prefix:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["bash", str(INSTALL_FONTS)], env=env, capture_output=True, text=True
    )


def _stub_cabextract(tmp_path, fail=False):
    """cabextract stand-in: logs each call, writes two fake fonts into its -d dir."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    body = "exit 1" if fail else 'echo x > "$d/arial.ttf"; echo x > "$d/arialbd.ttf"'
    stub = bindir / "cabextract"
    stub.write_text(
        "#!/bin/bash\n"
        f'echo call >> "{log}"\n'
        'while [ $# -gt 0 ]; do case "$1" in -d) d="$2"; shift;; esac; shift; done\n'
        f"{body}\n"
    )
    stub.chmod(0o755)
    return bindir, log


def test_install_fonts_unpacks_once_into_the_config_volume(tmp_path):
    """The image ships only the installer; fonts land in CONFIG_DIR, extracted once."""
    exe = tmp_path / "arial32.exe"
    exe.write_bytes(b"cab")
    bindir, log = _stub_cabextract(tmp_path)

    first = _run_install(tmp_path, exe, bindir)
    second = _run_install(tmp_path, exe, bindir)
    names = sorted(p.name for p in (tmp_path / "config" / "fonts").iterdir())
    calls = log.read_text().count("call")

    assert (first.returncode, second.returncode) == (0, 0)
    assert names == ["arial.ttf", "arialbd.ttf"]  # temp unpack dir cleaned up too
    assert calls == 1


def test_install_fonts_is_a_no_op_without_the_installer(tmp_path):
    """The lean image has no installer: nothing is created and start continues."""
    result = _run_install(tmp_path, tmp_path / "missing.exe")
    created = (tmp_path / "config" / "fonts").exists()

    assert result.returncode == 0
    assert not created


def test_install_fonts_failure_warns_but_never_fails_the_start(tmp_path):
    """A failed unpack leaves CL2K on its fallback font instead of stopping the container."""
    exe = tmp_path / "arial32.exe"
    exe.write_bytes(b"cab")
    bindir, _ = _stub_cabextract(tmp_path, fail=True)

    result = _run_install(tmp_path, exe, bindir)
    left = list((tmp_path / "config" / "fonts").iterdir())

    assert result.returncode == 0
    assert "WARNING" in result.stderr
    assert left == []


@pytest.mark.skipif(shutil.which("cabextract") is None, reason="needs cabextract")
def test_install_fonts_unpacks_the_vendored_arial(tmp_path):
    """The real installer yields both faces under their original names."""
    result = _run_install(tmp_path, ARIAL_EXE)
    fonts = tmp_path / "config" / "fonts"
    sizes = [(fonts / n).stat().st_size for n in ("arial.ttf", "arialbd.ttf")]

    assert result.returncode == 0, result.stderr
    assert min(sizes) > 100_000


def test_resolve_font_prefers_arial_unpacked_into_the_config_volume(tmp_path, monkeypatch):
    """CL2K must pick up the per-host unpack before any other candidate."""
    from backend.util.cl2k import geometry

    fonts = tmp_path / "fonts"
    fonts.mkdir()
    for name in ("arial.ttf", "arialbd.ttf"):
        (fonts / name).write_bytes(b"x")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))

    regular = geometry.resolve_font()
    bold = geometry.resolve_font(bold=True)

    assert regular == str(fonts / "arial.ttf")
    assert bold == str(fonts / "arialbd.ttf")


def test_gradient_generator_refuses_a_template_with_no_gradient(tmp_path, monkeypatch):
    """A fully transparent composite must not overwrite the committed gradient asset."""
    pytest.importorskip("psd_tools")
    from PIL import Image

    spec = importlib.util.spec_from_file_location(
        "gen_cl2k_gradient", ROOT / "scripts" / "gen_cl2k_gradient.py"
    )
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    target = tmp_path / "gradient.png"
    blank = Image.new("RGBA", (gen.geo.CANVAS_W, gen.geo.CANVAS_H), (0, 0, 0, 0))
    monkeypatch.setattr(gen.geo, "GRADIENT_PNG", target)
    monkeypatch.setattr(
        gen, "PSDImage", SimpleNamespace(open=lambda _src: SimpleNamespace(topil=lambda: blank))
    )
    monkeypatch.setattr(sys, "argv", ["gen_cl2k_gradient.py", "template.psd"])

    with pytest.raises(SystemExit, match="no gradient alpha"):
        gen.main()
    written = target.exists()

    assert not written
