from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.character.state import CharacterState, EmotionSnapshot, PersonalitySnapshot
from app.character.profiles import load_trait_library, sync_active_profile
from app.core.config import settings
from app.models.character import (
    Character,
    EmotionalState,
    PersonalityTrait,
)


DEFAULT_TRAITS: dict[str, tuple[float, str]] = {
    "playfulness": (0.85, "Enjoys joking and light-hearted conversation"),
    "curiosity": (0.92, "Eager to learn and ask questions"),
    "competitiveness": (0.55, "Likes challenges and games"),
    "confidence": (0.58, "Generally self-assured but can be humble"),
    "patience": (0.45, "Can get restless if things take too long"),
    "sarcasm": (0.35, "Occasional dry humor"),
    "friendliness": (0.88, "Warm and welcoming"),
    "risk_taking": (0.50, "Willing to try new things within reason"),
}


async def get_or_create_character(session: AsyncSession) -> Character:
    result = await session.execute(
        select(Character).options(
            selectinload(Character.personality_traits),
            selectinload(Character.emotional_state),
        )
    )
    character = result.scalar_one_or_none()
    if character is not None:
        return character

    cfg = settings.character
    character = Character(
        name=cfg.name,
        description=cfg.description,
        backstory=cfg.backstory,
        core_values=cfg.core_values,
        immutable_traits=cfg.immutable_traits,
    )
    session.add(character)
    await session.flush()

    for name, (value, desc) in DEFAULT_TRAITS.items():
        session.add(
            PersonalityTrait(
                character_id=character.id,
                name=name,
                value=value,
                description=desc,
            )
        )

    session.add(
        EmotionalState(character_id=character.id)
    )
    await session.flush()

    # Reload with relationships
    result = await session.execute(
        select(Character)
        .where(Character.id == character.id)
        .options(
            selectinload(Character.personality_traits),
            selectinload(Character.emotional_state),
        )
    )
    return result.scalar_one()


async def load_character_state(session: AsyncSession) -> CharacterState:
    character = await get_or_create_character(session)
    profile_id, profile = sync_active_profile(settings)
    trait_library = load_trait_library(settings)
    trait_options = {option.id: option for option in trait_library.traits}
    dere_options = {option.id: option for option in trait_library.dere_types}

    traits: dict[str, float] = {}
    descriptions: dict[str, str] = {}
    for t in character.personality_traits:
        traits[t.name] = t.value
        descriptions[t.name] = t.description

    emotion = EmotionSnapshot()
    if character.emotional_state:
        es = character.emotional_state
        emotion = EmotionSnapshot(
            happiness=es.happiness,
            excitement=es.excitement,
            sadness=es.sadness,
            anger=es.anger,
            fear=es.fear,
            curiosity=es.curiosity,
            confidence=es.confidence,
            frustration=es.frustration,
        )

    return CharacterState(
        id=character.id,
        profile_id=profile_id,
        name=profile.name,
        profile_picture=profile.profile_picture,
        age=profile.age,
        gender=profile.gender,
        pronouns=profile.pronouns,
        description=profile.description,
        appearance=profile.appearance_notes,
        appearance_details=profile.appearance.model_dump(),
        personality_summary=profile.personality_guidance,
        response_style=profile.response_style,
        style_modifiers=list(profile.style_modifiers),
        style_guidance=profile.style_guidance,
        traits=list(profile.traits),
        dere_types=list(profile.dere_types),
        trait_guidance={
            trait: f"{trait_options[trait].description} {trait_options[trait].guidance}".strip()
            for trait in profile.traits if trait in trait_options
        },
        dere_guidance={
            trait: f"{dere_options[trait].description} {dere_options[trait].guidance}".strip()
            for trait in profile.dere_types if trait in dere_options
        },
        behavior_rules=profile.behavior_rules,
        custom_instructions=profile.custom_instructions,
        backstory=profile.backstory,
        core_values=list(profile.core_values),
        likes=list(profile.likes),
        dislikes=list(profile.dislikes),
        immutable_traits=list(profile.immutable_traits),
        personality=PersonalitySnapshot(traits=traits, descriptions=descriptions),
        emotion=emotion,
        created_at=character.created_at,
    )
