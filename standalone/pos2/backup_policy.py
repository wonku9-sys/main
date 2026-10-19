"""Local backup listing and weekly retention; always retain the newest 15."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import tempfile


BACKUP_NAME = re.compile(r"^(서영POS-백업|복원전-자동백업)_\d{8}_\d{6}_[0-9a-f]{8}\.db$")
KEEP = 15


class BackupPolicyMixin:
    def _backup_directory(self):
        if not self.path:
            raise ValueError("파일로 저장되는 장부에서만 백업할 수 있습니다.")
        folder = self.path.parent / "backups"
        if folder.resolve() != folder.absolute():
            raise ValueError("백업 폴더가 외부 바로가기로 연결되어 있습니다. 원래 데이터 폴더 안에 일반 폴더를 사용하세요.")
        if self.path.name == "seoyoung-standalone-demo.db":
            folder /= "demo"
            if folder.resolve() != folder.absolute():
                raise ValueError("체험 백업 폴더는 일반 폴더여야 합니다.")
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _backup_files(self):
        result = []
        for file in self._backup_directory().glob("*.db"):
            if file.is_symlink() or not file.is_file():
                continue
            stat = file.stat()
            result.append({"path": str(file), "name": file.name, "created": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                           "mtime_ns": stat.st_mtime_ns, "size": stat.st_size,
                           "kind": "복원 전 보호" if file.name.startswith("복원전-자동백업_") else "일반 백업",
                           "managed": bool(BACKUP_NAME.fullmatch(file.name))})
        return sorted(result, key=lambda item: (item["mtime_ns"], item["name"]), reverse=True)

    def backup_files(self):
        self._require("admin")
        return self._backup_files()

    def create_backup(self, before_restore=False):
        self._require("admin")
        prefix = "복원전-자동백업" if before_restore else "서영POS-백업"
        target = self._backup_directory() / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(4)}.db"
        # Incomplete files never enter either the selectable list or retention.
        partial = target.with_suffix(".pending")
        try:
            if target.exists():
                raise ValueError("같은 백업 파일이 이미 있습니다. 다시 시도하세요.")
            self.backup(partial)
            if target.exists():
                raise ValueError("같은 백업 파일이 이미 있습니다. 다시 시도하세요.")
            partial.rename(target)
        finally:
            if partial.exists():
                partial.unlink()
        with self._tx():
            self._require("admin")
            self._audit("managed_backup", "settings", None, {"file": target.name, "before_restore": before_restore})
        return str(target)

    def run_backup_retention(self, now_at=None):
        # This fixed maintenance policy runs after login, including staff shifts.
        # Viewing or selecting backups remains administrator-only.
        self._require()
        moment = now_at or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            raise ValueError("백업 정리 시각에 시간대가 필요합니다.")
        moment = moment.astimezone(timezone.utc)
        folder = self._backup_directory()
        state_path = folder / ".retention.json"
        previous = None
        if state_path.exists():
            try:
                previous = datetime.fromisoformat(json.loads(state_path.read_text(encoding="utf-8"))["last_cleanup"])
                if previous.tzinfo is None:
                    previous = None
            except (ValueError, TypeError, KeyError, OSError):
                previous = None
        result = {"deleted": [], "failed": [], "kept": len(self._backup_files()), "due": False}
        if previous and moment - previous < timedelta(days=7):
            return result
        if previous:
            result["due"] = True
            files = [item for item in self._backup_files() if item["managed"]]
            for candidate in files[KEEP:]:
                file = Path(candidate["path"])
                try:
                    # Re-check immediately before unlinking. User-supplied files,
                    # symlinks, and the newest 15 managed files are never deleted.
                    current = [item for item in self._backup_files() if item["managed"]]
                    if candidate["path"] in {item["path"] for item in current[:KEEP]}:
                        continue
                    if file.is_symlink() or file.stat().st_mtime_ns != candidate["mtime_ns"]:
                        continue
                    file.unlink()
                    result["deleted"].append(candidate["name"])
                except FileNotFoundError:
                    continue
                except OSError:
                    result["failed"].append(candidate["name"])
        descriptor, temporary_name = tempfile.mkstemp(prefix=".retention-", suffix=".tmp", dir=folder)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"last_cleanup": moment.isoformat(), "keep": KEEP}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, state_path)
        finally:
            if temporary.exists():
                temporary.unlink()
        result["kept"] = len(self._backup_files())
        return result
