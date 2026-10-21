"""Thousands grouping for numeric fields only; no rounding or value conversion."""
import re
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLineEdit


def grouped_number(value):
    raw=str(value).replace(',','')
    if not re.fullmatch(r'[+-]?\d*(?:\.\d*)?',raw):return str(value)
    sign=raw[:1] if raw[:1] in ('+','-') else ''
    body=raw[len(sign):];integer,point,fraction=body.partition('.')
    groups=[]
    while integer:
        groups.append(integer[-3:]);integer=integer[:-3]
    return sign+','.join(reversed(groups))+point+fraction


class GroupedNumberEdit(QLineEdit):
    """Live grouping with stable cursor, decimals and bounded keyboard undo."""
    def __init__(self,value='',parent=None):
        super().__init__(grouped_number(value),parent)
        self._undo_states=[];self._redo_states=[];self._restoring=False
        self._last_state=self._snapshot()
        self.textEdited.connect(self._edited)
        self.cursorPositionChanged.connect(self._cursor_changed)

    def _snapshot(self):
        return self.text(),self.cursorPosition(),self.selectionStart(),len(self.selectedText())

    def _cursor_changed(self,*_):
        if self.text()==self._last_state[0]:self._last_state=self._snapshot()

    def setText(self,value):
        value=grouped_number(value)
        if value==self.text():return
        super().setText(value)
        if hasattr(self,'_undo_states') and not self._restoring:
            self._undo_states.clear();self._redo_states.clear();self._last_state=self._snapshot()

    def _edited(self,*_):
        if self._restoring:return
        self._undo_states.append(self._last_state);self._undo_states=self._undo_states[-100:]
        self._redo_states.clear()
        old=self.text();cursor=self.cursorPosition();formatted=grouped_number(old)
        if formatted!=old:
            logical=sum(c!=',' for c in old[:cursor]);position=0;seen=0
            while position<len(formatted) and seen<logical:
                if formatted[position]!=',':seen+=1
                position+=1
            blocked=self.blockSignals(True)
            QLineEdit.setText(self,formatted);self.setCursorPosition(position)
            self.blockSignals(blocked)
        self._last_state=self._snapshot()

    def _restore(self,source,destination):
        if self.isReadOnly() or not source:return
        destination.append(self._snapshot());value,cursor,start,length=source.pop()
        self._restoring=True
        try:
            QLineEdit.setText(self,value);self.setCursorPosition(cursor)
            if start>=0 and length:self.setSelection(start,length)
            self.textEdited.emit(value)
        finally:self._restoring=False;self._last_state=self._snapshot()

    def undo(self):self._restore(self._undo_states,self._redo_states)
    def redo(self):self._restore(self._redo_states,self._undo_states)

    def keyPressEvent(self,event):
        if event.matches(QKeySequence.StandardKey.Undo):self.undo();event.accept();return
        if event.matches(QKeySequence.StandardKey.Redo):self.redo();event.accept();return
        self._last_state=self._snapshot()
        if not self.hasSelectedText():
            cursor=self.cursorPosition()
            if event.key()==Qt.Key.Key_Backspace and cursor and self.text()[cursor-1:cursor]==',':self.setCursorPosition(cursor-1)
            elif event.key()==Qt.Key.Key_Delete and self.text()[cursor:cursor+1]==',':self.setCursorPosition(cursor+1)
        super().keyPressEvent(event)
