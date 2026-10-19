"""Cache-only packaging must retain integrity checks and never use the network."""

import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest

from scripts import windows_portable as portable


@pytest.fixture
def artifact_cache(tmp_path, monkeypatch):
    runtime_bytes = b"test runtime archive"
    wheel_bytes = b"test wheel archive"
    wheel_name = "example-1.0-py3-none-any.whl"
    (tmp_path / "python.3.12.10.nupkg").write_bytes(runtime_bytes)
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / wheel_name).write_bytes(wheel_bytes)
    monkeypatch.setattr(portable, "PYTHON_SHA512", base64.b64encode(hashlib.sha512(runtime_bytes).digest()).decode("ascii"))
    monkeypatch.setattr(portable, "WHEELS", (("example", "1.0", wheel_name, hashlib.sha256(wheel_bytes).hexdigest()),))
    return tmp_path, wheel_name


@pytest.fixture
def reject_network(monkeypatch):
    def forbidden(url):
        pytest.fail(f"Offline cache attempted a network request: {url}")
    monkeypatch.setattr(portable, "read_url", forbidden)


def test_cached_artifacts_verify_without_metadata_requests(artifact_cache, reject_network):
    cache, wheel_name = artifact_cache
    runtime, wheels, manifest = portable.upstream_artifacts(cache, offline_cache=True)
    assert runtime == cache / "python.3.12.10.nupkg"
    assert wheels == [cache / "wheels" / wheel_name]
    assert manifest[0]["verification_mode"] == "pinned_checksum_cache_only"
    wheel = manifest[1]
    assert wheel["metadata_fetched"] is False
    assert wheel["metadata"] == "https://pypi.org/pypi/example/1.0/json"
    assert wheel["verification_mode"] == "pinned_checksum_cache_only"
    assert "url" not in wheel  # No artifact URL is invented from a metadata URL.


@pytest.mark.parametrize("relative", ["python.3.12.10.nupkg", "wheels/example-1.0-py3-none-any.whl"])
def test_offline_missing_artifact_fails_without_download(artifact_cache, reject_network, relative):
    cache, _ = artifact_cache
    (cache / relative).unlink()
    with pytest.raises(FileNotFoundError, match="Offline cache file missing"):
        portable.upstream_artifacts(cache, offline_cache=True)


@pytest.mark.parametrize("relative", ["python.3.12.10.nupkg", "wheels/example-1.0-py3-none-any.whl"])
def test_offline_tampered_artifact_rejected(artifact_cache, reject_network, relative):
    cache, _ = artifact_cache
    (cache / relative).write_bytes(b"tampered cache")
    with pytest.raises(RuntimeError, match="Cached checksum mismatch"):
        portable.upstream_artifacts(cache, offline_cache=True)


def test_online_mode_still_cross_checks_pinned_upstream_metadata(artifact_cache, monkeypatch):
    cache, wheel_name = artifact_cache
    calls = []
    expected = portable.WHEELS[0][3]
    def metadata(url):
        calls.append(url)
        return json.dumps({"urls": [{"filename": wheel_name, "digests": {"sha256": expected},
                                      "url": "https://files.pythonhosted.org/example.whl"}]}).encode()
    monkeypatch.setattr(portable, "read_url", metadata)
    _, _, manifest = portable.upstream_artifacts(cache)
    assert calls == ["https://pypi.org/pypi/example/1.0/json"]
    assert manifest[1]["metadata_fetched"] is True
    assert manifest[1]["url"] == "https://files.pythonhosted.org/example.whl"
    monkeypatch.setattr(portable, "WHEELS", (("example", "1.0", wheel_name, "0" * 64),))
    with pytest.raises(RuntimeError, match="Upstream checksum changed"):
        portable.upstream_artifacts(cache)


def test_offline_license_text_and_source_license_are_hash_verified(tmp_path, monkeypatch, reject_network):
    cache = tmp_path / "cache"
    cache.mkdir()
    text = b"Example license text"
    (cache / "Qt-LGPL-3.0-only.txt").write_bytes(text)
    archive_path = cache / "example-1.0.tar.gz"
    source_license = b"MIT example source license"
    with tarfile.open(archive_path, "w:gz") as archive:
        entry = tarfile.TarInfo("example-1.0/LICENSE.txt")
        entry.size = len(source_license)
        archive.addfile(entry, io.BytesIO(source_license))
    monkeypatch.setattr(portable, "LICENSE_INPUTS", (
        ("Qt-LGPL-3.0-only.txt", "https://example.invalid/license", hashlib.sha256(text).hexdigest()),
        (archive_path.name, "https://example.invalid/source", portable.digest(archive_path)),
    ))
    destination = tmp_path / "bundle"
    destination.mkdir()
    sources = portable.copy_licenses(destination, cache, offline_cache=True)
    assert (destination / "licenses" / "Qt-LGPL-3.0-only.txt").read_bytes() == text
    assert (destination / "licenses" / "example-LICENSE.txt").read_bytes() == source_license
    assert all(source["verification_mode"] == "pinned_checksum_cache_only" for source in sources)


@pytest.mark.parametrize("state", ["missing", "tampered"])
def test_offline_missing_or_tampered_license_never_downloads(tmp_path, monkeypatch, reject_network, state):
    expected = hashlib.sha256(b"trusted license").hexdigest()
    monkeypatch.setattr(portable, "LICENSE_INPUTS", (("license.txt", "https://example.invalid/license", expected),))
    destination = tmp_path / "bundle"
    destination.mkdir()
    if state == "tampered":
        (tmp_path / "license.txt").write_bytes(b"changed license")
    error = FileNotFoundError if state == "missing" else RuntimeError
    with pytest.raises(error):
        portable.copy_licenses(destination, tmp_path, offline_cache=True)


def test_source_copy_includes_all_python_modules_without_business_data(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    package = checkout / "seoyoung_pos"
    (package / "nested").mkdir(parents=True)
    (package / "app.py").write_text("# current app\n", encoding="utf-8")
    (package / "loyalty.py").write_text("# loyalty\n", encoding="utf-8")
    (package / "nested" / "module.py").write_text("# nested\n", encoding="utf-8")
    (package / "business.db").write_bytes(b"private data")
    (package / ".env").write_text("SECRET=do-not-bundle", encoding="utf-8")
    (package / "app.pyc").write_bytes(b"old bytecode")
    monkeypatch.setattr(portable, "ROOT", checkout)
    destination = tmp_path / "bundle"
    hashes = portable.copy_source(destination)
    assert set(hashes) == {"app.py", "loyalty.py", str(Path("nested/module.py"))}
    copied = destination / "app" / "seoyoung_pos"
    assert sorted(path.suffix for path in copied.rglob("*") if path.is_file()) == [".py"] * 3
    assert all(portable.digest(copied / name) == expected for name, expected in hashes.items())


def test_cli_forwards_offline_cache_and_separate_output(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(portable, "build", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(sys, "argv", ["windows_portable.py", "--offline-cache", "--cache", str(tmp_path / "cache"),
                                    "--output", str(tmp_path / "new-output")])
    assert portable.main() == 0
    args, kwargs = calls[0]
    assert args == (tmp_path / "cache", tmp_path / "new-output")
    assert kwargs == {"refresh_source": False, "offline_cache": True}


def test_only_named_documentation_and_demo_pngs_are_copied(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    package = checkout / "seoyoung_pos"
    package.mkdir(parents=True)
    (package / "app.py").write_text("# application\n", encoding="utf-8")
    docs = checkout / "docs"
    screenshots = docs / "screenshots"
    screenshots.mkdir(parents=True)
    names = {"windows-portable-notes.md", "MANUAL_SCOPE.md", "VALIDATION.md", "RELEASE_NOTES.md"}
    for name in names:
        (docs / name).write_text(f"# {name}\n", encoding="utf-8")
    (docs / "private.md").write_text("Unpublished private note", encoding="utf-8")
    (docs / "private.db").write_bytes(b"Private business data")
    (screenshots / "demo.png").write_bytes(b"Example generated screenshot")
    (screenshots / "private.db").write_bytes(b"Private business data")
    (screenshots / "attachment.jpg").write_bytes(b"User attachment")
    monkeypatch.setattr(portable, "ROOT", checkout)
    destination = tmp_path / "bundle"
    portable.copy_source(destination)
    copied = destination / "docs"
    assert {path.name for path in copied.glob("*.md")} == names
    assert {path.name for path in (copied / "screenshots").iterdir()} == {"demo.png"}
    assert not list(destination.rglob("*.db"))
