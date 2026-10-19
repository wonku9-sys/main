"""Original local, high-DPI vector-painted icons. No downloads or font glyphs."""
from functools import lru_cache
import math
from PySide6.QtCore import Qt,QPointF,QRectF
from PySide6.QtGui import QColor,QIcon,QPainter,QPainterPath,QPen,QPixmap,QPolygonF


def family(key):
    if key=='lucky_numbers' or '행운' in key or '추첨' in key:return 'lucky'
    if key=='goal' or '목표' in key or '예산' in key:return 'goal'
    if key=='calendar' or '달력' in key or '일정' in key:return 'calendar'
    if key=='home' or '첫화면' in key:return 'home'
    if 'waste' in key or any(x in key for x in ('삭제','폐기','무효')):return 'waste'
    if 'category' in key or 'categories' in key or '분류' in key:return 'category'
    if key=='products' or '상품' in key or key=='labels':return 'product'
    if key=='diary' or '일기' in key:return 'diary'
    if key=='household' or '가계부' in key:return 'wallet'
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


@lru_cache(maxsize=128)
def menu_icon(key):
    kind=family(key);pix=QPixmap(64,64);pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.scale(2,2)
    ink='#A75C59' if kind=='waste' else '#4D6B9B' if kind in {'sale','user','search'} else '#2E6B56'
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#F8E9E5' if kind=='waste' else '#ECF1F8' if ink=='#4D6B9B' else '#E7F0E9'));p.drawRoundedRect(QRectF(1,1,30,30),7,7)
    p.setPen(QPen(QColor(ink),1.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));p.setBrush(Qt.BrushStyle.NoBrush)
    if kind=='lucky':
        p.drawEllipse(QRectF(6,4,20,20));p.drawRoundedRect(QRectF(9,24,14,4),1,1)
        for x,y in ((12,11),(21,12),(16,19)):p.setBrush(QColor('#B7A16A'));p.drawEllipse(QRectF(x-2,y-2,4,4))
    elif kind=='goal':
        p.drawEllipse(QRectF(5,5,22,22));p.drawEllipse(QRectF(10,10,12,12));p.drawLine(16,16,27,5);p.drawLine(21,5,27,5);p.drawLine(27,5,27,11)
    elif kind=='calendar':
        p.drawRoundedRect(QRectF(6,7,20,20),2,2);p.drawLine(6,13,26,13);p.drawLine(11,5,11,10);p.drawLine(21,5,21,10)
        for x in (11,16,21):
            for y in (18,23):p.drawPoint(x,y)
    elif kind=='home':
        p.drawPolyline(QPolygonF([QPointF(5,15),QPointF(16,6),QPointF(27,15)]));p.drawRoundedRect(QRectF(9,14,14,12),1,1);p.drawRect(QRectF(14,19,4,7))
    elif kind in {'product','inventory'}:
        p.drawPolygon(QPolygonF([QPointF(6,11),QPointF(16,6),QPointF(26,11),QPointF(26,23),QPointF(16,28),QPointF(6,23)]));p.drawLine(6,11,16,16);p.drawLine(26,11,16,16);p.drawLine(16,16,16,28);p.drawLine(11,9,21,14)
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
