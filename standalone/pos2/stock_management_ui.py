"""Opening stock, disposal and dated inventory asset movements."""
from datetime import date
from decimal import Decimal
from uuid import uuid4
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout,QLabel,QMessageBox,QComboBox,QTabWidget
from .widgets import Page,FormDialog,DataGrid,action,date_field,won


class StockAdjustmentPage(Page):
    def __init__(self,window,kind):
        self.kind=kind
        super().__init__(window,'기초재고 등록' if kind=='opening' else '재고 폐기','확정하면 재고에 즉시 반영합니다. 매입/판매 금액이나 거래처 결제에는 반영하지 않습니다.')
        self.actions.addWidget(action('기초재고 입력' if kind=='opening' else '폐기 기록',self.add,primary=True))
        self.grid=self.table(['일자','상품코드','상품명','수량','단위','재고 원가액','처리 사유','담당자','등록 일시'])
        note=QLabel('기초재고는 재고이동이 없는 상품에 1회 등록합니다. g 상품은 g 수량과 상품장의 100g 단가 기준을 사용합니다.' if kind=='opening' else '현재고를 초과한 폐기는 불가합니다. 현재 이동평균 원가로 차감하며 매입반품·판매반품과 별개입니다.')
        note.setWordWrap(True);self.body.addWidget(note)
        self.body.addWidget(QLabel('확정 이력은 수정·삭제하지 않습니다. 잘못 기록한 수량은 ‘재고실사 입력 · 적용’에서 사유를 남기고 조정하세요.'))
    def refresh(self):
        rows=self.store.stock_adjustments(self.kind)
        self.grid.fill([[r['date'],r['code'],r['product_name'],Decimal(r['qty']),r['base_unit'],r['stock_cost'],r['reason'],r['user_name'],r['created_at']] for r in rows],rows)
    def add(self):
        try:products=[r for r in self.store.products(active_only=True) if r['tracked']]
        except (ValueError,PermissionError) as exc:self.fail(exc);return
        picker=FormDialog('재고 상품 선택',self);picker.resize(750,320)
        choices=[(r['code']+' · '+r['name']+' · '+r['barcode']+' · '+r['specification'],r['id']) for r in products]
        choice=picker.combo('product','상품코드 · 바코드 · 상품명 · 규격 검색',choices);choice.setEditable(True);choice.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        choice.completer().setFilterMode(Qt.MatchFlag.MatchContains);choice.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        selected={}
        def choose():
            if choice.currentIndex()<0 or choice.currentText()!=choice.itemText(choice.currentIndex()):picker.error('검색 결과에서 상품을 선택하세요.');return
            selected['product']=next((r for r in products if r['id']==choice.currentData()),None)
            if selected['product'] is not None:picker.accept()
        picker.finish(choose)
        if picker.exec() and selected.get('product'):self.editor(selected['product'])
        picker.deleteLater()
    def editor(self,product):
        dialog=FormDialog('기초재고 입력' if self.kind=='opening' else '재고 폐기 기록',self)
        dialog.body.insertWidget(1,QLabel(product['code']+' · '+product['name']))
        when=date_field();dialog.form.addRow('기준일' if self.kind=='opening' else '폐기일',when)
        quantity=dialog.field('qty',f"{'기초' if self.kind=='opening' else '폐기'} 수량 ({product['base_unit']})")
        price=dialog.field('price',f"단가 (원 / {product.get('price_basis',1)}{product['base_unit']})",product['purchase_price'])
        price.setVisible(self.kind=='opening');dialog.form.labelForField(price).setVisible(self.kind=='opening')
        reason=dialog.field('reason','사유 *','기초재고 등록' if self.kind=='opening' else '')
        request_key=uuid4().hex
        def save():
            if QMessageBox.question(dialog,'재고 반영 확인','입력한 수량을 재고에 반영할까요?\n확정 이력은 보존하며 재고자산 원가가 변경됩니다.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            try:
                self.store.post_stock_adjustment({'kind':self.kind,'product_id':product['id'],'date':when.date().toString('yyyy-MM-dd'),'qty':quantity.text(),'unit_price':price.text() if self.kind=='opening' else '0','reason':reason.text()},request_key)
                dialog.accept();self.refresh()
            except (ValueError,PermissionError,OSError) as exc:dialog.error(exc)
        dialog.finish(save);dialog.exec();dialog.deleteLater()


class InventoryAssetsPage(Page):
    def __init__(self,window):
        super().__init__(window,'재고자산 현황','재고이동 기록일 기준의 수량 증감·보유 원가입니다. 현금·예금·채권 등을 합친 전체 자산/재무제표가 아닙니다.')
        row=QHBoxLayout();self.start=date_field(date.today().replace(day=1));self.end=date_field();row.addWidget(self.start);row.addWidget(QLabel('~'));row.addWidget(self.end);row.addWidget(action('조회',self.refresh));row.addStretch();self.body.addLayout(row)
        self.summary=QLabel();self.summary.setWordWrap(True);self.summary.setObjectName('notice');self.body.addWidget(self.summary)
        from .household_finance_ui import MoneyChart
        charts=QHBoxLayout();self.pie=MoneyChart('pie',title='분류별 재고자산 비율');self.bar=MoneyChart('bar',title='7일 전 · 한 달 전 재고자산 비교',keep_order=True)
        charts.addWidget(self.pie);charts.addWidget(self.bar);self.body.addLayout(charts)
        self.trend=MoneyChart('bar',title='최근 날짜별 재고 원가 추이 · 8개 기준일',keep_order=True);self.body.addWidget(self.trend)
        self.category_grid=self.table(['분류','기준일 재고자산','7일 전','주간 증감액','증감률','한 달 전','월간 증감액','증감률'])
        self.category_grid.setMinimumHeight(150)
        self.grid=self.table(['상품코드','상품명','단위','기초수량','매입입고 +','매입반품 −','판매출고 −','판매반품 +','폐기 −','기초등록/실사/취소 증감','기말수량','기초 원가액','기말 재고자산','공급사','분류'])
        self.body.addWidget(QLabel('기말 = 기초 + 매입 − 매입반품 − 판매 + 판매반품 − 폐기 + 조정. 단위가 다른 수량은 합산하지 않습니다. 판매예정가가 아닌 이동평균 보유 원가입니다.'))
    def refresh(self):
        report=self.store.inventory_assets(self.start.date().toString('yyyy-MM-dd'),self.end.date().toString('yyyy-MM-dd'))
        self.grid.fill([[r['code'],r['name'],r['base_unit'],*[Decimal(r[key]) for key in ('opening_qty','purchase_qty','purchase_return_qty','sale_qty','sale_return_qty','waste_qty','adjustment_qty','closing_qty')],r['opening_cost'],r['stock_cost'],r['supplier_name'] or '',r['category']] for r in report['rows']],report['rows'])
        self.summary.setText(f"기초 재고자산 {won(report['totals']['opening_cost'])}원  →  기말 재고자산 {won(report['totals']['stock_cost'])}원 · {len(report['rows'])}개 상품")
        comparison=self.store.inventory_asset_comparison(self.end.date().toString('yyyy-MM-dd'))
        rate=lambda value:'기준 없음' if value is None else f'{value:+.1f}%'
        self.category_grid.fill([[r['category'],r['stock_cost'],r['week_cost'],r['change_week'],rate(r['week_rate']),r['month_cost'],r['change_month'],rate(r['month_rate'])] for r in comparison['rows']],comparison['rows'])
        self.pie.set_values([(r['category'],r['stock_cost']) for r in comparison['rows'] if r['stock_cost']>0])
        totals=comparison['totals'];self.bar.set_values([('한 달 전',totals['month_cost']),('7일 전',totals['week_cost']),('기준일',totals['stock_cost'])])
        timeline=comparison['timeline'];indices=sorted({round(i*(len(timeline)-1)/7) for i in range(8)}) if timeline else []
        self.trend.set_values([(timeline[i]['date'][5:],timeline[i]['stock_cost']) for i in indices])
        self.summary.setText(self.summary.text()+f"\n비교 기준: {comparison['week_date']} / {comparison['month_date']} · 최초 재고기록: {comparison['first_record'] or '없음'}. 기록 이전의 자산은 알 수 없으며 금액 0으로 표시하고 증가율은 산출하지 않습니다.")
