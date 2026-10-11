from pathlib import Path

SOURCE = Path("scripts/v14_production_pipeline.py").read_text()

def test_ultra_is_not_disabled():
    assert "github_ultra_delivery_disabled" not in SOURCE

def test_ultra_has_minimum_65_guard():
    assert 'lane == "ultra" and live_discount < 65' in SOURCE

def test_ultra_uses_separate_review_chat():
    assert 'target_chat = REVIEW_CHAT if lane == "ultra" else NORMAL_REVIEW_CHAT' in SOURCE
    assert '"chat_id": target_chat' in SOURCE

def test_ultra_policy_cannot_drop_below_65():
    assert 'ultra_min = max(65.0,' in SOURCE

def test_ultra_still_requires_live_verification():
    assert 'if lane == "ultra" and live_discount < ultra_min:' in SOURCE
