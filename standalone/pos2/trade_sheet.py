"""One continuous worksheet, without nested rounded input cards in each cell."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QComboBox, QLineEdit, QTableWidgetItem
from .widgets import HeaderSafeTable


class EntrySheet(HeaderSafeTable):
    """Shared visual contract for data-entry tables; no business/key behavior changes."""
    def __init__(self, rows=0, columns=0, parent=None):
        super().__init__(rows, columns, parent)
        self.setObjectName('entryWorksheet')
        self.setProperty('syEntryWorksheet', True)
        self.setShowGrid(True)
        self.setAlternatingRowColors(False)
        self.setStyleSheet('''
            QTableWidget {background:#A4A4A4; gridline-color:#B9BBB7; border:1px solid #8E9589; border-radius:0px;}
            QTableWidget::item {background:#FFFFFF; color:#17231F; padding:0px; border:0px;}
            QTableWidget::item:selected {background:#DCECF9; color:#17231F;}
            QHeaderView::section {background:#E9EACA; color:#18231C; border:0px; border-right:1px solid #A4AA99; border-bottom:1px solid #A4AA99; padding:4px 3px;}
            QLineEdit, QComboBox {color:#17231F; background:#FFFFFF; border:0px; border-radius:0px; padding:1px 4px; min-height:0px; min-width:0px;}
            QLineEdit:read-only {color:#283830; background:#F8F8F2;}
            QLineEdit:focus, QComboBox:focus {background:#E4F1FF; border:1px solid #2682C9; padding:0px 3px; selection-background-color:#1682C5; selection-color:white;}
            QComboBox::drop-down {border:0px; width:14px;}
            QLabel {color:#18231C; background:#F3F3E8; padding:1px 3px; border:0px;}
            QPushButton {border-radius:0px; padding:1px 3px; min-height:0px; min-width:0px;}
        ''')
        self.verticalHeader().setDefaultSectionSize(32)
        self.verticalHeader().setMinimumSectionSize(28)
        self.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)

    def setCellWidget(self, row, column, widget):
        # Editors created after the sheet must also be flat continuous cells,
        # including fields with pre-existing local padding/min-width styles.
        if isinstance(widget, (QLineEdit, QComboBox)):
            widget.setMinimumWidth(0)
            widget.setStyleSheet(widget.styleSheet()+';border:0px;border-radius:0px;padding:1px 4px;min-height:0px;min-width:0px;')
        super().setCellWidget(row, column, widget)


class TradeSheet(EntrySheet):
    def __init__(self, owner, columns):
        super().__init__(0, len(columns))
        self.owner = owner
        self.setObjectName('tradeWorksheet')
        self.setSelectionMode(self.SelectionMode.SingleSelection)

    def bind(self, row, index):
        for column, key in enumerate(self.owner.line_columns):
            field = row[key]
            self.setItem(index, column, QTableWidgetItem(''))
            field.setProperty('sheet_column', column)
            field.setProperty('sheet_row', index)
            field.installEventFilter(self)
            if isinstance(field, (QLineEdit, QComboBox)):
                field.setMinimumWidth(0)
                field.setStyleSheet('padding:1px 4px;min-width:0px;min-height:0px;border-radius:0px;')
            if key in {'total', 'base_qty'}:
                field.setStyleSheet('background:#E5E2F8;color:#142432;border:0px;border-radius:0px;padding:1px 4px;min-height:0px;min-width:0px;font-weight:600;')

    def eventFilter(self, field, event):
        if event.type() not in (QEvent.Type.FocusIn, QEvent.Type.KeyPress):
            return super().eventFilter(field,event)
        # Resolve row dynamically: deleting/moving rows must not leave stale indices.
        row = next((i for i, data in enumerate(self.owner.line_rows) if any(value is field for value in data.values())), None)
        column = field.property('sheet_column')
        if row is not None and column is not None:
            if event.type() == QEvent.Type.FocusIn:
                self.setCurrentCell(row, column)
            elif event.type() == QEvent.Type.KeyPress and not self.owner.readonly and isinstance(field, QLineEdit):
                key = event.key()
                if event.modifiers() == Qt.KeyboardModifier.NoModifier and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Up, Qt.Key.Key_Down):
                    if self.owner.line_columns[column] == 'barcode' and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                        return False  # barcode lookup keeps its existing Enter contract
                    if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                        next_row = row + (-1 if key == Qt.Key.Key_Up else 1)
                        if 0 <= next_row < len(self.owner.line_rows):
                            target = self.owner.line_rows[next_row][self.owner.line_columns[column]]
                            target.setFocus(); target.selectAll(); return True
                    else:
                        for offset in range(1, len(self.owner.line_columns)+1):
                            next_column = (column+offset) % len(self.owner.line_columns)
                            next_row = row + (column+offset)//len(self.owner.line_columns)
                            if next_row >= len(self.owner.line_rows): break
                            target = self.owner.line_rows[next_row][self.owner.line_columns[next_column]]
                            if isinstance(target, QLineEdit) and not target.isReadOnly() and target.isEnabled():
                                target.setFocus(); target.selectAll(); return True
                        return True  # Enter must not activate Save by accident
        return super().eventFilter(field, event)
