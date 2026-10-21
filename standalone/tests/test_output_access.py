"""Output must recheck a second administrator's real committed revocations."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from pos2 import widgets
from pos2.loyalty_ui import MembersPage
from pos2.store import Store
from pos2.widgets import DataGrid, FormDialog, Page


@pytest.fixture(scope="module")
def app():
    result = QApplication.instance() or QApplication([])
    yield result
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    result.processEvents()


@pytest.fixture
def scenario(app, tmp_path, monkeypatch):
    admin = Store(tmp_path / "access.db")
    admin.setup_admin("admin", "관리자", "Output-Admin-2026!")
    admin.save_member({"code": "M1", "name": "보호 대상 회원", "phone": "010-1111-2222"})
    user = admin.save_user({"code": "staff", "name": "직원", "role": "staff",
                            "password": "Output-Staff-2026!", "permissions": ["loyalty"]})
    staff = Store(tmp_path / "access.db")
    staff.login("staff", "Output-Staff-2026!")
    page = MembersPage(SimpleNamespace(store=staff))
    page.refresh()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(_args[-1]))
    context = SimpleNamespace(admin=admin, staff=staff, user=user, page=page, warnings=warnings,
                              target=tmp_path / "forbidden.xlsx")
    yield context
    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    staff.close()
    admin.close()


@pytest.mark.parametrize("revoke", [{"active": False}, {"permissions": []}])
@pytest.mark.parametrize("operation", ["export", "print", "pdf"])
def test_bound_grid_blocks_committed_account_revocation(scenario, monkeypatch, operation, revoke):
    s = scenario
    assert s.page.grid.rowCount() == 1
    s.admin.save_user(revoke, s.user)
    file_dialogs, preview_dialogs = [], []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_kw: file_dialogs.append(1))
    monkeypatch.setattr(widgets, "QPrintPreviewDialog", lambda *_a: preview_dialogs.append(1))
    if operation == "export":
        result = s.page.grid.export(s.page, "회원")
    elif operation == "print":
        result = s.page.grid.print_pages(s.page, "회원")
    else:
        result = s.page.grid.to_pdf(s.target.with_suffix(".pdf"), "회원")
    assert result is None
    assert not s.target.exists() and not s.target.with_suffix(".pdf").exists()
    assert file_dialogs == preview_dialogs == []
    assert s.warnings
    assert all(grid.rowCount() == 0 for grid in s.page.findChildren(DataGrid))


@pytest.mark.parametrize("operation", ["export", "print"])
def test_page_guard_runs_even_when_grid_output_is_replaced(scenario, monkeypatch, operation):
    s = scenario
    s.admin.save_user({"permissions": []}, s.user)
    seen = []
    method = "export" if operation == "export" else "print_pages"
    monkeypatch.setattr(s.page.grid, method, lambda *_a, **_kw: seen.append(True))
    getattr(s.page, operation)()
    assert seen == []
    assert s.warnings
    assert s.page.grid.rowCount() == 0


def test_native_file_chooser_permission_change_prevents_any_written_file(scenario, monkeypatch):
    s = scenario
    def choose(*_args, **_kwargs):
        # This is a different SQLite connection committing during the dialog.
        s.admin.save_user({"active": False}, s.user)
        return str(s.target), ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    assert s.page.grid.export(s.page, "회원") is None
    assert not s.target.exists()
    assert s.page.grid.rowCount() == 0
    assert s.warnings


def test_preview_revalidates_each_paint_and_closes_without_printing(scenario, monkeypatch):
    s = scenario
    previews = []
    class Preview(QObject):
        paintRequested = Signal(object)
        def __init__(self, printer, _parent):
            super().__init__()
            self.printer, self.rejected = printer, False
            previews.append(self)
        def setWindowTitle(self, *_):
            pass
        def resize(self, *_):
            pass
        def reject(self):
            self.rejected = True
        def exec(self):
            s.admin.save_user({"permissions": []}, s.user)
            self.paintRequested.emit(self.printer)
    class NeverPaint:
        def __init__(self):
            pytest.fail("Revoked data reached the print document builder")
    monkeypatch.setattr(widgets, "QPrintPreviewDialog", Preview)
    monkeypatch.setattr(widgets, "QTextDocument", NeverPaint)
    s.page.grid.print_pages(s.page, "회원")
    assert len(previews) == 1 and previews[0].rejected
    assert s.page.grid.rowCount() == 0
    assert s.warnings


def test_pdf_rechecks_after_building_document_before_painter_starts(scenario, monkeypatch):
    s = scenario
    original = s.page.grid.document_html
    def build(*args, **kwargs):
        content = original(*args, **kwargs)
        s.admin.save_user({"active": False}, s.user)
        return content
    monkeypatch.setattr(s.page.grid, "document_html", build)
    target = s.target.with_suffix(".pdf")
    assert s.page.grid.to_pdf(target, "회원") is None
    assert not target.exists()
    assert s.page.grid.rowCount() == 0


def test_parentless_temporary_grid_uses_supplied_dialog_page_context(scenario, monkeypatch):
    s = scenario
    dialog = FormDialog("회원 상세", s.page)
    grid = DataGrid(["보호 자료"])
    grid.fill([["회원 이력"]])
    s.admin.save_user({"permissions": []}, s.user)
    assert grid.export(dialog, "임시 상세") is None
    assert grid.rowCount() == 0
    assert s.page.grid.rowCount() == 0
    dialog.close()
    grid.close()


def test_explicit_grid_permission_precedes_parent_class_and_supports_or(scenario, monkeypatch):
    s = scenario
    s.page.grid.read_permissions = ("trade", "reports")
    # A cash-close grid nested in a broader page must not inherit loyalty access.
    assert not widgets.authorize_output(s.page.grid, s.page)
    s.admin.save_user({"permissions": ["reports"]}, s.user)
    s.page.grid.fill([["허용 자료", "", "", 0, "", ""]])
    assert widgets.authorize_output(s.page.grid, s.page)
    assert s.page.grid.rowCount() == 1


def test_store_only_context_still_requires_live_login(scenario):
    s = scenario
    holder = QWidget()
    holder.store = s.staff
    grid = DataGrid(["자료"])
    grid.setParent(holder)
    grid.fill([["공통 자료"]])
    assert widgets.authorize_output(grid)
    s.admin.save_user({"active": False}, s.user)
    assert not widgets.authorize_output(grid)
    assert grid.rowCount() == 0
    holder.close()


def test_orphan_utility_grid_without_store_retains_export_and_pdf(app, tmp_path, monkeypatch):
    grid = DataGrid(["자료", "금액"])
    grid.fill([["독립 유틸리티", 1000]])
    target = tmp_path / "utility.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_kw: (str(target), ""))
    assert grid.export(title="유틸리티") == target
    assert target.exists()
    pdf = tmp_path / "utility.pdf"
    assert grid.to_pdf(pdf) == pdf
    assert pdf.read_bytes().startswith(b"%PDF-")
    grid.close()
