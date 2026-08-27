import asyncio

import app.api.routes as routes


def _restore_settings(snapshot) -> None:
    for field_name in snapshot.__class__.model_fields:
        setattr(routes.settings, field_name, getattr(snapshot, field_name))


def test_channel_master_runtime_is_overlaid_and_restored(monkeypatch):
    snapshot = routes.settings.model_copy(deep=True)
    monkeypatch.setattr(
        routes,
        "_load_presets",
        lambda: [
            {"id": "master-1", "type": "master", "data": {"llm_preset_id": "llm-1"}},
            {"id": "llm-1", "type": "llm", "data": {"llm_model": "channel-model.gguf"}},
        ],
    )
    try:
        async def exercise():
            async with routes._channel_runtime_scope("master-1"):
                assert routes.settings.llm.model == "channel-model.gguf"
                # No avatar component means the channel deliberately uses the orb.
                assert routes.settings.avatar.model == ""

        asyncio.run(exercise())
        assert routes.settings.llm.model == snapshot.llm.model
        assert routes.settings.avatar.model == snapshot.avatar.model
    finally:
        _restore_settings(snapshot)


def test_resolved_master_data_keeps_child_component_values(monkeypatch):
    monkeypatch.setattr(
        routes,
        "_load_presets",
        lambda: [
            {
                "id": "master-2",
                "type": "master",
                "data": {"llm_preset_id": "llm-2", "avatar_preset_id": "avatar-2"},
            },
            {"id": "llm-2", "type": "llm", "data": {"llm_model": "chat.gguf"}},
            {
                "id": "avatar-2",
                "type": "avatar",
                "data": {
                    "avatar_model": "/live2d/chat.model3.json",
                    "avatar_idle_preset": "neuro_subtle",
                },
            },
        ],
    )
    data, profile_id = routes._resolve_master_runtime("master-2")
    assert data["llm_model"] == "chat.gguf"
    assert data["avatar_model"] == "/live2d/chat.model3.json"
    assert data["avatar_idle_preset"] == "neuro_subtle"
    assert data["_channel_avatar_specified"] is True
    assert profile_id is None
