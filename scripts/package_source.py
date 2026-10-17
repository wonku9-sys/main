"""Create a source-only ZIP with no databases, credentials or local tooling."""
import argparse
import hashlib
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    files = [ROOT / name for name in (
        "README.md", ".gitignore", ".python-version", "pyproject.toml", "uv.lock",
        "requirements.txt", "requirements-dev.txt", "run.py", "run_windows.bat", "build_windows.bat",
    )]
    for directory in ("seoyoung_pos", "tests", "scripts", "docs", ".github"):
        files.extend(p for p in (ROOT / directory).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".db", ".sqlite", ".xlsx", ".log"})
    archive_path = args.output / "SeoyoungPOS-source.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(set(files)):
            archive.write(path, Path("SeoyoungPOS-source") / path.relative_to(ROOT))
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip():
            raise RuntimeError("Source archive integrity check failed")
    with archive_path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    archive_path.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive_path.name}\n", encoding="ascii")
    print(f"{archive_path} · {len(set(files))} source files · SHA256 {checksum}")


if __name__ == "__main__":
    main()
