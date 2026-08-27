from __future__ import annotations

"""Convert conversational intent into a tiny, model-agnostic avatar API.

The renderer is the sole owner of Cubism parameter IDs.  This module only
returns safe semantic values such as ``look_away`` or ``nod`` so a model can be
swapped without exposing raw parameter controls to an LLM response.
"""

import re
from typing import Mapping

AVATAR_GESTURES = frozenset(
    {
        "wave",
        "warm_nod",
        "celebrate",
        "dance",
        "bow",
        "wink",
        "look_down",
        "firm_shake",
        "recoil",
        "head_tilt",
        "lean_in",
        "look_away",
        "laugh",
    }
)

_EMOTION_GESTURES = {
    "happiness": "warm_nod",
    "excitement": "celebrate",
    "sadness": "look_down",
    "anger": "firm_shake",
    "fear": "recoil",
    "curiosity": "head_tilt",
    "confidence": "lean_in",
    "frustration": "look_away",
}

_EXPRESSIVE_GESTURES = {
    "laughing": "laugh",
    "crying": "look_down",
    "shocked": "recoil",
    "yelling": "firm_shake",
    "panicking": "recoil",
    "blushing": "look_away",
    "smug": "head_tilt",
}

_GESTURE_HOLDS_MS = {
    "wave": 1800,
    "warm_nod": 900,
    "celebrate": 1500,
    "dance": 2400,
    "bow": 1500,
    "wink": 900,
    "look_down": 1800,
    "firm_shake": 1200,
    "recoil": 900,
    "head_tilt": 1600,
    "lean_in": 1300,
    "look_away": 1500,
    "laugh": 1500,
}

_TEXT_GESTURES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:hello|hi|hey|welcome|goodbye|bye|see you)\b", re.I), "wave"),
    (re.compile(r"\b(?:dance|dancing|party|let['’]?s go|music)\b", re.I), "dance"),
    (re.compile(r"\b(?:thank you|thanks|sorry|apolog(?:y|ize|ise))\b", re.I), "bow"),
    (re.compile(r"\b(?:wink|secret|trust me|gotcha)\b", re.I), "wink"),
    (re.compile(r"\b(?:no|nope|never|not happening|absolutely not)\b", re.I), "firm_shake"),
    (re.compile(r"\b(?:yes|yeah|yep|exactly|absolutely|agreed|you['’]?re right)\b", re.I), "warm_nod"),
)


def _gesture_from_text(text: str) -> str | None:
    for pattern, gesture in _TEXT_GESTURES:
        if pattern.search(text):
            return gesture
    return None


def choose_avatar_action(
    *,
    text: str,
    emotion: str,
    expressive_label: str | None,
    emotion_values: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """Return a bounded semantic action for the Live2D front end.

    This is intentionally deterministic today: the LLM changes the character
    state and writes the reply, while the controller makes that result safe and
    consistent for every Cubism model.  The returned schema is deliberately
    suitable for a future structured LLM/tool call without changing the
    renderer contract.
    """
    label = (expressive_label or "").strip().lower() or None
    normalized_emotion = (emotion or "curiosity").strip().lower()
    gesture = (
        _EXPRESSIVE_GESTURES.get(label or "")
        or _gesture_from_text(text)
        or _EMOTION_GESTURES.get(normalized_emotion, "head_tilt")
    )

    strongest = 0.45
    if emotion_values:
        strongest = max((float(value) for value in emotion_values.values()), default=strongest)
    # Punctuation and an expressive label may make the animation a little
    # stronger, never enough to force an uncanny or extreme pose.
    intensity = 0.35 + strongest * 0.45
    if label:
        intensity += 0.12
    if "!" in text:
        intensity += 0.05
    intensity = round(max(0.25, min(0.9, intensity)), 2)

    return {
        "emotion": normalized_emotion,
        "gesture": gesture,
        "intensity": intensity,
        "hold_ms": _GESTURE_HOLDS_MS.get(gesture, 1200),
    }
