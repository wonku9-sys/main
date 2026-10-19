"""Home navigation and explicit save/discard/cancel for local unsaved work."""
import weakref

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QLineEdit, QMessageBox, QPushButton, QSpinBox, QDoubleSpinBox, QTextEdit, QWidget,QTimeEdit


def _value(control):
    if isinstance(control,QTimeEdit):return control.time().toString('HH:mm')
    if isinstance(control, QComboBox):
        return control.currentData(), control.currentText()
    if isinstance(control, QCheckBox):
        return control.isChecked()
    if isinstance(control, QDateEdit):
        return control.date().toString("yyyy-MM-dd")
    if isinstance(control, (QSpinBox, QDoubleSpinBox)):
        return control.value()
    if isinstance(control, QTextEdit):
        return control.toPlainText()
    if isinstance(control, QLineEdit):
        return control.text()
    return None


def state(owner):
    name = type(owner).__name__
    if name in {"DiaryDialog","HouseholdDialog"}:return owner.snapshot()
    if name == "TradeDialog":
        return owner.kind, (owner.source or {}).get("id"), tuple(_value(getattr(owner, key)) for key in ("date", "partner", "member", "paid", "method", "points", "memo")), tuple(tuple(_value(row[key]) for key in ("product", "unit", "qty", "price")) for row in owner.line_rows)
    if name == "CountEditor":
        return owner.title.text(), _value(owner.date), tuple((key, field.text()) for key, field in sorted(owner.inputs.items()))
    if name == "PermissionsPage":
        return owner.user.currentData(), tuple((key, tuple((op, box.isChecked()) for op, box in checks.items())) for key, checks in owner.checks.items())
    if name == "SupplierGroupsDialog":
        return owner.loaded_kind, owner.group_id, tuple(owner.checked_members())
    if name in {"ProductDialog", "SettingsPage"}:
        extras = ("product_status", "tax_mode", "supplier", "unit", "price_basis", "tracked", "memo") if name == "ProductDialog" else ("point_enabled", "rounding_mode")
        basic = tuple((key, _value(field)) for key, field in owner.fields.items()), tuple(_value(getattr(owner, key)) for key in extras)
        return (basic, owner.backup_schedule_values()) if name == "SettingsPage" else basic
    controls = [control for control in owner.findChildren(QWidget) if isinstance(control, (QLineEdit, QComboBox, QCheckBox, QDateEdit, QTextEdit, QSpinBox, QDoubleSpinBox,QTimeEdit))]
    return tuple((id(control), _value(control)) for control in controls)


def ask_unsaved(owner):
    box = QMessageBox(owner)
    box.setWindowTitle("저장 확인")
    box.setIcon(QMessageBox.Icon.Question)
    box.setText("작업 중인 내용을 저장하시겠습니까?")
    box.setInformativeText("전표와 재고 실사는 초안으로 저장합니다. 저장하지 않음을 선택하면 입력한 변경을 버립니다.")
    box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
    box.button(QMessageBox.StandardButton.Save).setText("저장")
    box.button(QMessageBox.StandardButton.Discard).setText("저장하지 않음")
    box.button(QMessageBox.StandardButton.Cancel).setText("돌아가기")
    box.setDefaultButton(QMessageBox.StandardButton.Save)
    return box.exec()


def mark_saved(owner):
    guard = getattr(owner, "_navigation_guard", None)
    if guard:
        guard.track(owner)


def confirm_dialog_exit(owner):
    guard = getattr(owner, "_navigation_guard", None)
    return not guard or guard.allow_leave(owner)


class NavigationGuard(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.enabled, self.suspended = window, False, False
        self.saving = False
        self.snapshots = weakref.WeakKeyDictionary()
        self.dialogs = []

    def enable(self):
        if not self.enabled:
            QApplication.instance().installEventFilter(self)
            self.enabled = True
            self.track(self.window.current_page)

    def disable(self):
        QApplication.instance().removeEventFilter(self)
        self.enabled = False

    def belongs(self, widget):
        while widget is not None:
            if widget is self.window or getattr(widget,'_desktop_owner',None) is self.window:
                return True
            widget = widget.parentWidget()
        return False

    def editable(self, owner):
        if owner is None:
            return False
        name = type(owner).__name__
        if name in {"LoginDialog", "PartnerPicker", "ProductPicker", "CategoryDialog", "SupplierPicker"}:
            return False
        if name in {"SettingsPage", "PermissionsPage", "ProductDialog", "TradeDialog", "CountEditor", "SupplierPaymentDialog", "SupplierDialog", "SupplierGroupsDialog", "SalesFormDialog","DiaryDialog","HouseholdDialog"}:
            return not getattr(owner, "readonly", False)
        return isinstance(owner, QDialog) and bool(owner.findChildren(QDialogButtonBox)) and bool(getattr(owner, "fields", None))

    def track(self, owner):
        if self.enabled and self.editable(owner):
            owner._navigation_guard = self
            self.snapshots[owner] = state(owner)

    def changed(self, owner):
        try:
            return owner in self.snapshots and state(owner) != self.snapshots[owner]
        except RuntimeError:
            return False

    def allow_leave(self, owner):
        if not self.enabled or self.suspended or self.saving or not self.changed(owner):
            return True
        choice = ask_unsaved(owner)
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            self.saving = True
            try:
                before = self.window.store.audit_revision()
                name = type(owner).__name__
                if name in {"ProductDialog", "TradeDialog"}:
                    result = owner.save(False)
                elif name in {"CountEditor", "SupplierPaymentDialog", "SettingsPage", "PermissionsPage", "SupplierDialog", "SupplierGroupsDialog","DiaryDialog","HouseholdDialog"}:
                    result = owner.save()
                else:
                    result = None
                    buttons = owner.findChildren(QDialogButtonBox)
                    save = next((box.button(QDialogButtonBox.StandardButton.Save) for box in buttons if box.button(QDialogButtonBox.StandardButton.Save)), None)
                    if save:
                        save.click()
                after = self.window.store.audit_revision()
                if after == before and result is not True:
                    return False
            except (ValueError, PermissionError, OSError) as exc:
                QMessageBox.warning(owner, "저장할 수 없습니다", str(exc))
                return False
            finally:
                self.saving = False
        elif choice != QMessageBox.StandardButton.Discard:
            return False
        self.track(owner)
        return True

    def request_home(self):
        for reference in reversed(self.dialogs):
            dialog = reference()
            try:
                if dialog is not None and dialog.isVisible():
                    if not self.allow_leave(dialog):
                        return False
                    dialog.reject()
                    if dialog.isVisible():return False
                    QTimer.singleShot(0, self.request_home)
                    return True
            except RuntimeError:
                continue
        return self.window.open_page("home")

    def eventFilter(self, watched, event):
        if not self.enabled or self.suspended:
            return False
        if isinstance(watched, QDialog) and self.belongs(watched) and type(watched).__name__ not in {"LoginDialog", "QMessageBox", "QInputDialog", "QFileDialog", "QPrintDialog", "QPrintPreviewDialog"}:
            if event.type()==QEvent.Type.Polish and watched.parentWidget() is not None and not getattr(watched,'_desktop_owner',None):
                from PySide6.QtCore import Qt
                if watched.parentWidget() is self.window and getattr(self.window,'popup_menus',False):
                    owner=getattr(self.window,'popup_windows',{}).get(self.window.current_key)
                    if owner is not None and owner.isVisible():watched.setParent(owner,watched.windowFlags())
                watched.setWindowModality(Qt.WindowModality.WindowModal)
            if event.type() == QEvent.Type.Show and not getattr(watched, "_home_button", None):
                button = QPushButton("첫화면", watched)
                button.setAutoDefault(False)
                button.clicked.connect(self.request_home)
                if watched.layout():
                    watched.layout().addWidget(button)
                    watched._home_button = button
                self.dialogs.append(weakref.ref(watched))
                self.track(watched)
            elif event.type() == QEvent.Type.Close and not self.allow_leave(watched):
                event.ignore()
                return True
        return False
