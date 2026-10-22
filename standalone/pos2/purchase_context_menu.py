"""Product right-click commands backed only by existing working operations."""
from PySide6.QtWidgets import QApplication, QMenu, QInputDialog, QLineEdit


HELP={
    '상품검색 (F5)':'상품명·바코드로 검색해 품목을 추가합니다. Space로 추가한 뒤 검색창을 계속 사용할 수 있습니다.',
    '엑셀 붙여넣기 (Ctrl+V)':'엑셀 제목 행과 품목을 복사해 검토 후 추가합니다. 바코드·수량·매입단가·판매단가 4열도 지원합니다.',
    '인쇄(그리드)':'현재 전표 품목을 표 형식으로 인쇄 미리보기 합니다. 장부에는 반영하지 않습니다.',
    '인쇄(출력양식)':'현재 전표를 매입전표 양식으로 인쇄 미리보기 합니다. 장부에는 반영하지 않습니다.',
    '엑셀저장':'현재 전표 한 건을 XLSX 파일로 저장합니다. 저장된 전표나 작성 중인 입력을 사용합니다.',
    '상품 등록정보 (F8)':'선택 상품의 현재 등록정보를 확인합니다. 과거 전표 기록을 바꾸지 않습니다.',
    '부가정보 · 가격 이력 (F11)':'선택 상품의 확정 매입 가격 이력을 오른쪽에 표시하거나 숨깁니다.',
    '매입수정 (F6)':'선택한 품목의 수량 입력칸으로 이동합니다. 최종 저장 전에는 장부가 바뀌지 않습니다.',
    '수량·매입단가 일괄입력':'작성 중인 품목의 수량·단가를 일괄 입력합니다. 검토 후 적용하세요.',
    '선택행 메모 입력':'선택한 한 품목의 메모를 입력합니다. 최종 저장 시 전표와 함께 보존됩니다.',
    '선택행 삭제 (F7)':'선택한 한 품목을 작성 중인 표에서 삭제합니다. 최종 저장 전에는 장부가 바뀌지 않습니다.',
    '과면세 정보':'현재 전표의 품목별 과세·면세 구분과 금액을 확인합니다.',
}


def build_menu(trade):
    menu=QMenu(trade);menu._sy_submenus=[];menu.setToolTipsVisible(True)
    row=trade.table.currentRow()
    selected=trade.line_rows[row] if 0<=row<len(trade.line_rows) else None
    has_product=bool(selected and selected['product'].currentData())
    printable=any(r['product'].currentData() for r in trade.line_rows) or bool(trade.record and trade.record['status']=='posted')
    mutable=not trade.readonly and (not trade.amending or trade.amend_context['stock_editable'])
    def add(text,callback,enabled=True):
        command=menu.addAction(text,callback);command.setEnabled(enabled)
        if text in HELP:command.setToolTip(HELP[text])
        return command
    from .menu_icons import menu_icon
    compact=add('줄여보기',lambda:trade.purchase_view.set_view('compact'))
    compact.setIcon(menu_icon('back'));compact.setToolTip('기본 15개 열을 모두 표시하고 추가 상세 열만 숨깁니다. 입력값과 장부는 바뀌지 않습니다.')
    expanded=add('펼쳐보기',lambda:trade.purchase_view.set_view('expanded'))
    expanded.setIcon(menu_icon('forward'));expanded.setToolTip('기준가·할인·공급가액·보증금·이익 열을 추가합니다. 저장 근거가 없는 값은 미기록으로 표시합니다.')
    menu.addSeparator()
    add('상품검색 (F5)',trade.pick_product,mutable and trade.kind=='purchase')
    def paste():
        from .purchase_clipboard import paste_purchase
        paste_purchase(trade)
    add('엑셀 붙여넣기 (Ctrl+V)',paste,mutable and trade.kind=='purchase')
    menu.addSeparator()
    add('인쇄(그리드)',trade.print_grid,printable)
    add('인쇄(출력양식)',trade.print_document,printable)
    add('엑셀저장',trade.export_document,printable);menu.addSeparator()
    add('상품 등록정보 (F8)',trade.product_info,has_product)
    history=add('부가정보 · 가격 이력 (F11)',trade.tax_info,has_product)
    history.setCheckable(True);history.setChecked(trade.price_panel.enabled)
    menu.addSeparator()
    add('매입수정 (F6)',trade.edit_selected_line,has_product and mutable)
    move=menu.addMenu('상품 순서이동')
    move.setToolTipsVisible(True)
    move.menuAction().setToolTip('선택 품목을 위·아래로 한 칸 이동합니다. 입력한 수량·가격·메모를 함께 옮깁니다.')
    menu._sy_submenus.append(move)
    up=move.addAction('위로',lambda:trade.move_line(-1));up.setEnabled(mutable and row>0)
    down=move.addAction('아래로',lambda:trade.move_line(1));down.setEnabled(mutable and 0<=row<len(trade.line_rows)-1)
    up.setToolTip('선택 품목을 한 줄 위로 옮깁니다. 첫 번째 줄에서는 사용할 수 없습니다.')
    down.setToolTip('선택 품목을 한 줄 아래로 옮깁니다. 마지막 줄에서는 사용할 수 없습니다.')
    add('수량·매입단가 일괄입력',trade.bulk_edit_lines,mutable and has_product)
    def memo():
        if not mutable or selected not in trade.line_rows:return
        text,accepted=QInputDialog.getText(trade,'선택행 메모 입력','메모',text=selected['line_memo'].text())
        if accepted:selected['line_memo'].setText(text)
    add('선택행 메모 입력',memo,mutable and has_product)
    add('선택행 삭제 (F7)',trade.remove_selected_line,mutable and selected is not None)
    menu.addSeparator()
    add('과면세 정보',trade.show_tax_info,has_product)
    trade.purchase_view.column_menu(menu)
    # Standard text-edit commands remain reachable inside an editable cell.
    column=trade.table.currentColumn()
    field=selected.get(trade.line_columns[column]) if selected and 0<=column<len(trade.line_columns) else None
    if isinstance(field,QLineEdit):
        editor=field.createStandardContextMenu();editor.setTitle('셀 편집');editor.setParent(menu,editor.windowFlags());menu.addMenu(editor)
        menu._sy_submenus.append(editor)
        cell_mutable=not trade.readonly and field.isEnabled() and not field.isReadOnly()
        for command in editor.actions():
            if command.objectName() in {'edit-undo','edit-redo','edit-cut','edit-paste','edit-delete'}:
                command.setEnabled(command.isEnabled() and cell_mutable)
        # A native QAction invokes QLineEdit.paste() without sending Ctrl+V to
        # TradeSheet. Route tabular clipboard values through the same reviewed
        # transaction instead of putting a whole worksheet into one number cell.
        paste_command=next((a for a in editor.actions() if a.objectName()=='edit-paste'),None)
        if paste_command is not None:
            paste_command.triggered.disconnect()
            def paste_cell():
                if trade.readonly or field.isReadOnly() or not field.isEnabled():return
                value=QApplication.clipboard().text()
                if '\t' in value or '\n' in value:paste()
                else:field.paste()
            paste_command.triggered.connect(paste_cell)
            paste_command.setToolTip('숫자·문자는 이 셀에 붙여넣고, 엑셀 표는 검토 후 품목으로 추가합니다.')
        editor.setToolTipsVisible(True)
        editor.menuAction().setToolTip('우클릭한 셀의 실행 취소·복사·붙여넣기 등을 사용합니다.')
    # PySide 6.8 can transfer ownership of a submenu's menuAction wrapper.
    # Retain it when actions() is queried/decorated so the submenu stays alive.
    menu._sy_actions=menu.actions()
    return menu
