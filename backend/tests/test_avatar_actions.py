from app.avatar.actions import AVATAR_GESTURES, choose_avatar_action


def _action(text: str, emotion: str = "curiosity", expressive_label: str | None = None):
    return choose_avatar_action(
        text=text,
        emotion=emotion,
        expressive_label=expressive_label,
        emotion_values={emotion: 0.7},
    )


def test_dialogue_intent_can_trigger_specific_safe_gestures():
    assert _action("Hello everyone!")["gesture"] == "wave"
    assert _action("Yes, you're right.")["gesture"] == "warm_nod"
    assert _action("Nope, absolutely not.")["gesture"] == "firm_shake"
    assert _action("Thank you so much.")["gesture"] == "bow"
    assert _action("Let's dance!")["gesture"] == "dance"
    assert _action("Wink. It's a secret.")["gesture"] == "wink"


def test_expressive_action_wins_over_plain_text_intent():
    assert _action("No, that was funny!", expressive_label="laughing")["gesture"] == "laugh"


def test_actions_stay_inside_the_bounded_renderer_contract():
    action = _action("OH WOW!", emotion="excitement")
    assert action["gesture"] in AVATAR_GESTURES
    assert 0.25 <= action["intensity"] <= 0.9
    assert 300 <= action["hold_ms"] <= 3000
