"""Original A4 commercial-paper layout shared by print, PDF and PNG output."""
from decimal import Decimal
from html import escape
from PySide6.QtCore import QRectF,QSizeF,Qt
from PySide6.QtGui import QImage,QPainter,QTextDocument
from .font_support import document_font
from .currency import round_amount


def plain(value):return escape(str(value if value is not None else ''))
def cash(value):return f'{Decimal(str(value or 0)):,.2f}'


def supplier_summary(values):
    """Use the paper's saved supplier, never a later live store profile."""
    return (f"공급자: {values.get('store_name','')} / 사업자등록번호: {values.get('business_no','')} / 대표자명: {values.get('representative','')}\n"
            f"업태: {values.get('business_type','')} / 업종: {values.get('business_category','')} / 전화번호: {values.get('phone','')}\n"
            f"주소: {values.get('address','')}")


def paper_html(record,title):
    seller=record['seller'];customer=dict(record['customer']);member=record.get('member',{})
    if member:
        for key in ('business_no','representative','address','phone'):
            if member.get(key):customer[key]=member[key]
        customer['name']=member.get('company') or customer['name']
    def party(values,supplier=False):
        fields=(('사업자번호',values.get('business_no','')),('상호',values.get('store_name') if supplier else values.get('name','')),('대표자명',values.get('representative','')),('주소',values.get('address','')),('전화번호',values.get('phone','')),('업태 / 업종',values.get('business_type','')+' / '+values.get('business_category','')))
        return '<table width="100%">'+''.join(f'<tr><th width="25%">{key}</th><td>{plain(value)}</td></tr>' for key,value in fields)+'</table>'
    lines=record['lines'];pages=[]
    taxable=sum((Decimal(str(line['total'])) for line in lines if line['tax_mode']=='taxable'),Decimal(0))
    vat=round_amount(taxable/11)
    cancelled=any(state['status']!='posted' for state in record.get('source_states',[])) or record.get('order',{}).get('status')=='cancelled'
    for offset in range(0,max(1,len(lines)),16):
        rows=[]
        for i,line in enumerate(lines[offset:offset+16],offset+1):
            unit=plain(line['unit_name'])+(f" / {line['price_basis']}g당" if line.get('price_basis')==100 else '')
            rows.append('<tr>'+''.join(f'<td>{value}</td>' for value in (str(i),plain(line.get('barcode') or line.get('product_code','')),plain(line['product_name']),plain(line.get('specification','')),unit,plain(line['qty']),cash(line['unit_price']),cash(line['total']),'과세' if line['tax_mode']=='taxable' else '면세'))+'</tr>')
        # Keep the document recognisable and usable even for a short order.
        rows.extend('<tr><td colspan="9">&nbsp;</td></tr>' for _ in range(max(0,16-len(rows))))
        order=record.get('order',{})
        warning='<p style="color:#B42318;font-weight:bold">취소된 문서 / 원판매전표 취소 — 유효 거래 자료로 사용하지 마세요.</p>' if cancelled else ''
        heading_style=' style="page-break-before:always"' if offset else ''
        pages.append(f'''<h1 align="center"{heading_style}>{plain(title)}</h1>
        {warning}<p>제의일 / 작성일: {plain(record['date'])}　　문서번호: {plain(record['number'])}<br>
        유효기간: {plain(record.get('valid_until') or '미지정')}　　배달일: {plain(order.get('delivery_date',''))}</p>
        <table width="100%"><tr><th width="50%">공 급 자</th><th width="50%">공 급 받 는 자</th></tr>
        <tr><td>{party(seller,True)}</td><td>{party(customer)}</td></tr></table><br>
        <table width="100%"><thead><tr><th>No.</th><th>코드 / 바코드</th><th>품명</th><th>규격</th><th>단위</th><th>수량</th><th>단가</th><th>금액</th><th>과면세</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
        <p align="right">이 페이지 소계: {cash(sum(Decimal(str(line['total'])) for line in lines[offset:offset+16]))} 원</p>
        <table width="100%"><tr><th>주문서 / 문서 메모</th><td colspan="3">{plain(record.get('memo','')).replace(chr(10),'<br>')}</td></tr>
        <tr><th>면세 물품가액</th><th>과세 공급가액</th><th>부가세 (포함·참고)</th><th>총 합계</th></tr>
        <tr><td>{cash(Decimal(str(record['total']))-taxable)}</td><td>{cash(taxable-vat)}</td><td>{cash(vat)}</td><td><b>{cash(record['total'])}</b></td></tr>
        <tr><th>은행명 / 예금주</th><td colspan="3">{plain(seller.get('bank',''))} / {plain(seller.get('account_holder',''))}</td></tr>
        <tr><th>계좌번호</th><td colspan="3">{plain(seller.get('account',''))}</td></tr>
        <tr><th>확인 · 검수 · 인수</th><td colspan="3">&nbsp;<br>&nbsp;</td></tr></table>
        <p>품목 묶음 {offset//16+1} / {max(1,(len(lines)+15)//16)}　　담당: {plain(order.get('assignee',''))}<br>
        배달 설명: {plain(order.get('delivery_note',''))}<br>
        가격 기준은 저장 당시 단위·100g 기준을 따릅니다. 금액은 소수점 두 자리로 표시합니다.<br>
        재고·결제 미반영 문서 / 전자세금계산서·세무 신고용 법정 서식이 아닙니다.</p>''')
    return '<html><head><style>body{color:#141414;font-size:9pt}h1{font-size:21pt}table{border-collapse:collapse}td,th{border:1px solid #444;padding:3px}th{background:#E8E8E8}p{font-size:8pt}</style></head><body>'+''.join(pages)+'</body></html>'


def paper_document(record,title):
    document=QTextDocument();document.setDefaultFont(document_font(9));document.setDocumentMargin(28)
    document.setPageSize(QSizeF(794,1123));document.setHtml(paper_html(record,title));return document


def paper_images(document):
    if document.pageCount()>100:raise ValueError('문서가 너무 큽니다. 품목을 나눠 출력하세요.')
    size=document.pageSize()
    for page in range(document.pageCount()):
        image=QImage(round(size.width()*2),round(size.height()*2),QImage.Format.Format_RGB32);image.fill(Qt.GlobalColor.white)
        image.setDotsPerMeterX(7559);image.setDotsPerMeterY(7559)
        painter=QPainter(image);painter.scale(2,2);painter.translate(0,-page*size.height())
        document.drawContents(painter,QRectF(0,page*size.height(),size.width(),size.height()));painter.end();yield image
