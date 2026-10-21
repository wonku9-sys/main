"""Archive only the newly written independent application and its own build files."""

import argparse
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from pos2 import __version__

ROOT = Path(__file__).resolve().parent
NAME = f"SY-POS-v{__version__}-source-아이콘3d.zip"


def source_files():
    files = list(ROOT.glob("*.md")) + list(ROOT.glob("requirements*.txt"))
    files += [ROOT / name for name in ("launch.py", "build_portable.py", "assemble_windows.py", "package_source.py", "pyproject.toml", "uv.lock", "setup_cloud.sh")]
    files += list((ROOT / "pos2").rglob("*.py")) + list((ROOT / "tests").rglob("*.py"))
    files += list((ROOT / "third-party-licenses").glob("*.txt"))
    files += [ROOT / "pos2" / "assets" / name for name in ("NotoSansKR-Regular.ttf", "OFL.txt", "FONT_SOURCE.md", "sy-monogram.png", "SY_LOGO.md")]
    files += [ROOT/'pos2'/'assets'/name for name in ('menu-icons-3d.png','MENU_ICONS_3D.md')]
    files += [ROOT/'pos2'/'assets'/name for name in ('output-icons-real3d.png','OUTPUT_ICONS_3D.md')]
    files += [ROOT/'pos2'/'assets'/name for name in ('payment-icons-real3d.png','PAYMENT_ICONS_3D.md')]
    files += [ROOT/'pos2'/'assets'/name for name in ('purchase-actions-real3d.png','PURCHASE_ACTIONS_3D.md')]
    files += [ROOT/'pos2'/'assets'/name for name in ('diary-real3d.png','household-real3d.png','PERSONAL_ICONS_3D.md')]
    files += [ROOT/'pos2'/'assets'/'sy-pos-wordmark-3d.png']
    files += list((ROOT / 'pos2' / 'assets').glob('step-*.svg'))
    files += [ROOT/'pos2'/'assets'/name for name in ('lottery-machine.jpg','LOTTERY_IMAGE.md')]
    files += [ROOT/'pos2'/'assets'/name for name in ('lucky-machine-realistic.png','LUCKY_MACHINE.md')]
    from pos2.audio_defaults import SOUNDS,MOUSE_PCM,default_source,mouse_pcm_source
    if not all(default_source(kind) is not None for kind in SOUNDS):
        raise ValueError('Approved audio is missing or changed; do not publish an incomplete source package.')
    files += [ROOT/'pos2'/'assets'/'sounds'/row[0] for row in SOUNDS.values()]
    if not all(mouse_pcm_source(kind,default_source(kind)) is not None for kind in MOUSE_PCM):
        raise ValueError('Verified low-latency mouse PCM files are missing or changed.')
    files += [ROOT/'pos2'/'assets'/'sounds'/row[0] for row in MOUSE_PCM.values()]
    files += [ROOT/'pos2'/'assets'/'sounds'/'SOUNDS.md']
    files += [ROOT.parent / ".github" / "workflows" / name for name in ('standalone-windows.yml','native-package-retry.yml','menu-effects-release.yml','lucky-sequence-release.yml','personal-contrast-release.yml','payment-access-release.yml','business-profile-release.yml')]
    files += [ROOT.parent/'.github'/'workflows'/'manual-purchase-release.yml']
    for source in sorted(set(files)):
        if source.is_file() and "__pycache__" not in source.parts:
            yield source


def package(output):
    output.mkdir(parents=True, exist_ok=True)
    archive = output / NAME
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    if archive.exists() or checksum.exists():
        raise ValueError("Source output already exists. Choose a new output folder to preserve the previous package.")
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as stream:
        for source in source_files():
            relative = source.relative_to(ROOT.parent)
            if "seoyoung_pos" in relative.parts:
                raise ValueError("The old application must not enter the new source package.")
            stream.write(source, Path("SY-POS-source") / relative)
    with ZipFile(archive) as stream:
        if stream.testzip() is not None:
            raise ValueError("Source ZIP CRC validation failed.")
    digest = sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Standalone source: {archive}\nSHA256 {digest}", flush=True)
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", default=ROOT / "dist")
    package(parser.parse_args().output)
