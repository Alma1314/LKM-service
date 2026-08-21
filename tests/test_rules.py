from app.modules.points.rules import RULE_DELTAS


def test_rules_deltas():
    assert RULE_DELTAS["post"] == 10
    assert RULE_DELTAS["comment"] == 2
    assert RULE_DELTAS["like"] == 1
    assert RULE_DELTAS["file_approved"] == 15
    assert RULE_DELTAS["answer_accepted"] == 0
    assert RULE_DELTAS["checkin"] == 5
    assert RULE_DELTAS["competition"] == 50
