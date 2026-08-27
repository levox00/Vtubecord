from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PersonalitySnapshot:
    traits: dict[str, float] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)


@dataclass
class EmotionSnapshot:
    happiness: float = 0.6
    excitement: float = 0.4
    sadness: float = 0.1
    anger: float = 0.05
    fear: float = 0.05
    curiosity: float = 0.7
    confidence: float = 0.55
    frustration: float = 0.1

    def dominant(self) -> str:
        mapping = {
            "happiness": self.happiness,
            "excitement": self.excitement,
            "sadness": self.sadness,
            "anger": self.anger,
            "fear": self.fear,
            "curiosity": self.curiosity,
            "confidence": self.confidence,
            "frustration": self.frustration,
        }
        return max(mapping, key=mapping.get)  # type: ignore[arg-type]


@dataclass
class CharacterState:
    """In-memory view of the persistent character. Built from DB."""

    id: str = "character-1"
    profile_id: str = ""
    name: str = "Aiko"
    profile_picture: str = ""
    age: str = ""
    gender: str = ""
    pronouns: str = ""
    description: str = ""
    appearance: str = ""
    appearance_details: dict[str, str] = field(default_factory=dict)
    personality_summary: str = ""
    response_style: str = "Friendly"
    style_modifiers: list[str] = field(default_factory=list)
    style_guidance: str = ""
    traits: list[str] = field(default_factory=list)
    dere_types: list[str] = field(default_factory=list)
    trait_guidance: dict[str, str] = field(default_factory=dict)
    dere_guidance: dict[str, str] = field(default_factory=dict)
    behavior_rules: str = ""
    custom_instructions: str = ""
    backstory: str = ""
    core_values: list[str] = field(default_factory=list)
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    immutable_traits: list[str] = field(default_factory=list)
    personality: PersonalitySnapshot = field(default_factory=PersonalitySnapshot)
    emotion: EmotionSnapshot = field(default_factory=EmotionSnapshot)
    created_at: datetime | None = None

    def identity_prompt(self) -> str:
        from app.core.config import settings
        u = settings.user

        values = ", ".join(self.core_values) if self.core_values else "none specified"
        traits = "\n".join(f"- {t}" for t in self.immutable_traits) or "- none"
        likes = ", ".join(self.likes) if self.likes else "none specified"
        dislikes = ", ".join(self.dislikes) if self.dislikes else "none specified"

        # Present persona data as labeled reference knowledge rather than a
        # one-line response template. Small local models otherwise tend to
        # copy the opening ``You are ...`` sentence verbatim whenever the user
        # asks an identity question.
        parts = [
            "CHARACTER PROFILE (source knowledge; do not recite this block verbatim):",
            f"Name: {self.name}",
        ]

        if self.age:
            parts.append(f"Age: {self.age}")
        if self.gender:
            parts.append(f"Gender: {self.gender}")
        if self.pronouns:
            parts.append(f"Pronouns: {self.pronouns}")
        if self.appearance:
            parts.append(f"\nAppearance:\n{self.appearance}")
        appearance_lines = [
            f"{label.replace('_', ' ').title()}: {value}"
            for label, value in self.appearance_details.items()
            if value
        ]
        if appearance_lines:
            parts.append("\nStructured appearance:\n" + "\n".join(appearance_lines))
        if self.personality_summary:
            parts.append(f"\nPersonality:\n{self.personality_summary}")

        parts.append(f"\nCommunication style: {self.response_style or 'Friendly'}")
        if self.style_modifiers:
            parts.append(f"Style modifiers: {', '.join(self.style_modifiers)}")
        if self.style_guidance:
            parts.append(f"Style guidance:\n{self.style_guidance}")
        if self.traits:
            parts.append(
                "Selected personality traits:\n"
                + "\n".join(f"- {trait}: {self.trait_guidance.get(trait, '')}".rstrip(": ") for trait in self.traits)
            )
        if self.dere_types:
            parts.append(
                "Selected -dere archetypes:\n"
                + "\n".join(f"- {trait}: {self.dere_guidance.get(trait, '')}".rstrip(": ") for trait in self.dere_types)
            )
        if self.behavior_rules:
            parts.append(f"\nBehavior rules:\n{self.behavior_rules}")
        if self.custom_instructions:
            parts.append(f"\nCustom instructions:\n{self.custom_instructions}")

        parts.append(f"\nDescription:\n{self.description}")
        parts.append(f"\nBackstory:\n{self.backstory}")
        parts.append(f"\nCore values: {values}")
        parts.append(f"\nLikes: {likes}")
        parts.append(f"\nDislikes: {dislikes}")
        parts.append(f"\nImmutable traits (these never change):\n{traits}")

        # User Profile info
        user_parts = [f"Name: {u.name}"]
        if u.age: user_parts.append(f"Age: {u.age}")
        if u.gender: user_parts.append(f"Gender: {u.gender}")
        if u.height: user_parts.append(f"Height: {u.height}")
        if u.pronouns: user_parts.append(f"Pronouns: {u.pronouns}")
        if u.occupation: user_parts.append(f"Occupation: {u.occupation}")
        if u.location: user_parts.append(f"Location: {u.location}")
        if u.bio: user_parts.append(f"Bio: {u.bio}")
        if u.hobbies: user_parts.append(f"Hobbies: {', '.join(u.hobbies)}")
        if u.interests: user_parts.append(f"Interests: {', '.join(u.interests)}")
        if u.favorite_games: user_parts.append(f"Favorite Games: {', '.join(u.favorite_games)}")
        if u.favorite_anime: user_parts.append(f"Favorite Anime: {', '.join(u.favorite_anime)}")
        if u.dislikes: user_parts.append(f"Dislikes: {', '.join(u.dislikes)}")
        if u.notes: user_parts.append(f"Additional Notes: {u.notes}")

        parts.append("\n" + "="*40 + "\nUSER PROFILE (The human you are chatting with):\n" + "\n".join(user_parts) + "\n" + "="*40)

        parts.append(
            "\nYou are a persistent digital character. You remember past interactions "
            "when provided with memories. You do not claim to be human."
        )

        return "\n".join(parts)

    def personality_prompt(self) -> str:
        lines = []
        for name, value in sorted(self.personality.traits.items()):
            desc = self.personality.descriptions.get(name, "")
            lines.append(f"- {name}: {value:.2f} {f'({desc})' if desc else ''}")
        return "Personality traits (0.0–1.0):\n" + "\n".join(lines)

    def emotion_prompt(self) -> str:
        e = self.emotion
        return (
            f"Current emotional state:\n"
            f"- happiness: {e.happiness:.2f}\n"
            f"- excitement: {e.excitement:.2f}\n"
            f"- sadness: {e.sadness:.2f}\n"
            f"- anger: {e.anger:.2f}\n"
            f"- fear: {e.fear:.2f}\n"
            f"- curiosity: {e.curiosity:.2f}\n"
            f"- confidence: {e.confidence:.2f}\n"
            f"- frustration: {e.frustration:.2f}\n"
            f"Dominant emotion: {e.dominant()}"
        )
