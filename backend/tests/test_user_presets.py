import pytest

from app.api import routes


def test_user_presets_are_supported_and_scoped():
    assert "user" in routes.SUPPORTED_PRESET_TYPES
    assert "user_name" in routes.USER_PRESET_FIELDS
    assert "llm_model" not in routes.USER_PRESET_FIELDS


@pytest.mark.anyio
async def test_list_presets_exposes_user_but_not_legacy_character(monkeypatch):
    monkeypatch.setattr(
        routes,
        "_load_presets",
        lambda: [
            {"id": "u1", "name": "Personal", "type": "user", "data": {"user_name": "Alex"}},
            {"id": "c1", "name": "Legacy Character", "type": "character", "data": {}},
        ],
    )

    presets = await routes.list_presets()

    assert [preset["id"] for preset in presets] == ["u1"]
