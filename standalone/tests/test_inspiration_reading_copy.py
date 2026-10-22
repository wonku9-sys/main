from collections import Counter

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pos2.store import Store
from pos2.inspiration import CARDS,WORDS,InspirationDialog,category_pool
from pos2.inspiration_cards import CARDS as ORIGINAL_CARDS
from pos2.inspiration_life import CARDS as LIFE_CARDS,THEMES
from pos2.inspiration_hanja import hanja_characters,READINGS,GLOSSES,MEANINGS


@pytest.fixture
def desktop(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'wisdom.db');store.setup_admin('owner','시험 관리자','Wisdom-Test-2026!')
    dialog=InspirationDialog(store);dialog.show();app.processEvents()
    yield app,store,dialog
    for widget in app.topLevelWidgets():widget.close();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();store.close()


def display(dialog,index):
    dialog.history=[WORDS[index]];dialog.history_index=0;dialog.show_current()


@pytest.mark.parametrize('index',[i for i,c in enumerate(CARDS) if hanja_characters(c['text'])])
def test_every_hanja_card_has_sentence_reading_each_character_gloss_and_meaning(desktop,index):
    app,_,dialog=desktop;card=CARDS[index];display(dialog,index);app.processEvents()
    assert dialog.reading.isVisible() and card['reading']==READINGS[card['text']]
    assert not dialog.explanation.isVisible()
    QTest.mouseClick(dialog.explanation_button,Qt.MouseButton.LeftButton);app.processEvents()
    assert dialog.explanation.isVisible() and card['reading'] in dialog.explanation.text()
    assert MEANINGS[card['text']] in dialog.explanation.text()
    for char in hanja_characters(card['text']):assert f'{char}({GLOSSES[char]})' in dialog.explanation.text()
    assert dialog.reading_area.horizontalScrollBar().maximum()==0
    assert dialog.copy_button.isVisible() and dialog.copy_button.isEnabled()


def test_special_readings_are_context_correct():
    assert READINGS['學而時習之，不亦說乎']=='학이시습지, 불역열호'
    assert GLOSSES['說']=='기쁠 열'
    assert READINGS['行有不得者，皆反求諸己'].endswith('개반구저기') and GLOSSES['諸']=='어조사 저'


def test_sixty_original_life_readings_and_old_numeric_ids_are_preserved():
    assert len(LIFE_CARDS)==60 and len(THEMES)==6 and all(len(rows)==10 for rows in THEMES.values())
    assert len({c['text'] for c in CARDS})==len(CARDS)==len(WORDS)
    assert [c['text'] for c in CARDS[31:31+len(ORIGINAL_CARDS)]]==[row[1] for row in ORIGINAL_CARDS]
    life=CARDS[-60:]
    assert all(c['source']=='SY POS 자체 작성 · 인생 지혜' and c['explanation'] and c['reflection'] for c in life)
    counts=Counter(category_pool())
    assert all(weight==(2 if category.startswith('인생의 지혜 · ') else 1) for category,weight in counts.items())
    assert all(category not in category_pool(category) for category in counts)


def test_copy_button_and_shortcut_copy_current_reading_and_source_without_database_writes(desktop):
    app,store,dialog=desktop
    index=next(i for i,c in enumerate(CARDS) if c['text']=='學而時習之，不亦說乎');display(dialog,index)
    before=store.audit_revision();saved=store.db.execute('SELECT * FROM inspiration_history').fetchall()
    QTest.mouseClick(dialog.copy_button,Qt.MouseButton.LeftButton);app.processEvents()
    copied=QApplication.clipboard().text()
    assert CARDS[index]['text'] in copied and '학이시습지, 불역열호' in copied and CARDS[index]['source'] in copied
    assert '복사했습니다' in dialog.copy_status.text() and dialog.isVisible()
    assert dialog.history_index==0 and store.audit_revision()==before
    assert store.db.execute('SELECT * FROM inspiration_history').fetchall()==saved
    display(dialog,len(CARDS)-1);QTest.keySequence(dialog,QKeySequence('Ctrl+Shift+C'));app.processEvents()
    assert CARDS[-1]['text'] in QApplication.clipboard().text() and '學而時習之' not in QApplication.clipboard().text()
    assert store.audit_revision()==before


def test_labels_allow_drag_keyboard_copy_and_navigation_clears_confirmation(desktop):
    app,_,dialog=desktop;display(dialog,0)
    for label in (dialog.phrase,dialog.reading,dialog.english,dialog.explanation,dialog.reflection,dialog.source):
        assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
        assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByKeyboard
    dialog.phrase.setFocus();dialog.phrase.setSelection(0,5)
    QTest.keySequence(dialog.phrase,QKeySequence.StandardKey.Copy);app.processEvents()
    assert QApplication.clipboard().text()==dialog.phrase.text()[:5]
    dialog.copy_button.click();dialog.next_button.click();assert not dialog.copy_status.text()
    next_text=dialog.phrase.text();dialog.previous_button.click();assert dialog.phrase.text()==CARDS[0]['text']
    dialog.next_button.click();assert dialog.phrase.text()==next_text and dialog.isVisible()


def test_longest_hanja_explanation_scrolls_without_hiding_controls(desktop):
    app,_,dialog=desktop
    index=max(range(len(CARDS)),key=lambda i:len(CARDS[i]['explanation']))
    display(dialog,index);dialog.resize(740,600);dialog.explanation_button.click();app.processEvents();app.processEvents()
    assert dialog.reading_area.verticalScrollBar().maximum()>0
    # The global popup policy deliberately removes redundant close buttons;
    # the native window X remains available.
    for button in (dialog.previous_button,dialog.next_button,dialog.copy_button,dialog.explanation_button):
        assert button.isVisible() and dialog.rect().contains(button.geometry())
        assert not dialog.reading_area.isAncestorOf(button)
    assert dialog.width()==740 and dialog.height()==600


def test_stored_original_quote_id_keeps_the_same_subject_after_reopen(desktop):
    _,store,dialog=desktop;index=31
    store.db.execute('UPDATE inspiration_history SET last_id=? WHERE user_id=?',(index,store.actor['id']));store.db.commit()
    assert store.inspiration(False)==WORDS[index] and CARDS[index]['text']==ORIGINAL_CARDS[0][1]
