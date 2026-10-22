import sys
from types import ModuleType

import pytest

from assemble_windows import ENTRY,assemble


@pytest.mark.parametrize('arguments,explicit',[
    ([],False),(['--smoke-test'],False),(['--data-dir','D:/explicit-test'],True),(['--data-dir=D:/explicit-test'],True),
])
def test_trial_executable_defaults_to_its_own_data_folder_not_installed_user_data(tmp_path,monkeypatch,arguments,explicit):
    executable=tmp_path/'SY-POS'/'runtime'/'pythonw.exe';calls=[]
    module=ModuleType('pos2.app');module.main=lambda argv:calls.append(argv) or 0
    monkeypatch.setitem(sys.modules,'pos2.app',module)
    monkeypatch.setattr(sys,'executable',str(executable));monkeypatch.setattr(sys,'argv',['SY-POS.exe',*arguments])
    with pytest.raises(SystemExit) as result:exec(compile(ENTRY,'trial-launcher','exec'),{})
    assert result.value.code==0 and len(calls)==1
    assert calls[0]==arguments if explicit else calls[0]==['--data-dir',str(tmp_path/'SY-POS'/'trial-data-v2'),*arguments]
    assert not (tmp_path/'SY-POS'/'trial-data-v2').exists()  # wrapper itself writes no business data


@pytest.mark.parametrize('label',['../bad','a/b','a\\b','','-unsafe','x'*81])
def test_delivery_build_label_cannot_escape_output_directory(tmp_path,label):
    with pytest.raises(ValueError,match='build label'):assemble(tmp_path/'runtime',tmp_path/'wheels',tmp_path/'output',label)
    assert not (tmp_path/'output').exists()
