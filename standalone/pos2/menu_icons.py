"""Offline 3D menu artwork, cached per family; vector fallback for recovery."""
from functools import lru_cache
from pathlib import Path
import math
from PySide6.QtCore import Qt,QPointF,QRectF
from PySide6.QtGui import QColor,QFont,QIcon,QImage,QPainter,QPainterPath,QPen,QPixmap,QPolygonF

ATLAS=Path(__file__).resolve().parent/'assets'/'menu-icons-3d.png'
ATLAS_SHA256='91096d5d54212a57301f6645f0b85d79152e5bd87397e55552b21356525933e8'
PAYMENT_ATLAS=ATLAS.with_name('payment-icons-real3d.png')
PAYMENT_KEYS=('back','forward','payables','supplier','purchase_payment','bill','receivables','member','sales_payment','ledger','profit','connection','update','remote','printer','excel')


@lru_cache(maxsize=16)
def payment_icon(kind):
    """Full-cell, alpha-safe financial artwork; fixed transparent guard band."""
    image=QImage(str(PAYMENT_ATLAS))
    if image.isNull() or kind not in PAYMENT_KEYS:return menu_icon(kind)
    index=PAYMENT_KEYS.index(kind);w,h=image.width()/4,image.height()/4
    return _fitted_icon(image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied),QRectF(index%4*w,index//4*h,w,h))
OUTPUT_ATLAS=ATLAS.with_name('output-icons-real3d.png')
OUTPUT_KEYS=('printer','excel')
OUTPUT_ATLAS_SHA256='8bd686fc3d8ce4c4b320e0043932f4509911b375f7a19943b155a5dd84aec3ad'
# Explicit source rectangles keep the generated objects complete, not split at
# the image midpoint. The printer is wider than the upright workbook.
OUTPUT_RECTS=((65,68,875,754),(1036,80,686,764))
PERSONAL_ASSETS={
    'diary':ATLAS.with_name('diary-real3d.png'),
    'wallet':ATLAS.with_name('household-real3d.png'),
}
PERSONAL_SHA256={
    'diary':'9d2ff763c241049c97b2a56023cded5d741a1dde8d582f0a3c67a3a658bd8652',
    'wallet':'f420969d5b66b95105998e941a56cc1f4746b611c900c2776a6e5d398d8bc74c',
}
ATLAS_KEYS=('back','forward','home','calendar','product','purchase',
            'sale','report','user','money','printer','excel',
            'scan','truck','inventory','category','settings','search',
            'add','edit','waste','diary','wallet','worklog',
            'lucky','goal','card','transfer','backup','info')


@lru_cache(maxsize=1)
def _atlas_image():
    image=QImage(str(ATLAS))
    if image.isNull() or image.width()%6 or image.height()%5 or image.width()//6!=image.height()//5:return None
    # Scale and composite premultiplied alpha, so transparent edge pixels do
    # not introduce a pale matte when displayed on different seasonal skins.
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


@lru_cache(maxsize=1)
def _output_atlas_image():
    """Dedicated large-object output artwork, with the original atlas as fallback."""
    image=QImage(str(OUTPUT_ATLAS))
    if image.isNull() or not image.hasAlphaChannel() or image.width()!=1774 or image.height()!=887:return None
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


@lru_cache(maxsize=2)
def _personal_image(kind):
    image=QImage(str(PERSONAL_ASSETS[kind]))
    if image.isNull() or not image.hasAlphaChannel() or image.width()!=image.height():return None
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def _fitted_icon(image,source):
    """Preserve proportions and a transparent guard without changing artwork."""
    scale=min(120/source.width(),120/source.height())
    width,height=source.width()*scale,source.height()*scale
    pix=QPixmap(128,128);pix.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pix);painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(QRectF((128-width)/2,(128-height)/2,width,height),image,source);painter.end()
    return QIcon(pix)


def family(key):
    if key in {'back','이전'}:return 'back'
    if key in {'forward','다음'}:return 'forward'
    if '카드' in key:return 'card'
    if '이체' in key or key=='transfer':return 'transfer'
    if '정정' in key:return 'edit'
    if '결제 취소' in key:return 'waste'
    if key=='backup' or '백업' in key:return 'backup'
    if key=='info' or '도움말' in key:return 'info'
    if '엑셀' in key or key=='excel':return 'excel'
    if '인쇄' in key or key=='printer':return 'printer'
    if '스캔' in key or key=='scan':return 'scan'
    if key=='lucky_numbers' or '행운' in key or '추첨' in key:return 'lucky'
    if key=='goal' or '목표' in key or '예산' in key:return 'goal'
    if key=='calendar' or '달력' in key or '일정' in key:return 'calendar'
    if key=='home' or '첫화면' in key:return 'home'
    if 'waste' in key or any(x in key for x in ('삭제','폐기','무효')):return 'waste'
    if 'category' in key or 'categories' in key or '분류' in key:return 'category'
    if key=='products' or '상품' in key or key=='labels':return 'product'
    if key=='diary' or '일기' in key:return 'diary'
    if key in {'household','wallet'} or '가계부' in key:return 'wallet'
    if key=='worklog' or '일지' in key:return 'worklog'
    if 'supplier' in key or '공급사' in key:return 'truck'
    if key in {'payments','ledger','commission'} or any(x in key for x in ('결제','수수료','잔액')):return 'money'
    if any(x in key for x in ('inventory','stock','counts','재고','실사')):return 'inventory'
    if 'purchase' in key or '매입' in key:return 'purchase'
    if 'sale' in key or '판매' in key:return 'sale'
    if key in {'users','permissions','user_access','members','customers'} or 'member' in key or any(x in key for x in ('회원','직원','권한')):return 'user'
    if key=='settings' or any(x in key for x in ('설정','환경','암호')):return 'settings'
    if any(x in key for x in ('추가','새 ','등록','기록')):return 'add'
    if any(x in key for x in ('수정','편집')):return 'edit'
    if any(x in key for x in ('조회','검색','찾기')):return 'search'
    return 'report'


def menu_icon(key):
    from .hover_effects import normal_menu_icon
    return normal_menu_icon(family(key))


@lru_cache(maxsize=32)
def _family_icon(kind):
    if kind in PERSONAL_ASSETS:
        image=_personal_image(kind)
        if image is not None:return _fitted_icon(image,QRectF(image.rect()))
    if kind in OUTPUT_KEYS:
        output=_output_atlas_image()
        if output is not None:
            source=QRectF(*OUTPUT_RECTS[OUTPUT_KEYS.index(kind)])
            return _fitted_icon(output,source)
    atlas=_atlas_image()
    if atlas is not None and kind in ATLAS_KEYS:
        index=ATLAS_KEYS.index(kind);edge=atlas.width()//6
        pix=QPixmap(128,128);pix.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pix);painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRectF(0,0,128,128),atlas,QRectF(index%6*edge,index//6*edge,edge,edge));painter.end()
        return QIcon(pix)
    pix=QPixmap(64,64);pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.scale(2,2)
    ink='#A75C59' if kind=='waste' else '#4D6B9B' if kind in {'sale','user','search'} else '#2E6B56'
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#F8E9E5' if kind=='waste' else '#ECF1F8' if ink=='#4D6B9B' else '#E7F0E9'));p.drawRoundedRect(QRectF(1,1,30,30),7,7)
    p.setPen(QPen(QColor(ink),1.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));p.setBrush(Qt.BrushStyle.NoBrush)
    if kind in {'back','forward'}:
        p.setPen(QPen(QColor('#517BA3'),1.2));p.setBrush(QColor('#CEE8F8'));p.drawEllipse(QRectF(3,3,26,26))
        points=[QPointF(8,16),QPointF(17,8),QPointF(17,13),QPointF(24,13),QPointF(24,19),QPointF(17,19),QPointF(17,24)]
        if kind=='forward':points=[QPointF(32-point.x(),point.y()) for point in points]
        p.setBrush(QColor('#FFFFFF'));p.drawPolygon(QPolygonF(points))
    elif kind=='lucky':
        p.drawEllipse(QRectF(6,4,20,20));p.drawRoundedRect(QRectF(9,24,14,4),1,1)
        for x,y in ((12,11),(21,12),(16,19)):p.setBrush(QColor('#B7A16A'));p.drawEllipse(QRectF(x-2,y-2,4,4))
    elif kind=='goal':
        p.drawEllipse(QRectF(5,5,22,22));p.drawEllipse(QRectF(10,10,12,12));p.drawLine(16,16,27,5);p.drawLine(21,5,27,5);p.drawLine(27,5,27,11)
    elif kind=='calendar':
        p.drawRoundedRect(QRectF(6,7,20,20),2,2);p.drawLine(6,13,26,13);p.drawLine(11,5,11,10);p.drawLine(21,5,21,10)
        for x in (11,16,21):
            for y in (18,23):p.drawPoint(x,y)
    elif kind=='home':
        p.setBrush(QColor('#FCFEFC'));p.drawRoundedRect(QRectF(7,11,18,13),2,2)
        p.setBrush(QColor('#548B76'));p.drawPolygon(QPolygonF([QPointF(4,13),QPointF(16,3),QPointF(28,13)]))
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#D7AF5D'));p.drawRoundedRect(QRectF(13,15,6,9),1,1)
        p.setBrush(QColor('#BFD9E6'));p.drawRoundedRect(QRectF(9,15,3,4),.6,.6);p.drawRoundedRect(QRectF(20,15,3,4),.6,.6)
        p.setPen(QColor('#285747'));font=QFont();font.setPixelSize(7);font.setBold(True);p.setFont(font)
        p.drawText(QRectF(2,24,28,8),Qt.AlignmentFlag.AlignCenter,'Home')
    elif kind in {'product','inventory'}:
        p.setBrush(QColor('#E4C58B'));p.drawPolygon(QPolygonF([QPointF(5,13),QPointF(16,8),QPointF(27,13),QPointF(27,25),QPointF(16,29),QPointF(5,25)]))
        p.setBrush(QColor('#F8E8C6'));p.drawPolygon(QPolygonF([QPointF(5,13),QPointF(16,17),QPointF(27,13),QPointF(16,8)]))
        p.drawLine(16,17,16,29);p.drawLine(10,11,21,15)
        if kind=='product':
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#E78B7D'));p.drawEllipse(QRectF(7,6,9,8))
            p.setBrush(QColor('#83AD81'));p.drawEllipse(QRectF(11,3,5,4));p.setBrush(QColor('#F6F9F2'));p.drawRoundedRect(QRectF(18,5,6,8),1,1)
            p.setBrush(QColor('#7798B9'));p.drawRect(QRectF(18,8,6,2));p.setPen(QPen(QColor(ink),1.4));p.drawArc(QRectF(7,19,7,4),185*16,160*16)
    elif kind=='purchase':
        p.setBrush(QColor('#FFFDF7'));p.drawRoundedRect(QRectF(6,4,19,24),2,2)
        p.setPen(QPen(QColor('#A8B8AC'),1.2));p.drawLine(10,10,20,10);p.drawLine(10,15,19,15);p.drawLine(10,20,16,20)
        p.setPen(QPen(QColor('#7B6A4C'),1));p.setBrush(QColor('#D9B269'))
        p.drawPolygon(QPolygonF([QPointF(17,25),QPointF(19,19),QPointF(27,7),QPointF(30,10),QPointF(22,22)]))
        p.setBrush(QColor('#486E5D'));p.drawPolygon(QPolygonF([QPointF(17,25),QPointF(19,19),QPointF(22,22)]))
    elif kind=='excel':
        p.setBrush(QColor('#F9FEFA'));p.drawRoundedRect(QRectF(9,4,19,24),2,2)
        p.setPen(QPen(QColor('#9BBCA9'),.9))
        for y in (10,15,20,25):p.drawLine(14,y,25,y)
        for x in (15,20,25):p.drawLine(x,8,x,25)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#3A805F'));p.drawRoundedRect(QRectF(3,10,14,15),2,2)
        p.setPen(QPen(QColor('#FFFFFF'),1.8));p.drawLine(7,14,13,21);p.drawLine(13,14,7,21)
    elif kind=='printer':
        p.setBrush(QColor('#FFFFFF'));p.drawRect(QRectF(10,3,12,9));p.setBrush(QColor('#AEC6BE'));p.drawRoundedRect(QRectF(5,11,22,13),3,3)
        p.setBrush(QColor('#FFFFFF'));p.drawRoundedRect(QRectF(10,19,12,10),1,1);p.setPen(QPen(QColor('#648B7C'),1));p.drawLine(13,23,19,23);p.drawLine(13,26,19,26)
        p.setBrush(QColor('#D6AD58'));p.drawEllipse(QRectF(22,14,2,2))
    elif kind=='scan':
        p.setPen(QPen(QColor('#466B84'),1.7))
        for x in (7,10,12,16,19,23,25):p.drawLine(x,8,x,24)
        p.setPen(QPen(QColor('#DB826E'),2));p.drawLine(3,16,29,16)
        p.setPen(QPen(QColor('#4B886B'),1.8));p.drawPolyline(QPolygonF([QPointF(3,9),QPointF(3,4),QPointF(9,4)]));p.drawPolyline(QPolygonF([QPointF(23,28),QPointF(29,28),QPointF(29,23)]))
    elif kind=='category':
        p.drawRoundedRect(QRectF(5,6,11,7),2,2);p.drawLine(10,13,10,25);p.drawLine(10,18,17,18);p.drawLine(10,25,17,25);p.drawRoundedRect(QRectF(17,15,10,6),1,1);p.drawRoundedRect(QRectF(17,23,10,5),1,1)
    elif kind=='waste':
        p.drawLine(7,10,25,10);p.drawRoundedRect(QRectF(10,10,12,17),2,2);p.drawLine(13,6,19,6);p.drawLine(13,6,12,10);p.drawLine(19,6,20,10);p.drawLine(14,15,14,23);p.drawLine(18,15,18,23)
    elif kind in {'purchase','sale','report','worklog','diary'}:
        p.drawRoundedRect(QRectF(7,5,18,23),2,2)
        if kind in {'purchase','sale'}:
            p.drawLine(16,10,16,23);up=kind=='sale';y=10 if up else 23;p.drawLine(11,y+(5 if up else -5),16,y);p.drawLine(21,y+(5 if up else -5),16,y)
        elif kind=='report':
            p.setBrush(QColor('#B7A16A'));p.drawRect(QRectF(11,19,3,6));p.drawRect(QRectF(16,14,3,11));p.drawRect(QRectF(21,10,2,15))
        elif kind=='diary':
            p.drawLine(12,5,12,28);p.drawLine(16,12,21,12);p.drawLine(16,17,21,17)
        else:
            p.drawRoundedRect(QRectF(12,4,8,5),1,1)
            for y in (13,18,23):p.drawLine(12,y,21,y)
    elif kind=='money':
        p.drawEllipse(QRectF(5,5,22,22));p.drawPolyline(QPolygonF([QPointF(10,11),QPointF(13,22),QPointF(16,15),QPointF(19,22),QPointF(22,11)]));p.drawLine(9,16,23,16)
    elif kind=='wallet':
        p.drawRoundedRect(QRectF(5,9,22,17),3,3);p.drawPolyline(QPolygonF([QPointF(7,9),QPointF(23,5),QPointF(25,9)]));p.drawRoundedRect(QRectF(20,15,8,6),2,2);p.drawPoint(23,18)
    elif kind=='truck':
        p.drawRect(QRectF(4,9,14,13));p.drawPolyline(QPolygonF([QPointF(18,13),QPointF(24,13),QPointF(28,18),QPointF(28,22),QPointF(18,22)]));p.setBrush(QColor('#FAF8F3'));p.drawEllipse(QRectF(8,21,5,5));p.drawEllipse(QRectF(21,21,5,5))
    elif kind=='user':
        p.drawEllipse(QRectF(12,6,8,8));p.drawArc(QRectF(7,17,18,17),0,180*16);p.drawLine(7,25,25,25)
    elif kind=='settings':
        p.drawEllipse(QRectF(9,9,14,14));p.drawEllipse(QRectF(13,13,6,6))
        for angle in range(0,360,45):
            a=math.radians(angle);p.drawLine(QPointF(16+8*math.cos(a),16+8*math.sin(a)),QPointF(16+11*math.cos(a),16+11*math.sin(a)))
    elif kind=='add':p.drawEllipse(QRectF(5,5,22,22));p.drawLine(16,10,16,22);p.drawLine(10,16,22,16)
    elif kind=='search':p.drawEllipse(QRectF(6,6,15,15));p.drawLine(20,20,27,27)
    else:p.drawLine(8,24,24,8);p.drawLine(8,24,13,23);p.drawLine(8,24,9,19)
    p.end();return QIcon(pix)


def decorate_menu(menu):
    for item in menu.actions():
        if not item.isSeparator() and item.icon().isNull():item.setIcon(menu_icon(item.text()))
        if item.menu():decorate_menu(item.menu())
