"""One shortcut catalogue for menus, hover help and the keyboard guide.

Function keys belong to the desktop/page window, never to the application:
editing dialogs keep their own F3/F5/F6/F7/F9 bindings.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QVBoxLayout


DIRECT_KEYS = {
    'home': ('Ctrl+Home',),
    'products': ('Ctrl+1', 'F2'),
    'suppliers': ('Ctrl+Shift+1', 'F3'),
    'categories': ('Ctrl+Shift+C',),
    'purchases': ('Ctrl+2', 'F4'),
    'payments': ('Ctrl+Shift+2', 'F7'),
    'sales': ('Ctrl+3', 'F6'),
    'quotations': ('Ctrl+Shift+3',),
    'promotions': ('Ctrl+5',),
    'inventory': ('Ctrl+6', 'F9'),
    'reports': ('Ctrl+7', 'F12'),
    'members': ('Ctrl+8',),
    'permissions': ('Ctrl+0',),
    'settings': ('Ctrl+,',),
    'diary': ('Alt+1',),
    'household': ('Alt+2',),
    'worklog': ('Alt+3',),
    'lucky_numbers': ('Alt+4',),
}
COMMON_KEYS = {
    '조회': ('F5',), '새로고침': ('F5',),
    'F8 스캔': ('F8',), '엑셀 저장': ('Ctrl+E',),
    '인쇄': ('Ctrl+P',), '새 항목': ('Ctrl+N',),
    '단축키 안내': ('F1',),
    '이전': ('Alt+Left',), '다음': ('Alt+Right',), '달력':('Ctrl+Shift+H',),
}
ACTION_KEYS = {
    **COMMON_KEYS,
    '첫화면': DIRECT_KEYS['home'], '상품장': DIRECT_KEYS['products'],
    '매입전표': DIRECT_KEYS['purchases'], '관리자 설정': DIRECT_KEYS['settings'],
    '판매조회': DIRECT_KEYS['sales'],
}


def menu_keys(sections):
    """Stable even when some entries are hidden by an employee's permissions.

Less frequent pages use a two-step sequence: Ctrl+Alt+section, then A/B/… .
No normal typing or standard text editing shortcut is captured on its own.
"""
    result = {}
    for title, entries in sections:
        for index, (key, _caption, _permission) in enumerate(entries):
            if key in DIRECT_KEYS:
                result[key] = DIRECT_KEYS[key]
            else:
                assert title[0].isdigit() and index < 26
                result[key] = (f'Ctrl+Alt+{title[0]}, {chr(65+index)}',)
    return result


def key_text(sequences):
    return ' / '.join(sequence.replace(', ', ' → ') for sequence in sequences)


def help_text(description, sequences=()):
    return description + ('\n단축키: ' + key_text(sequences) if sequences else '')


def bind_action(window, text, sequences, callback):
    shortcut = QAction(text, window)
    shortcut.setShortcuts([QKeySequence(sequence) for sequence in sequences])
    shortcut.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    shortcut.setAutoRepeat(False)
    shortcut.triggered.connect(callback)
    window.addAction(shortcut)
    return shortcut


def install_window_shortcuts(target, desktop):
    """Independent business windows have local actions, not app-global hooks."""
    target.menu_shortcut_actions = {}
    for key, source in desktop.nav_actions.items():
        target.menu_shortcut_actions[key] = bind_action(
            target, source.text(), desktop.menu_keys[key],
            lambda checked=False, page=key: desktop.go_home() if page=='home' else desktop.open_page(page))
    callbacks = {
        '단축키 안내': lambda: desktop.show_shortcut_guide(target),
        '조회': target.refresh,
        'F8 스캔': desktop.focus_scan, '엑셀 저장': desktop.export,
        '인쇄': desktop.print, '새 항목': desktop.new_current,
        '이전': desktop.previous_menu, '다음': desktop.next_menu,
        '달력':desktop.open_calendar,
    }
    target.common_shortcut_actions = {
        title: bind_action(target, title, COMMON_KEYS[title], callback)
        for title, callback in callbacks.items()
    }


class ShortcutGuide(QDialog):
    def __init__(self, desktop, parent=None):
        super().__init__(parent or desktop)
        from .menu_help import MENU_HELP
        from .widgets import DataGrid, action
        self.setWindowTitle('단축키 안내 · SY POS')
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        note = QLabel('메뉴 위에 약 0.7초 머무르면 설명·단축키가 표시됩니다.\n'
                      '→ 표시는 앞 조합을 누르고 손을 뗀 뒤 다음 키를 누릅니다. '
                      '입력 팝업에서는 해당 화면의 단축키가 우선하며 F11은 전체화면입니다.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.search = QLineEdit()
        self.search.setPlaceholderText('메뉴명 · 설명 · 단축키 검색')
        layout.addWidget(self.search)
        self.grid = DataGrid(['메뉴 / 기능', '단축키', '간단한 설명'])
        self.grid.setColumnWidth(0, 200); self.grid.setColumnWidth(1, 210)
        layout.addWidget(self.grid, 1)
        self.records = [
            {'title': source.text(), 'keys': key_text(desktop.menu_keys[key]), 'help': MENU_HELP[key]}
            for key, source in desktop.nav_actions.items()
        ]
        from .menu_help import ACTION_HELP
        self.records += [
            {'title': title, 'keys': key_text(COMMON_KEYS[title]), 'help': ACTION_HELP.get(title, '현재 화면의 새 항목을 작성합니다.')}
            for title in ('단축키 안내', '조회', 'F8 스캔', '엑셀 저장', '인쇄', '새 항목', '이전', '다음','달력')
        ]
        self.search.textChanged.connect(self.refresh)
        self.refresh()
        layout.addWidget(action('닫기', self.close))

    def refresh(self):
        query = self.search.text().strip().casefold()
        rows = [row for row in self.records if query in ' '.join(row.values()).casefold()]
        self.grid.fill([[row['title'], row['keys'], row['help']] for row in rows], rows)
