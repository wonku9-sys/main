"""User-supplied, explicitly approved release sounds and their event mapping."""
from hashlib import sha256
from pathlib import Path


SOUNDS = {
    'draw': ('freesound_community-winning-82808.mp3', '6ca79465b7a62206de8883123e3d7e3efff2fe0ce2d8236d3fef9456d0fa9a65', '공 추첨'),
    'open': ('u_xmiiqyhi46-gamestart-272829.mp3', 'ad92d9c232e945c5bb3ef941777cd20703f9caf3ef09e875797dee2c2f8e8c32', '행운의 숫자 열기'),
    'login': ('freesound_community-lovelyboot1-103697.mp3', 'a8c8ea88b683c3ca7bdd0e78d4eb092869cb3f43845053c15493cb48f347a8a1', '로그인 성공'),
    'warning': ('liecio-message-alert-190042.mp3', '0e7dafa80dca5da5f9804e5164a232b864a9ca5d5c76d8469da0e9846ff853b9', '경고·알림'),
    'click': ('universfield-computer-mouse-click-02-383961.mp3', 'e9fdb3ed918d112c06a6573fae13c236b18d7c6d2225ab917048e20851d60feb', '왼쪽 마우스 클릭'),
    'context': ('creatorshome-sharp-pop-328170.mp3', 'b89f463a8ebc94babe30ec854cbf7493eafdee8c04ea9eb12b444e44166b0b7b', '오른쪽 마우스 메뉴 열기'),
}
SOUND_DIRECTORY = Path(__file__).resolve().parent / 'assets' / 'sounds'
MOUSE_PCM = {
    'click': ('mouse-click-ready.wav', 'f702bcac41c127177633cbd0c3ea970645a235965552e5a88ac885adf29a19de'),
    'context': ('mouse-context-ready.wav', '3a641b6a4c0ee72a26588087aac0bacb758a5d126e80302b6ca99b6112dc0e7d'),
}


def mouse_pcm_source(kind, original):
    """Only the approved MP3 (including private copies) uses its PCM derivative."""
    if kind not in MOUSE_PCM or original is None:
        return None
    original = Path(original)
    name, digest = MOUSE_PCM[kind]
    path = SOUND_DIRECTORY / name
    try:
        if (original.is_symlink() or not original.is_file()
                or sha256(original.read_bytes()).hexdigest() != SOUNDS[kind][1]):
            return None
        if path.is_symlink() or not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
            return None
        return path
    except OSError:
        return None


def default_source(kind):
    name, digest, _ = SOUNDS[kind]
    path = SOUND_DIRECTORY / name
    try:
        if path.is_symlink() or not path.is_file() or not 16 <= path.stat().st_size <= 10 * 1024 * 1024:
            return None
        if sha256(path.read_bytes()).hexdigest() != digest:
            return None
        return path
    except OSError:
        return None


def approved_sound_file(path):
    """Only these exact six files may enter a public source/runtime package."""
    path = Path(path)
    expected = {name: digest for name, digest, _ in SOUNDS.values()}
    return (not path.is_symlink() and path.is_file() and path.name in expected
            and sha256(path.read_bytes()).hexdigest() == expected[path.name])
