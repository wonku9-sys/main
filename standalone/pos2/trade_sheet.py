"""One continuous worksheet, without nested rounded input cards in each cell."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QTableWidgetItem
from shiboken6 import isValid
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
            QComboBox[syPickerOnly="true"]::drop-down {width:0px; border:0px;}
            QComboBox[syPickerOnly="true"]::down-arrow {image:none; width:0px;}
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
        self.purchase_layout = owner.kind.startswith('purchase')
        self.selection_scope = 'cell'; self._setting_selection = False; self._painted_fields = []
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)
        if self.purchase_layout:
            self.viewport().installEventFilter(self)
            self.verticalHeader().setStyleSheet('QHeaderView::section {background:#EEEFCF;color:#17231F;border:1px solid #B9BBB7;}')
            self.currentCellChanged.connect(self._current_changed)
            self.verticalHeader().sectionClicked.connect(lambda row:self.choose_row(row))
            for header in (self.horizontalHeader(),self.verticalHeader()):
                header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                header.viewport().installEventFilter(self)
                header.customContextMenuRequested.connect(lambda point,source=header:self.header_menu(source,point))

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
            if self.purchase_layout and column<2:
                field.setStyleSheet(field.styleSheet()+';background:#EEEFCF;color:#17231F;')

    def choose_row(self, row):
        if not 0<=row<len(self.owner.line_rows):return
        self._setting_selection=True
        try:
            self.selection_scope='row';self.setCurrentCell(row,0);self.selectRow(row)
        finally:self._setting_selection=False
        self.paint_selection()

    def choose_cell(self,row,column):
        self._setting_selection=True
        try:
            self.selection_scope='cell';self.clearSelection();self.setCurrentCell(row,column)
        finally:self._setting_selection=False
        self.paint_selection()

    def _current_changed(self,row,column,*_):
        if not self._setting_selection:
            self.selection_scope='row' if column<2 else 'cell'
            self.paint_selection()

    def paint_selection(self):
        if not self.purchase_layout:return
        suffix=';background:#087FD3;color:#FFFFFF;selection-background-color:#005A9E;selection-color:#FFFFFF;'
        for field,base in self._painted_fields:
            if isValid(field) and field.styleSheet()==base+suffix:field.setStyleSheet(base)
        self._painted_fields=[]
        index=self.currentRow()
        if not 0<=index<len(self.owner.line_rows):return
        row=self.owner.line_rows[index]
        columns=range(2,len(self.owner.line_columns)) if self.selection_scope=='row' else (self.currentColumn(),)
        for column in columns:
            if column<2:continue
            field=row[self.owner.line_columns[column]];base=field.styleSheet()
            field.setStyleSheet(base+suffix);self._painted_fields.append((field,base))

    def header_menu(self,header,point):
        vertical=header is self.verticalHeader()
        row=header.logicalIndexAt(point) if vertical else self.currentRow()
        self.show_product_menu(row,header.viewport().mapToGlobal(point),0 if vertical and row>=0 else None)

    def show_product_menu(self,row,position,column=None):
        if not self.purchase_layout:return
        if 0<=row<len(self.owner.line_rows):
            if column is not None:
                if column<2:self.choose_row(row)
                else:self.choose_cell(row,column)
            elif row!=self.currentRow():self.choose_row(row)
        from .purchase_context_menu import build_menu
        previous=getattr(self,'_product_menu',None)
        if previous is not None and isValid(previous):previous.close();previous.deleteLater()
        self._product_menu=build_menu(self.owner)
        self._product_menu.popup(position)

    def contextMenuEvent(self,event):
        if self.purchase_layout:
            index=self.indexAt(event.pos())
            self.show_product_menu(index.row() if index.isValid() else self.currentRow(),event.globalPos(),index.column() if index.isValid() else None)
            event.accept();return
        super().contextMenuEvent(event)

    def paste_excel(self,event):
        if self.purchase_layout and event.matches(QKeySequence.StandardKey.Paste):
            value=QApplication.clipboard().text()
            if '\t' in value or '\n' in value:
                from .purchase_clipboard import paste_purchase
                paste_purchase(self.owner);event.accept();return True
        return False

    def keyPressEvent(self,event):
        if self.paste_excel(event):return
        super().keyPressEvent(event)

    def eventFilter(self, field, event):
        if event.type() not in (QEvent.Type.FocusIn, QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.ContextMenu):
            return super().eventFilter(field,event)
        # Open on the real mouse press as well as keyboard/native context
        # events. This includes the gray viewport before any product is added.
        if self.purchase_layout and event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.RightButton:
            for header in (self.horizontalHeader(),self.verticalHeader()):
                if field is header.viewport():
                    self.header_menu(header,event.position().toPoint());return True
            if field is self.viewport():
                index=self.indexAt(event.position().toPoint())
                self.show_product_menu(index.row() if index.isValid() else self.currentRow(),event.globalPosition().toPoint(),index.column() if index.isValid() else None)
                return True
            row=next((i for i,data in enumerate(self.owner.line_rows) if any(value is field for value in data.values())),None)
            if row is not None:
                self.show_product_menu(row,event.globalPosition().toPoint(),field.property('sheet_column'));return True
        # Resolve row dynamically: deleting/moving rows must not leave stale indices.
        row = next((i for i, data in enumerate(self.owner.line_rows) if any(value is field for value in data.values())), None)
        column = field.property('sheet_column')
        if row is not None and column is not None:
            if event.type()==QEvent.Type.KeyPress and self.paste_excel(event):return True
            if self.purchase_layout and event.type()==QEvent.Type.ContextMenu:
                self.show_product_menu(row,event.globalPos(),column);return True
            if self.purchase_layout and event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton:
                if column<2 and self.owner.line_rows[row]['product'].currentData():
                    self.choose_row(row);self.setFocus();return True
                self.choose_cell(row,column)
            if event.type() == QEvent.Type.FocusIn:
                if self.purchase_layout:self.choose_cell(row,column) if column>=2 else self.choose_row(row)
                else:self.setCurrentCell(row, column)
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
