"""New document, signed-stock, game and encrypted crash-journal boundaries."""
from datetime import date
from decimal import Decimal
import json
import random
import re
import secrets
from types import SimpleNamespace
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtWidgets import QApplication,QMessageBox,QPushButton
from pos2.store import Store


@pytest.fixture
def shop(tmp_path):
    store=Store(tmp_path/'new.db');store.setup_admin('owner','관리자','Owner-Password-2026!')
    sup=store.save_partner(dict(kind='supplier',name='공급사'));customer=store.save_partner(dict(kind='customer',name='거래처'))
    product=store.save_product(dict(name='테스트 상품',base_unit='g',price_basis=100,purchase_price='123.45',sale_price='200.25',barcode='100200300',tax_mode='taxable',specification='100g',supplier_id=sup))
    yield store,sup,customer,product
    store.close()


@pytest.fixture
def desktop(shop,monkeypatch):
    from pos2.app import MainWindow
    from pos2.popup_policy import install_popup_policy
    app=QApplication.instance() or QApplication([]);install_popup_policy(app)
    window=MainWindow(shop[0]);window.show();window.navigation.enable();app.processEvents()
    monkeypatch.setattr(QMessageBox,'warning',lambda *_:QMessageBox.StandardButton.Ok)
    monkeypatch.setattr('pos2.navigation.ask_unsaved',lambda *_:QMessageBox.StandardButton.Discard)
    yield app,window
    if hasattr(window,'crash_journal'):window.crash_journal.stop()
    window.navigation.suspended=True;window.navigation.disable()
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def trade(shop,kind,quantity,price='123.45'):
    s,sup,customer,p=shop
    return s.post_document(dict(kind=kind,date=date.today().isoformat(),partner_id=sup if kind=='purchase' else customer,lines=[dict(product_id=p,qty=quantity,unit_price=price)]))


def order_data(shop):return dict(date=date.today().isoformat(),partner_id=shop[2],lines=[dict(product_id=shop[3],qty='250',unit_price='200.25')],order=dict(delivery_date=date.today().isoformat(),assignee='김 담당',phone='010-1111-2222',address='서울',delivery_note='문 앞',order_type='phone'))


def test_order_is_nonposting_snapshot_and_lifecycle_exactly_once_sale(shop):
    s=shop[0];s.save_settings(dict(store_name='우리 상점',representative='대표',business_type='소매',bank='은행',account='123'))
    identifier=s.save_sales_form('order',order_data(shop));record=s.sales_form(identifier)
    assert record['total']==Decimal('500.63') and record['seller']['store_name']=='우리 상점'
    assert record['lines'][0]['barcode']=='100200300' and record['order']['delivery_note']=='문 앞'
    assert not s.documents() and s.products()[0]['stock_qty']=='0.000'
    s.save_settings(dict(store_name='변경 상점'));assert s.sales_form(identifier)['seller']['store_name']=='우리 상점'
    s.set_order_status(identifier,'printed');assert len(s.sales_forms('order',date.today(),date.today(),status='printed',date_basis='delivery_date'))==1
    sale=s.post_order_sale(identifier);assert s.post_order_sale(identifier)==sale
    assert len(s.documents())==1 and s.products()[0]['stock_qty']=='-250.000'
    assert s.sales_form(identifier)['order']['status']=='completed'
    with pytest.raises(ValueError):s.delete_sales_form(identifier)
    with pytest.raises(ValueError):s.set_order_status(identifier,'cancelled')


def test_order_cancel_permissions_and_atomic_failed_conversion(shop):
    s=shop[0];identifier=s.save_sales_form('order',order_data(shop));s.set_order_status(identifier,'cancelled')
    with pytest.raises(ValueError):s.post_order_sale(identifier)
    s.set_order_status(identifier,'received');s.save_settings({'allow_negative_stock':False})
    with pytest.raises(ValueError):s.post_order_sale(identifier)
    assert not s.documents() and s.sales_form(identifier)['order']['document_id'] is None
    staff=s.save_user(dict(code='staff',name='직원',password='Staff-Password-2026!',permissions=['trade','deny:orders.edit']))
    s.login('staff','Staff-Password-2026!')
    with pytest.raises(PermissionError):s.set_order_status(identifier,'completed')
    with pytest.raises(PermissionError):s.post_order_sale(identifier)


def test_signed_stock_exact_cost_inbound_returns_count_and_red_display(shop,desktop):
    s=shop[0];trade(shop,'sale','250','200.25')
    p=s.products()[0];assert p['stock_qty']=='-250.000' and p['stock_cost']==Decimal('-308.63')
    assert '잠정' in s.stock_events(shop[3])[0]['reason']
    assert s.inventory_status(stock_filter='negative')['products'][0]['stock_qty']=='-250'
    trade(shop,'purchase','250','150.00')
    assert s.products()[0]['stock_qty']=='0.000' and s.products()[0]['stock_cost']==Decimal('66.37')
    # Explicit count clears valuation differences, never an invisible rewrite.
    count=s.create_count(dict(title='입고 확인',date=date.today().isoformat(),items=[dict(product_id=shop[3],expected_qty='0',counted_qty='0')]))
    s.apply_count(count);assert s.products()[0]['stock_cost']==0
    trade(shop,'sale','100');count=s.create_count(dict(title='음수 실사',date=date.today().isoformat(),items=[dict(product_id=shop[3],expected_qty='-100',counted_qty='10')]))
    s.apply_count(count);assert s.products()[0]['stock_qty']=='10.000' and s.products()[0]['stock_cost']==Decimal('12.35')
    from pos2.widgets import DataGrid
    grid=DataGrid(['수량']);grid.fill([[Decimal('-2.50')]])
    assert grid.item(0,0).foreground().color().name()=='#b42318'


def test_signed_stock_sale_cancel_conserves_every_movement(shop):
    s=shop[0];identifier=trade(shop,'sale','100');s.cancel_document(identifier,'입력 취소')
    assert s.products()[0]['stock_qty']=='0.000' and s.products()[0]['stock_cost']==0
    assert sum(row[0] for row in s.db.execute('SELECT qty_delta FROM stock_events'))==0
    assert sum(row[0] for row in s.db.execute('SELECT cost_delta FROM stock_events'))==0
    s.save_settings({'allow_negative_stock':False})
    with pytest.raises(ValueError):trade(shop,'sale','1')
    assert len(s.documents())==1


def test_a4_paper_escapes_input_conserves_cents_and_renders_png(shop,desktop,tmp_path,monkeypatch):
    from pos2.commercial_paper import paper_html,paper_document,paper_images
    from pos2.paper_output_ui import output_paper
    from PySide6.QtWidgets import QFileDialog
    s=shop[0];s.save_settings(dict(store_name='<SCRIPT>상호',account='계좌-001'))
    identifier=s.save_sales_form('quotation',dict(order_data(shop),memo='<img src="http://example.invalid/a">'))
    record=s.sales_form(identifier);html=paper_html(record,'견적서')
    assert '&lt;SCRIPT&gt;' in html and '<img src=' not in html and '500.63' in html and '계좌-001' in html
    document=paper_document(record,'견적서');assert document.pageCount()==1
    images=list(paper_images(document));assert images[0].width()==1588 and not images[0].isNull()
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *_:(str(tmp_path/'견적.png'),'PNG'))
    paths=output_paper(s,identifier,'견적서',desktop[1],'image');assert len(paths)==1 and (tmp_path/'견적.png').read_bytes().startswith(b'\x89PNG')
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *_:(str(tmp_path/'견적.pdf'),'PDF'))
    output_paper(s,identifier,'견적서',desktop[1],'pdf');assert (tmp_path/'견적.pdf').read_bytes().startswith(b'%PDF')


def test_games_engines_independent_movement_scoring_and_gomoku_block():
    from pos2.arcade import Blocks,Gomoku,Shooter
    blocks=Blocks(random.Random(1));old=blocks.y;blocks.tick(1);assert blocks.y==old+1
    blocks.drop();assert blocks.score>0 and any(any(row) for row in blocks.board)
    game=Gomoku(random.Random(1))
    for x in range(4):game.board[7][x]=1
    game.ai();assert game.board[7][4]==2 and not game.over
    game=Gomoku()
    for x in range(4):game.place(x,0,1)
    game.place(4,0,1);assert game.over and game.winner==1 and game.score>=1000
    shooter=Shooter(random.Random(1));before=shooter.x;shooter.right=True;shooter.fire=True;shooter.tick(.05)
    assert shooter.x>before and shooter.bullets and shooter.enemies


def test_original_platform_games_coins_jumping_bubble_capture_and_stages():
    from pos2.arcade import Jumper,Bubbles
    jump=Jumper(random.Random(2));jump.coins=[(jump.x+13,jump.y+17)];jump.tick(.01);assert jump.score==100 and not jump.coins
    jump.y=546;jump.grounded=True;jump.jump=True;jump.tick(.02);assert jump.vy<0
    jump.x=2540;jump.tick(.01);assert jump.stage==2 and jump.score>=2000
    bubble=Bubbles(random.Random(3));bubble.enemies=[dict(x=120.,y=530.,vy=0.,direction=1,grounded=True)]
    bubble.orbs=[dict(x=134.,y=547.,age=.9,direction=1,captured=False)]
    bubble.tick(.01);assert bubble.orbs[0]['captured'] and not bubble.enemies and bubble.score==50
    bubble.x=bubble.orbs[0]['x']-13;bubble.y=bubble.orbs[0]['y']-17;bubble.tick(.01)
    assert bubble.stage==2 and bubble.score==1350


@pytest.mark.parametrize('kind',['blocks','gomoku','shooter','jumper','bubbles','raccoon'])
def test_every_arcade_game_draws_in_its_independent_popup(desktop,tmp_path,kind):
    from pos2.arcade_ui import ArcadeGameDialog,ScoreBook
    app,window=desktop;game=ArcadeGameDialog(kind,ScoreBook(tmp_path/'scores.json'));game.show();app.processEvents()
    assert not game.isModal() and not game.grab().isNull();game.close();assert not game.timer.isActive() and window.isVisible()


def test_raccoon_ladders_jump_fruit_hit_timer_and_final_stage():
    from pos2.arcade import Raccoon
    game=Raccoon(random.Random(2));game.enemies=[];game.x=57;game.up=True
    for _ in range(105):game.tick(.01)
    assert game.y==406 and game.grounded and not game.climbing
    game.up=False;game.right=True;before=game.x;game.tick(.02);assert game.x>before
    game.right=False;game.jump=True;game.tick(.02);assert game.vy<0
    game.fruits=[(game.x+13,game.y+17)];game.tick(.01);assert game.stage==2 and game.score>1000
    game.enemies=[dict(x=game.x,y=game.y,direction=1)];game.tick(.01)
    assert game.lives==2 and game.invincible>0
    game.tick(.01);assert game.lives==2
    game.invincible=0;game.time_left=.001;game.tick(.01);assert game.lives==1 and game.time_left>=35
    game.invincible=0;game.hurt();assert game.over
    game=Raccoon();game.stage=5;game.fruits=[];game.enemies=[];game.tick(.01)
    assert game.won and game.over


def test_raccoon_keys_are_cleared_on_pause_and_recorded_once(desktop,tmp_path):
    from pos2.arcade_ui import ArcadeGameDialog,ScoreBook,GAMES
    app,_=desktop;book=ScoreBook(tmp_path/'raccoon-scores.json');game=ArcadeGameDialog('raccoon',book)
    game.key(Qt.Key.Key_Up,True);game.key(Qt.Key.Key_Right,True);game.key(Qt.Key.Key_Space,True)
    assert game.game.up and game.game.right and game.game.jump
    game.pause();assert not game.game.up and not game.game.right and not game.game.jump
    game.game.score=1234;game.game.over=True;game.refresh();game.close()
    assert len(book.rows())==1 and book.rows()[0]['game']=='raccoon'
    assert '테트리스' in GAMES['blocks'][0]


def test_game_score_persistence_once_and_pause_does_not_drive_pos(desktop,tmp_path):
    from pos2.arcade_ui import ScoreBook,ArcadeGameDialog
    app,window=desktop;book=ScoreBook(tmp_path/'scores.json');game=ArcadeGameDialog('blocks',book,'점주');game.show();app.processEvents()
    game.paused=False;game.key(Qt.Key.Key_Space,True);score=game.game.score;assert score>0
    game.pause();before=game.game.y;game.tick();assert game.game.y==before
    game.game.over=True;game.refresh();game.refresh();game.close();assert len(book.rows())==1 and book.rows()[0]['score']==score
    assert window.isVisible()
    book.path.write_text('{broken',encoding='utf-8')
    with pytest.raises(ValueError):book.add('blocks','플레이어',3,'끝')
    assert book.path.read_text(encoding='utf-8')=='{broken'


@pytest.fixture
def encrypted_dpapi(monkeypatch):
    from pos2 import windows_secrets
    key=secrets.token_bytes(32)
    def protect(payload):
        nonce=secrets.token_bytes(12);return nonce+AESGCM(key).encrypt(nonce,payload,b'test-windows-user')
    monkeypatch.setattr(windows_secrets,'protect',protect)
    monkeypatch.setattr(windows_secrets,'unprotect',lambda cipher:AESGCM(key).decrypt(cipher[:12],cipher[12:],b'test-windows-user'))


def test_crash_journal_encrypted_draft_roundtrip_never_posts(shop,desktop,encrypted_dpapi):
    from pos2.unsaved_work import CrashJournal,apply_values
    from pos2.workflow_ui import TradeDialog
    app,window=desktop;journal=CrashJournal(window,testing=True);window.crash_journal=journal
    window.open_page('purchases');dialog=TradeDialog(window);dialog.show();app.processEvents()
    dialog.partner.setCurrentIndex(dialog.partner.findData(shop[1]));dialog.scan_barcode('100200300');dialog.line_rows[0]['qty'].setText('123.456');dialog.memo.setText('중단 전 민감한 매입 메모')
    journal.capture(dialog);rows=journal.rows();assert len(rows)==1
    cipher=next(journal.root.glob('*.draft')).read_bytes();assert '민감한'.encode() not in cipher
    payload=journal.read(rows[0]['identifier']);restored=TradeDialog(window);restored.show();app.processEvents();apply_values(restored,payload)
    assert restored.memo.text()=='중단 전 민감한 매입 메모' and restored.line_rows[0]['qty'].text()=='123.456'
    assert not shop[0].documents() and shop[0].products()[0]['stock_qty']=='0.000'
    journal.forget(dialog);assert not journal.rows()


def test_private_journal_requires_vault_key_and_omits_passwords(shop,desktop,encrypted_dpapi):
    from pos2.unsaved_work import CrashJournal,capture_values
    from pos2.diary_ui import DiaryDialog
    from pos2.widgets import FormDialog
    app,window=desktop;s=shop[0];s.setup_diary('Private-Password!','Private-Password!');key=s.unlock_diary('Private-Password!')
    journal=CrashJournal(window,testing=True);window.crash_journal=journal
    diary=DiaryDialog(s,key,window);diary.show();app.processEvents();diary.editor.setPlainText('나만의 일기 비밀');journal.capture(diary)
    row=journal.rows()[0];assert row['sealed'] and row['private']=='diary'
    with pytest.raises(PermissionError):journal.read(row['identifier'])
    with pytest.raises(PermissionError):journal.read(row['identifier'],bytes(32))
    assert '나만의 일기 비밀' in str(journal.read(row['identifier'],key))
    form=FormDialog('검사',window);password=form.field('password','암호',password=True);password.setText('NEVER-JOURNAL-SECRET')
    assert 'NEVER-JOURNAL-SECRET' not in str(capture_values(form))


def test_personal_menu_labels_fit_and_store_profile_is_connected(desktop,shop):
    app,window=desktop
    buttons=[b for b in window.personal_panel.findChildren(QPushButton)]
    assert {'일기장','가계부','업무일지','행운의 숫자'}<={b.text() for b in buttons}
    for button in buttons:
        assert button.fontMetrics().horizontalAdvance(button.text())+button.iconSize().width()+30<=button.width()
    assert window.personal_panel.parentWidget() is window.personal_dock
    assert window.personal_dock.geometry().top()>window.stack.geometry().top()
    window.open_page('store_profile');page=window.current_page;page.fields['representative'].setText('홍 대표');assert page.save()
    assert shop[0].store_profile()['representative']=='홍 대표'
