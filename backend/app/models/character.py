from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Character(Base):
    """Persistent character identity. Survives LLM swaps."""

    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    backstory: Mapped[str] = mapped_column(Text, default="")
    core_values: Mapped[list] = mapped_column(JSON, default=list)
    immutable_traits: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    personality_traits: Mapped[list[PersonalityTrait]] = relationship(
        back_populates="character", cascade="all, delete-orphan"
    )
    emotional_state: Mapped[EmotionalState | None] = relationship(
        back_populates="character", uselist=False, cascade="all, delete-orphan"
    )
    conversations: Mapped[list[Conversation]] = relationship(back_populates="character")


class PersonalityTrait(Base):
    """Numeric personality trait (0.0 – 1.0)."""

    __tablename__ = "personality_traits"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    description: Mapped[str] = mapped_column(Text, default="")

    character: Mapped[Character] = relationship(back_populates="personality_traits")


class PersonalityChange(Base):
    """Historical record of accepted personality updates."""

    __tablename__ = "personality_changes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    trait_name: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[float] = mapped_column(Float, nullable=False)
    new_value: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EmotionalState(Base):
    """Current short-term emotional state (0.0 – 1.0 each)."""

    __tablename__ = "emotional_states"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), unique=True
    )
    happiness: Mapped[float] = mapped_column(Float, default=0.6)
    excitement: Mapped[float] = mapped_column(Float, default=0.4)
    sadness: Mapped[float] = mapped_column(Float, default=0.1)
    anger: Mapped[float] = mapped_column(Float, default=0.05)
    fear: Mapped[float] = mapped_column(Float, default=0.05)
    curiosity: Mapped[float] = mapped_column(Float, default=0.7)
    confidence: Mapped[float] = mapped_column(Float, default=0.55)
    frustration: Mapped[float] = mapped_column(Float, default=0.1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    character: Mapped[Character] = relationship(back_populates="emotional_state")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(256), default="Conversation")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    character: Mapped[Character] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    emotion: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Memory(Base):
    """Persistent memory record for the character."""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    memory_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # short_term | episodic | semantic | relationship | skill | experience
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    pinned: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_accessed: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Goal(Base):
    """Character goal — something the character is working toward."""

    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(32), default="active"
    )  # active | completed | abandoned
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Skill(Base):
    """Character skill — learned capability with proficiency level."""

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    proficiency: Mapped[float] = mapped_column(Float, default=0.5)
    experience: Mapped[int] = mapped_column(Integer, default=0)
    last_used: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VoiceBrainSession(Base):
    """Durable executive state for one Discord or web live-voice surface."""

    __tablename__ = "voice_brain_sessions"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    character_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False
    )
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_key: Mapped[str] = mapped_column(String(256), default="")
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    phase: Mapped[str] = mapped_column(String(32), default="listening")
    internal_state: Mapped[dict] = mapped_column(JSON, default=dict)
    conversation_summary: Mapped[str] = mapped_column(Text, default="")
    open_loops: Mapped[list] = mapped_column(JSON, default=list)
    turns_since_summary: Mapped[int] = mapped_column(Integer, default=0)
    proactive_turns_in_window: Mapped[int] = mapped_column(Integer, default=0)
    proactive_window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_user_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ai_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VoiceBrainEvent(Base):
    """Bounded audit trail of perceptions and executive decisions."""

    __tablename__ = "voice_brain_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("voice_brain_sessions.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="runtime")
    priority: Mapped[int] = mapped_column(Integer, default=50)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="observed")
    decision: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VoiceBrainInteraction(Base):
    """Training/evaluation record without automatically modifying the model."""

    __tablename__ = "voice_brain_interactions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(256), ForeignKey("voice_brain_sessions.id", ondelete="CASCADE"), nullable=False
    )
    trigger_event_ids: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[str] = mapped_column(Text, default="")
    delivery: Mapped[dict] = mapped_column(JSON, default=dict)
    evaluation: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Forward refs resolved by SQLAlchemy
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    pass
