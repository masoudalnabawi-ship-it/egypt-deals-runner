import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))
from health import assess, save_health


def test_no_candidates():
    assert assess({'discovered': 0, 'probed': 0})['status'] == 'NO_CANDIDATES'


def test_probe_failure():
    assert assess({'discovered': 4, 'probed': 0})['status'] == 'NO_VERIFIED_PROBES'


def test_partial_failure():
    assert assess({'discovered': 4, 'probed': 2, 'failures': [{'reason': 'TimeoutError'}]})['status'] == 'PARTIAL_FAILURE'


def test_healthy():
    assert assess({'discovered': 4, 'probed': 2, 'failures': []})['status'] == 'OK'


def test_atomic_output(tmp_path):
    target = tmp_path / 'nested' / 'health.json'
    save_health(target, assess({'discovered': 0}))
    assert json.loads(target.read_text())['status'] == 'NO_CANDIDATES'
    assert not list(target.parent.glob('.v16-health-*'))
