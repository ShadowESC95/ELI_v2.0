"""Lock on the multi-frame Windows icon.

`write_packaged_icons` built its .ico by saving `imgs[0]` — the 16x16 — with a
`sizes=` list running up to 256, plus `append_images`. Pillow's ICO writer clamps
every requested size to the base image, so that produced a SINGLE 16x16 frame
(668 bytes) instead of seven (95KB): a fuzzy shortcut at every size above 16px,
which commit 1b90948 had already had to fix once by hand.

It was worse than a bad icon. `scripts/package_desktop_app.sh` regenerates icons
during a release build, so running the builder reverted the committed .ico in the
working tree — and anyone staging broadly after a build would commit the
regression straight back in. It was caught exactly that way: a build left the
95,577-byte icon sitting at 566 bytes.

These assertions read the ICO container directly rather than going through
Pillow: conftest force-mocks PIL for the whole suite, so an image-library test
would silently assert nothing. Parsing the bytes also checks the artifact that
actually ships, not just the code that writes it.
"""
import struct
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_ICO = REPO_ROOT / "packaging" / "desktop" / "Eli_Icon.ico"

EXPECTED_SIZES = {16, 24, 32, 48, 64, 128, 256}


def _ico_frame_sizes(path: Path) -> set[int]:
    """Frame widths declared in an .ico directory. No image library involved.

    Layout: a 6-byte header (reserved, type, count) then one 16-byte entry per
    frame whose first byte is the width — with 0 meaning 256, since the field is
    a single byte and 256 does not fit.
    """
    blob = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", blob[:6])
    assert reserved == 0 and kind == 1, f"{path.name} is not an .ico"
    sizes = set()
    for i in range(count):
        entry = 6 + i * 16
        width = blob[entry]
        sizes.add(256 if width == 0 else width)
    return sizes


@pytest.fixture(scope="module")
def frame_sizes() -> set[int]:
    if not COMMITTED_ICO.is_file():
        pytest.skip(f"no committed icon at {COMMITTED_ICO}")
    return _ico_frame_sizes(COMMITTED_ICO)


def test_icon_carries_every_frame(frame_sizes):
    assert frame_sizes == EXPECTED_SIZES


def test_icon_is_not_a_single_small_frame(frame_sizes):
    """The exact regression a release build reintroduced."""
    assert frame_sizes != {16}, "collapsed back to a single 16x16 frame"
    assert len(frame_sizes) >= 7


def test_icon_has_a_full_resolution_frame(frame_sizes):
    """256px is what Windows uses for large shortcut and Explorer tile views."""
    assert 256 in frame_sizes


def test_icon_is_not_the_truncated_artifact():
    """Size is the cheapest tripwire: the broken icon was ~566 bytes, the real one
    ~95KB. A build that quietly rewrites it shows up here immediately."""
    assert COMMITTED_ICO.stat().st_size > 10_000, (
        f"{COMMITTED_ICO.stat().st_size} bytes — that is the one-frame icon, "
        "not the full set; did a release build overwrite it?"
    )


def test_generator_saves_from_the_largest_frame():
    """Guard the cause, not just the symptom: saving from imgs[0] is what collapsed
    the file, and PIL being mocked here means only the source can be inspected."""
    src = (REPO_ROOT / "eli" / "gui" / "branding.py").read_text(encoding="utf-8")
    assert "append_images=imgs[1:]" not in src, (
        "saving the .ico from the smallest frame clamps every size to 16x16"
    )
    assert "master.save(ico_path" in src


def test_linux_scalable_icon_is_rendered_square():
    """The scalable hicolor slot copied the source art in verbatim — 175x157, not
    square and smaller than the 256 slot beside it, so a desktop preferring
    "scalable" got the worst icon of the set. It must be rendered like the rest."""
    src = (REPO_ROOT / "eli" / "gui" / "branding.py").read_text(encoding="utf-8")
    scalable_block = src[src.index("scalable = theme_base"):]
    scalable_block = scalable_block[: scalable_block.index("return ICON_NAME")]

    assert "_square_png_bytes" in scalable_block, "scalable icon must be rendered square"
    assert "shutil.copy2" not in scalable_block, "raw source art is not square"
