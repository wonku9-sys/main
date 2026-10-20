"""Decode the shipped MP3s to PCM, without a speaker or a playback device."""
from .audio_defaults import SOUNDS, default_source


def verify_default_audio():
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtMultimedia import QAudioDecoder
    results = {}
    for kind in SOUNDS:
        source = default_source(kind)
        if source is None:
            raise RuntimeError(f'Missing or altered default audio: {kind}')
        decoder = QAudioDecoder()
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        frames, errors = [], []

        def read_buffer():
            frames.append(decoder.read().frameCount())

        def failed(*_):
            errors.append(decoder.errorString())
            loop.quit()

        def timed_out():
            errors.append('decode timeout')
            loop.quit()

        decoder.bufferReady.connect(read_buffer)
        decoder.finished.connect(loop.quit)
        decoder.error.connect(failed)
        timer.timeout.connect(timed_out)
        decoder.setSource(QUrl.fromLocalFile(str(source)))
        decoder.start()
        timer.start(5000)
        loop.exec()
        timer.stop()
        decoder.stop()
        if errors or not sum(frames):
            raise RuntimeError(f'Cannot decode default audio {kind}: {errors}')
        results[kind] = sum(frames)
    return results
