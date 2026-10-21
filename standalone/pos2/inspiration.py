"""Sourced wisdom and original reflections, with private random reading history."""
import secrets
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QLabel,QVBoxLayout,QHBoxLayout,QMessageBox
from .widgets import action

INSPIRATION_SCHEMA='''
CREATE TABLE IF NOT EXISTS inspiration_history (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,last_id INTEGER NOT NULL
);
'''
WORDS=(
 '오늘의 작은 한 걸음도, 어제 없던 길을 만듭니다.',
 '조금 느려도 괜찮습니다. 당신의 속도로 계속 걸어가세요.',
 '완벽한 하루보다, 나를 돌본 하루가 오래 남습니다.',
 '지친 마음에는 다그침보다 다정한 말 한마디가 필요합니다.',
 '지금 할 수 있는 작은 일을 해내는 것부터 시작해 보세요.',
 '쉬어 가는 시간도 앞으로 나아갈 힘을 모으는 시간입니다.',
 '오늘의 실수 하나가 당신의 모든 가치를 정하지는 않습니다.',
 '당연하게 지나친 하루에도 당신이 지켜 낸 소중한 것이 있습니다.',
 '좋은 변화는 대단한 결심보다 작은 반복에서 자랍니다.',
 '내일의 걱정을 모두 오늘 짊어지지 않아도 됩니다.',
 '함께 웃을 사람에게 먼저 안부를 건네 보세요.',
 '비교를 잠시 내려놓으면 내가 걸어온 길이 보입니다.',
 '하루를 잘 마치는 일에는 스스로를 칭찬하는 일도 포함됩니다.',
 '해결되지 않은 일이 있어도, 당신은 오늘 충분히 애썼습니다.',
 '따뜻한 밥 한 끼와 잠깐의 휴식도 삶을 지탱하는 힘입니다.',
 '다시 시작하기에 가장 알맞은 순간은 작은 용기를 낸 지금입니다.',
 '작은 친절은 누군가의 긴 하루를 부드럽게 바꿉니다.',
 '마음이 복잡할 때는 한 번에 한 가지 일만 바라보세요.',
 '어제보다 한 가지를 배웠다면, 오늘도 조금 자란 것입니다.',
 '소중한 사람과 나누는 평범한 시간이 특별한 기억이 됩니다.',
 '할 수 없는 일보다 지금 할 수 있는 한 가지를 골라 보세요.',
 '잘 버텨 온 자신에게 오늘은 조금 더 너그러워지세요.',
 '내가 바꿀 수 있는 작은 부분부터 돌보면 하루가 달라집니다.',
 '희망은 멀리 있는 정답이 아니라 다시 해 보려는 마음에도 있습니다.',
 '바쁜 날에도 물 한 잔과 깊은 숨 한 번을 잊지 마세요.',
 '당신의 수고가 눈에 띄지 않는 날에도 그 의미는 사라지지 않습니다.',
 '작은 기쁨을 기록하면 평범한 하루에도 빛나는 자리가 생깁니다.',
 '오늘의 끝에는 잘한 일 하나를 꼭 기억해 주세요.',
 '새로운 길은 서툰 첫걸음을 허락할 때 열립니다.',
 '삶을 단단하게 만드는 것은 나 자신을 포기하지 않는 마음입니다.',
 '매일이 눈부시지 않아도, 당신의 하루는 충분히 소중합니다.',
)

from .inspiration_cards import CARDS as SOURCED_CARDS,as_card,render
CARDS=tuple(dict(category='오늘의 응원',text=text,source='SY POS 자체 작성',english='',explanation='나에게 필요한 만큼만 가볍게 마음에 담아 보세요.',reflection='오늘 나에게 건네고 싶은 말은 무엇인가요?') for text in WORDS)+tuple(as_card(row) for row in SOURCED_CARDS)
WORDS=tuple(render(card) for card in CARDS)
CARD_BY_TEXT=dict(zip(WORDS,CARDS))


class InspirationMixin:
    def inspiration(self,new=False):
        with self._tx():
            self._require();uid=self.actor['id'];row=self.db.execute('SELECT last_id FROM inspiration_history WHERE user_id=?',(uid,)).fetchone()
            previous=row[0] if row else -1
            if new or previous not in range(len(WORDS)):
                prior=CARDS[previous]['category'] if previous in range(len(WORDS)) else None
                category=secrets.choice(sorted({card['category'] for card in CARDS if card['category']!=prior}))
                selected=secrets.choice([i for i,card in enumerate(CARDS) if card['category']==category and i!=previous])
            else:selected=previous
            self.db.execute('INSERT INTO inspiration_history VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET last_id=excluded.last_id',(uid,selected))
            return WORDS[selected]


class InspirationDialog(QDialog):
    def __init__(self,store,new=False,parent=None):
        super().__init__(parent);self.store=store;self.setWindowTitle('오늘의 글귀 · 생각을 쉬어 가는 시간');self.resize(740,600)
        self._sy_no_home_button=True;self.history=[store.inspiration(new)];self.history_index=0
        self.setStyleSheet('''
            QDialog{background:#F6F4E9;}
            QLabel{color:#385D50;}
            QPushButton{padding:11px 20px;min-height:24px;font-size:14px;font-weight:600;color:#24483C;background:#E4EEE5;border:2px solid #B8CDBB;border-radius:9px;}
            QPushButton:hover{color:#24483C;background:#D4E4D6;}
            QPushButton:pressed{color:#24483C;background:#C2D8C5;}
            QPushButton#primary{color:#FFFFFF;background:#215D49;border-color:#215D49;font-size:15px;font-weight:700;}
            QPushButton#primary:hover{color:#FFFFFF;background:#174B3A;border-color:#174B3A;}
            QPushButton#primary:pressed{color:#FFFFFF;background:#103B2D;border-color:#103B2D;}
            QPushButton:focus{border-color:#A47516;}
            QPushButton:disabled,QPushButton#primary:disabled{color:#58645C;background:#E0E4DF;border-color:#BBC6BD;}
        ''')
        body=QVBoxLayout(self);body.setContentsMargins(36,28,36,28)
        self.category=QLabel();self.category.setStyleSheet('font-size:18px;font-weight:600;');body.addWidget(self.category)
        self.phrase=QLabel();self.phrase.setAlignment(Qt.AlignmentFlag.AlignCenter);self.phrase.setStyleSheet('font-size:24px;font-weight:600;padding:12px;');body.addWidget(self.phrase)
        self.english=QLabel();self.english.setAlignment(Qt.AlignmentFlag.AlignCenter);self.english.setStyleSheet('font-size:21px;color:#53686A;padding:6px;');body.addWidget(self.english)
        self.explanation=QLabel();self.explanation.setStyleSheet('font-size:15px;padding:8px;');body.addWidget(self.explanation)
        self.reflection=QLabel();self.reflection.setStyleSheet('font-size:15px;color:#6B603E;background:#E9E5D3;padding:10px;');body.addWidget(self.reflection)
        self.source=QLabel();self.source.setStyleSheet('font-size:12px;color:#616D60;');body.addWidget(self.source)
        for label in (self.category,self.phrase,self.english,self.explanation,self.reflection,self.source):label.setWordWrap(True);label.setTextFormat(Qt.TextFormat.PlainText)
        body.addStretch();controls=QHBoxLayout()
        self.previous_button=action('이전 글귀',self.previous);controls.addWidget(self.previous_button)
        self.next_button=action('다음 글귀',self.next,primary=True);controls.addWidget(self.next_button)
        self.explanation_button=action('뜻풀이 · 해설',self.toggle_explanation);self.explanation_button.setCheckable(True);controls.addWidget(self.explanation_button)
        self.close_button=action('닫기',self.accept);controls.addWidget(self.close_button);body.addLayout(controls)
        self._sy_close_button=self.close_button
        self.start_button=self.next_button  # Internal compatibility; no duplicate button.
        self.next_button.setAccessibleName('창을 닫지 않고 다음 글귀 보기')
        self.previous_button.setToolTip('이 창에서 앞서 읽은 글귀로 돌아갑니다.');self.next_button.setToolTip('앞으로 읽은 기록이 있으면 이동하고, 마지막에서는 새로운 글귀를 무작위로 보여줍니다.')
        self.show_current()

    def show_current(self):
        text=self.history[self.history_index];card=CARD_BY_TEXT.get(text,dict(category='오늘의 글귀',text=text,english='',explanation='',reflection='',source=''))
        for name in ('category','text','english','explanation','reflection','source'):
            label=self.phrase if name=='text' else getattr(self,name)
            label.setText(('생각해 보기 · ' if name=='reflection' and card[name] else '출처 · ' if name=='source' and card[name] else '')+card[name])
            label.setVisible(bool(card[name]))
        self.previous_button.setEnabled(self.history_index>0)
        self.explanation_button.setEnabled(bool(card['explanation']));self.explanation_button.setChecked(False)
        self.explanation_button.setText('뜻풀이 · 해설');self.explanation.hide()

    def toggle_explanation(self,*_):
        opened=self.explanation_button.isChecked();self.explanation.setVisible(opened)
        self.explanation_button.setText('해설 접기' if opened else '뜻풀이 · 해설')

    def previous(self):
        if self.history_index>0:self.history_index-=1;self.show_current()

    def next(self):
        if self.history_index+1<len(self.history):self.history_index+=1
        else:
            try:text=self.store.inspiration(True)
            except (ValueError,PermissionError) as exc:QMessageBox.warning(self,'글귀 조회',str(exc));return
            self.history.append(text)
            if len(self.history)>100:self.history.pop(0)
            self.history_index=len(self.history)-1
        self.show_current()
