"""Explicit, selected settings defaults; never a business-data factory wipe."""
from PySide6.QtWidgets import QCheckBox,QDialog,QDialogButtonBox,QLabel,QVBoxLayout

GROUPS={
    'appearance':('화면 색감 · 기본 스킨',{'appearance_theme':'default'}),
    'calculation':('금액 계산 · 재고 부족 허용',{'rounding_mode':'decimal','allow_negative_stock':True}),
    'points':('회원 포인트 정책',{'earn_bps':100,'point_min':1000,'point_step':100,'point_enabled':True}),
    'backup':('정상 종료 시 자동 백업',{'on_exit':True}),
    'sounds':('기본 효과음 · 음량',{}),
}


class SettingsDefaultsDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent);self.setWindowTitle('설정 기본값 복원');self.resize(560,330)
        layout=QVBoxLayout(self);self.boxes={}
        note=QLabel('복원할 항목만 선택하세요. 기본값을 입력한 뒤 ‘설정 저장’을 눌러야 적용됩니다.\n사업자·상품·매입·판매·재고·회원·계정·권한·메일·PC 연결 정보는 삭제하지 않습니다.');note.setWordWrap(True);layout.addWidget(note)
        descriptions={'appearance':'기본 쿨그레이/세이지 스킨 (설정 저장 후 적용)',
                      'calculation':'소수점 2자리 보존 / 마이너스 재고 거래 허용',
                      'points':'포인트 허용 / 적립률 1% / 최소 사용 1,000 / 사용 단위 100',
                      'backup':'정상 종료 시 백업 켜기 (로그인·입력 중 자동 백업 없음)',
                      'sounds':'승인된 기본음 / 사용 켜기 / 기본 음량 (직접 선택한 음원 파일은 삭제하지 않음)'}
        for key,(title,_) in GROUPS.items():
            box=QCheckBox(title);box.setToolTip(descriptions[key]);self.boxes[key]=box;layout.addWidget(box)
            description=QLabel(descriptions[key]);description.setWordWrap(True);layout.addWidget(description)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.apply_button=buttons.button(QDialogButtonBox.StandardButton.Ok);self.apply_button.setText('선택 항목 기본값 입력');self.apply_button.setEnabled(False)
        for box in self.boxes.values():box.toggled.connect(lambda:self.apply_button.setEnabled(any(b.isChecked() for b in self.boxes.values())))
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def selected(self):return [key for key,box in self.boxes.items() if box.isChecked()]


def stage_defaults(page,groups):
    page.store.require_menu('settings');page.store._require('admin')
    if not groups or set(groups)-set(GROUPS):raise ValueError('복원할 설정 항목을 선택하세요.')
    if 'appearance' in groups:
        page.appearance_theme.setCurrentIndex(page.appearance_theme.findData('default'))
        for field in (page.holiday_skin,page.snow_effect,page.weather_effect):field.setChecked(False)
    if 'calculation' in groups:
        page.rounding_mode.setCurrentIndex(page.rounding_mode.findData('decimal'));page.negative_stock.setChecked(True)
    if 'points' in groups:
        page.point_enabled.setChecked(True)
        for key in ('earn_bps','point_min','point_step'):page.fields[key].setText(str(GROUPS['points'][1][key]))
    if 'backup' in groups:page.backup_exit.setChecked(True)
    if 'sounds' in groups:page.restore_sounds.setChecked(True)
    page.notify('선택한 기본값을 입력했습니다. 아직 저장되지 않았습니다. ‘설정 저장’으로 적용하거나 ‘현재 설정 다시 조회’로 취소하세요.')


def restore_sound_defaults(store):
    from PySide6.QtWidgets import QApplication
    from .lucky_audio import DrawSound,login_sound,warning_sound,mouse_sound
    from .ui_sounds import public_sound_settings
    store.require_menu('settings');store._require('admin')
    app=QApplication.instance();public=public_sound_settings();public.setValue('enabled',True);public.sync()
    store.save_popup_sound_enabled(True)
    sounds=[login_sound(),warning_sound(),mouse_sound('click'),mouse_sound('context')]
    lucky=getattr(app,'_sy_lucky_window',None)
    from shiboken6 import isValid
    if lucky is not None and not isValid(lucky):lucky=None
    for kind in ('draw','open'):
        sounds.append(getattr(lucky.page,'draw_sound' if kind=='draw' else 'open_sound') if lucky is not None else DrawSound(app,kind=kind))
    for sound in sounds:
        sound.use_default();sound.set_enabled(True);sound.settings.remove('volume');sound.settings.sync();sound.set_volume(sound.volume)
