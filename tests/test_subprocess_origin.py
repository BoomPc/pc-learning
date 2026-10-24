"""A caller's checkout must not silently replace child-process implementations."""
import sys
from pathlib import Path
from math_agent.tools import dispatch
from math_agent.rendering import render
from math_agent.worker import supervise
from math_agent.config import ROOT


def shadow_checkout(tmp_path,monkeypatch):
    fake=tmp_path/'math_agent';fake.mkdir()
    (fake/'__init__.py').write_text("raise RuntimeError('wrong checkout imported')")
    monkeypatch.chdir(tmp_path)


def test_math_and_renderer_use_own_checkout_from_shadow_cwd(tmp_path,monkeypatch,sample):
    shadow_checkout(tmp_path,monkeypatch)
    result=dispatch('symbolic_geometry',{'points':{'A':[0,0],'B':[3,4]},'constructions':[],
        'measurements':[{'kind':'distance_squared','points':['A','B']}]})
    assert result['ok'] and result['measurements'][0]['value']=='25'
    render(sample[1]['spec'],Path('relative-output'),validate_only=True)
    assert (tmp_path/'relative-output/spec.json').exists()


def test_worker_child_imports_parent_checkout(tmp_path,monkeypatch,settings,job):
    shadow_checkout(tmp_path,monkeypatch)
    marker=tmp_path/'origin.txt'
    command=[sys.executable,'-c',f"from math_agent.config import ROOT;from pathlib import Path;Path({str(marker)!r}).write_text(str(ROOT))"]
    supervise(settings,job[0],job[1],lambda:False,lambda:None,command=command)
    assert marker.read_text()==str(ROOT)
