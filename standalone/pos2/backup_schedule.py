"""Local daily/weekly/interval backups; catch up once after missed schedules."""
from datetime import datetime, time, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import tempfile


DEFAULT_BACKUP_SCHEDULE = {"mode": "auto", "frequency": "daily", "time": "20:00", "weekdays": [0], "every_days": 7, "on_exit": True}


def validate_schedule(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_BACKUP_SCHEDULE):
        raise ValueError("백업 일정 항목을 확인하세요.")
    if not isinstance(value["mode"], str) or not isinstance(value["frequency"], str) or value["mode"] not in {"auto", "manual"} or value["frequency"] not in {"daily", "weekly", "interval"}:
        raise ValueError("백업 방식과 주기를 확인하세요.")
    try:
        clock = time.fromisoformat(value["time"])
        if len(value["time"]) != 5 or clock.tzinfo is not None:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("백업 시간은 HH:mm 형식으로 입력하세요.") from None
    days = value["weekdays"]
    if not isinstance(days, list) or any(type(day) is not int or not 0 <= day <= 6 for day in days):
        raise ValueError("백업 요일을 확인하세요.")
    if value["frequency"] == "weekly" and not days:
        raise ValueError("백업할 요일을 하나 이상 선택하세요.")
    if type(value["every_days"]) is not int or not 1 <= value["every_days"] <= 365 or type(value["on_exit"]) is not bool:
        raise ValueError("백업 간격은 1~365일이며 종료 백업은 체크 값이어야 합니다.")
    return {**value, "weekdays": sorted(set(days))}


def _write_state(path, data):
    descriptor, temporary_name = tempfile.mkstemp(prefix=".schedule-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def planned_event(policy, anchor, moment):
    clock = time.fromisoformat(policy["time"])
    candidate = moment.date()
    if datetime.combine(candidate, clock, moment.tzinfo) > moment:
        candidate -= timedelta(days=1)
    if policy["frequency"] == "weekly":
        for _ in range(7):
            if candidate.weekday() in policy["weekdays"]:
                break
            candidate -= timedelta(days=1)
    elif policy["frequency"] == "interval":
        offset = (candidate - anchor).days // policy["every_days"]
        candidate = anchor + timedelta(days=offset * policy["every_days"])
    return datetime.combine(candidate, clock, moment.tzinfo) if candidate >= anchor else None


class BackupScheduleMixin:
    def backup_schedule(self):
        self._require()
        return validate_schedule(self._settings_values().get("backup_schedule", DEFAULT_BACKUP_SCHEDULE))

    def _automatic_backup(self, reason):
        self._require()
        if reason not in {"schedule", "exit"}:
            raise ValueError("지원하지 않는 자동 백업입니다.")
        prefix = "서영POS-종료백업" if reason == "exit" else "서영POS-자동백업"
        target = self._backup_directory() / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(4)}.db"
        partial = target.with_suffix(".pending")
        try:
            self._backup_file(partial)
            if target.exists():
                raise ValueError("같은 백업 파일이 있습니다. 다시 시도하세요.")
            partial.rename(target)
        finally:
            if partial.exists():
                partial.unlink()
        with self._tx():
            self._require()
            self._audit("automatic_backup", "settings", None, {"file": target.name, "reason": reason})
        return str(target)

    def run_scheduled_backup(self, now_at=None):
        policy = self.backup_schedule()
        if policy["mode"] == "manual":
            return None
        moment = now_at or datetime.now().astimezone()
        if moment.tzinfo is None:
            raise ValueError("백업 시각에 시간대가 필요합니다.")
        path = self._backup_directory() / ".schedule.json"
        fingerprint = sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("policy") != fingerprint:
                raise ValueError
            anchor = datetime.fromisoformat(data["anchor"]).date()
            last = datetime.fromisoformat(data["last_event"]) if data.get("last_event") else None
            if last and last.tzinfo is None:
                raise ValueError
        except (OSError, ValueError, TypeError, KeyError):
            anchor, last = moment.date(), None
            data = {"policy": fingerprint, "anchor": anchor.isoformat(), "last_event": None}
            _write_state(path, data)
        event = planned_event(policy, anchor, moment)
        if not event or last and event <= last:
            return None
        if data.get("last_attempt"):
            try:
                if moment - datetime.fromisoformat(data["last_attempt"]) < timedelta(minutes=5):
                    return None
            except (ValueError, TypeError):
                pass
        data["last_attempt"] = moment.isoformat()
        _write_state(path, data)
        result = self._automatic_backup("schedule")
        data.update(last_event=event.isoformat(), last_success=moment.isoformat(), last_file=Path(result).name)
        _write_state(path, data)
        return result

    def backup_on_exit(self):
        return self._automatic_backup("exit") if self.backup_schedule()["on_exit"] else None
