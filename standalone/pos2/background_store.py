"""Local database work uses a separate connection owned by its worker thread."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication


class StoreTask(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, parent, store, method, args=(), login=False):
        super().__init__(parent)
        self.path, self.method, self.args, self.login = store.path, method, args, login
        self.session = (dict(store.actor) if store.actor else None,
                        store._session_password_hash, store._restore_token)
        app = QApplication.instance()
        if not hasattr(app, '_sy_catalog_workers'):
            app._sy_catalog_workers = []
        app._sy_catalog_workers.append(self)
        def forget(*_):
            if self in app._sy_catalog_workers:app._sy_catalog_workers.remove(self)
        self.finished.connect(forget)
        # A parent may be destroyed after run() stops but before the queued
        # finished callback is delivered. Never retain a deleted Qt wrapper.
        self.destroyed.connect(forget)

    def run(self):
        from .store import Store
        store = None
        try:
            store = Store(self.path)
            if self.login:
                code, password, replacement, target = self.args
                store.login(code, password)
                from .permissions import has_menu
                if not has_menu(store.actor, target):
                    raise PermissionError('이 메뉴의 사용 권한이 없습니다.')
                if replacement:
                    store.change_password(password, replacement)
                result = dict(actor=store.actor, password_hash=store._session_password_hash,
                              restore_token=store._restore_token)
            else:
                store.actor, store._session_password_hash, store._restore_token = self.session
                result = getattr(store, self.method)(*self.args)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.args = ()  # Do not retain login passwords after the task.
            if store is not None:
                store.close()
