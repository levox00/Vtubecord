import pytest

from app.api.character_profiles import _merge_profile_update, _update_character_message_names
from app.schemas.character_profile import AppearanceProfile, CharacterProfileBase


def test_profile_update_rehydrates_nested_appearance():
    current = CharacterProfileBase(name="Neuro", appearance=AppearanceProfile(eyes="blue"))

    updated = _merge_profile_update(
        current,
        {
            "appearance": {
                "height": "tall",
                "hair": "purple",
            }
        },
    )

    assert isinstance(updated.appearance, AppearanceProfile)
    assert updated.appearance.height == "tall"
    assert updated.appearance.hair == "purple"
    assert updated.appearance.eyes == "blue"


def test_profile_update_preserves_unmodified_fields():
    current = CharacterProfileBase(
        name="Neuro",
        response_style="Playful",
        traits=["witty"],
        appearance=AppearanceProfile(eyes="blue"),
    )

    updated = _merge_profile_update(current, {"name": "Neuro SAMA"})

    assert updated.name == "Neuro SAMA"
    assert updated.response_style == "Playful"
    assert updated.traits == ["witty"]
    assert updated.appearance.eyes == "blue"


@pytest.mark.anyio
async def test_renaming_profile_updates_only_matching_message_snapshots():
    class Result:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return self

        def all(self):
            return self.rows

    class Session:
        def __init__(self, rows):
            self.rows = rows

        async def execute(self, _query):
            return Result(self.rows)

    class MessageSnapshot:
        def __init__(self, profile_id, name):
            self.metadata_ = {"character_profile_id": profile_id, "character_name": name}

    matching = MessageSnapshot("neuro-sama", "Neuro")
    other = MessageSnapshot("aiko", "Aiko")

    changed = await _update_character_message_names(
        Session([matching, other]), "neuro-sama", "Neuro SAMA"
    )

    assert changed == 1
    assert matching.metadata_["character_name"] == "Neuro SAMA"
    assert other.metadata_["character_name"] == "Aiko"
