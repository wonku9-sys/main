"""No proprietary game bytes: synthetic headers/archives test local launching."""
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile
import pytest
from pos2.rom_library import RomLibrary,validate_rom,APPROVED


def nes(path):
    path.write_bytes(b'NES\x1a'+bytes([1,0])+bytes(10)+bytes(16384));return path


def test_library_has_six_approved_titles_without_bundled_roms(tmp_path):
    library=RomLibrary(tmp_path/'library');rows=library.rows()
    assert len(rows)==6 and all(not row['registered'] for row in rows)
    assert len({row['digest'] for row in rows})==6
    assert any(row['platform']=='snes' and '월드' in row['title'] for row in rows)
    assert not library.root.exists()


def test_nes_import_is_idempotent_and_does_not_move_original(tmp_path):
    source=nes(tmp_path/'내 게임.nes');original=source.read_bytes();library=RomLibrary(tmp_path/'library')
    digest=library.register(source);assert library.register(source)==digest and source.read_bytes()==original
    assert digest==sha256(original).hexdigest()
    row=next(row for row in library.rows() if row['registered']);assert row['filename']=='내 게임.nes'
    with pytest.raises(ValueError,match='실행기'):library.command(digest)
    emulator=tmp_path/'실행기.exe';emulator.write_bytes(b'SYNTHETIC-NOT-AN-EXECUTABLE')
    library.set_emulator('nes',emulator);program,args=library.command(digest)
    assert program==str(emulator.resolve()) and len(args)==1 and Path(args[0]).read_bytes()==original
    library.record_score(digest,'점주',999);assert library.load()['games'][digest]['best']==999
    with pytest.raises(ValueError):library.record_score(digest,'점주',-1)


def test_arcade_zip_is_kept_whole_and_mame_command_has_safe_argv(tmp_path):
    source=tmp_path/'bublbobl.zip'
    with ZipFile(source,'w') as z:z.writestr('synthetic.rom',b'not-a-commercial-ROM')
    library=RomLibrary(tmp_path/'library');digest=library.register(source)
    emulator=tmp_path/'mame.exe';emulator.write_bytes(b'FAKE-NOT-EXECUTABLE');library.set_emulator('arcade',emulator)
    program,args=library.command(digest)
    assert args[0]=='bublbobl' and args[1]=='-rompath' and args[-1]=='-window'
    assert not (library.root/'synthetic.rom').exists() # Never extract archives.
    target=library.root/'roms'/digest[:16]/source.name;assert target.read_bytes()==source.read_bytes()
    target.write_bytes(b'broken')
    with pytest.raises(ValueError):library.command(digest)


def test_bad_headers_and_zip_traversal_are_rejected_without_copy(tmp_path):
    bad=tmp_path/'bad.nes';bad.write_bytes(b'NES\x1a'+bytes([1,0])+bytes(10))
    with pytest.raises(ValueError):validate_rom(bad)
    archive=tmp_path/'bad.zip'
    with ZipFile(archive,'w') as z:z.writestr('../outside.rom',b'bad')
    library=RomLibrary(tmp_path/'library')
    with pytest.raises(ValueError):library.register(archive)
    assert not library.root.exists()


def test_only_explicit_launch_calls_process_and_counts_request(tmp_path,monkeypatch):
    from pos2 import rom_library
    source=nes(tmp_path/'synthetic.nes');library=RomLibrary(tmp_path/'library');digest=library.register(source)
    emulator=tmp_path/'nes.exe';emulator.write_bytes(b'FAKE');library.set_emulator('nes',emulator)
    called=[]
    monkeypatch.setattr(rom_library.QProcess,'startDetached',lambda *args:(called.append(args) or (True,123)))
    assert not called
    assert library.launch(digest)==123 and len(called)==1 and isinstance(called[0][1],list)
    assert library.load()['games'][digest]['plays']==1


@pytest.mark.parametrize('copier',[False,True])
@pytest.mark.parametrize('suffix',['.smc','.sfc'])
def test_snes_import_header_and_separate_emulator_argv(tmp_path,copier,suffix):
    # Synthetic LoROM header; not game code and never executed.
    data=bytearray(65536);offset=0x7fc0
    data[offset:offset+21]=b'SYNTHETIC SNES TEST'.ljust(21,b' ')
    data[offset+21]=0x20;data[offset+28:offset+32]=bytes.fromhex('cbed3412')
    data[offset+60:offset+62]=bytes.fromhex('0080')
    source=tmp_path/('my game & world'+suffix);source.write_bytes((bytes(512) if copier else b'')+data)
    library=RomLibrary(tmp_path/'library');digest=library.register(source)
    assert validate_rom(source)==('snes',digest)
    emulator=tmp_path/'snes9x.exe';emulator.write_bytes(b'FAKE-NOT-EXECUTABLE')
    library.set_emulator('nes',emulator)
    with pytest.raises(ValueError,match='실행기'):library.command(digest)
    library.set_emulator('snes',emulator);program,args=library.command(digest)
    assert program==str(emulator.resolve()) and len(args)==1
    assert Path(args[0]).read_bytes()==source.read_bytes()
    assert library.register(source)==digest
    damaged=bytearray(source.read_bytes());damaged[(512 if copier else 0)+offset+28]=0
    source.write_bytes(damaged)
    with pytest.raises(ValueError,match='SNES'):validate_rom(source)


def test_snes_random_or_truncated_payload_rejected(tmp_path):
    source=tmp_path/'not-a-game.smc';source.write_bytes(bytes(65536))
    with pytest.raises(ValueError,match='SNES'):validate_rom(source)
    source.write_bytes(bytes(1000))
    with pytest.raises(ValueError,match='SNES'):validate_rom(source)
