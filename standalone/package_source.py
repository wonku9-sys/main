"""Archive only the newly written independent application and its own build files."""

import argparse
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from pos2 import __version__

ROOT = Path(__file__).resolve().parent
NAME = f"SeoyoungPOS-Standalone-v{__version__}-source.zip"


def source_files():
    files = list(ROOT.glob("*.md")) + list(ROOT.glob("requirements*.txt"))
    files += [ROOT / name for name in ("launch.py", "build_portable.py", "package_source.py", "pyproject.toml", "uv.lock", "setup_cloud.sh")]
    files += list((ROOT / "pos2").rglob("*.py")) + list((ROOT / "tests").rglob("*.py"))
    files += list((ROOT / "third-party-licenses").glob("*.txt"))
    files += [ROOT / "pos2" / "assets" / name for name in ("NotoSansKR-Regular.ttf", "OFL.txt", "FONT_SOURCE.md")]
    files += [ROOT.parent / ".github" / "workflows" / "standalone-windows.yml"]
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
            stream.write(source, Path("SeoyoungPOS-Standalone-source") / relative)
    with ZipFile(archive) as stream:
        if stream.testzip() is not None:
            raise ValueError("Source ZIP CRC validation failed.")
    digest = sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Standalone source: {archive}\nSHA256 {digest}", flush=True)
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", default=ROOT / "dist")
    package(parser.parse_args().output)
