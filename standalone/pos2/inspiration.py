"""Original short encouragements, not quotations attributed to real people."""
import secrets
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QLabel,QVBoxLayout
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


class InspirationMixin:
    def inspiration(self,new=False):
        with self._tx():
            self._require();uid=self.actor['id'];row=self.db.execute('SELECT last_id FROM inspiration_history WHERE user_id=?',(uid,)).fetchone()
            previous=row[0] if row else -1
            selected=secrets.choice([i for i in range(len(WORDS)) if i!=previous]) if new or previous not in range(len(WORDS)) else previous
            self.db.execute('INSERT INTO inspiration_history VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET last_id=excluded.last_id',(uid,selected))
            return WORDS[selected]


class InspirationDialog(QDialog):
    def __init__(self,store,new=False,parent=None):
        super().__init__(parent);self.setWindowTitle('오늘도 당신을 응원합니다');self.resize(620,360)
        self.setStyleSheet('QDialog{background:#F6F4E9;} QLabel{color:#385D50;} QPushButton{padding:11px 20px;background:#E4EEE5;border:1px solid #B8CDBB;border-radius:9px;}')
        body=QVBoxLayout(self);body.setContentsMargins(36,28,36,28)
        heading=QLabel('🌿  오늘도 당신을 응원합니다');heading.setStyleSheet('font-size:21px;font-weight:600;');body.addWidget(heading)
        phrase=QLabel(store.inspiration(new));phrase.setWordWrap(True);phrase.setTextFormat(Qt.TextFormat.PlainText);phrase.setAlignment(Qt.AlignmentFlag.AlignCenter);phrase.setStyleSheet('font-size:25px;padding:20px;');body.addWidget(phrase,1)
        note=QLabel('상단 ‘오늘의 글귀’에서 다시 볼 수 있습니다. · 자체 작성 응원 문구');note.setWordWrap(True);body.addWidget(note)
        body.addWidget(action('닫고 시작하기',self.accept,primary=True))
