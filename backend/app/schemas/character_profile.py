from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AppearanceProfile(BaseModel):
    height: str = ""
    build: str = ""
    hair: str = ""
    eyes: str = ""
    skin_or_fur: str = ""
    clothing: str = ""
    accessories: str = ""
    distinguishing_features: str = ""
    visual_style: str = ""
    notes: str = ""


class CharacterProfileBase(BaseModel):
    name: str = "New Character"
    profile_picture: str = ""
    age: str = ""
    gender: str = ""
    pronouns: str = ""
    response_style: str = "Friendly"
    style_modifiers: list[str] = Field(default_factory=list)
    style_guidance: str = ""
    traits: list[str] = Field(default_factory=list)
    dere_types: list[str] = Field(default_factory=list)
    core_values: list[str] = Field(default_factory=list)
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    immutable_traits: list[str] = Field(default_factory=list)
    description: str = ""
    personality_guidance: str = ""
    appearance: AppearanceProfile = Field(default_factory=AppearanceProfile)
    appearance_notes: str = ""
    backstory: str = ""
    behavior_rules: str = ""
    custom_instructions: str = ""


class CharacterProfileCreate(CharacterProfileBase):
    id: str | None = None


class CharacterProfileUpdate(BaseModel):
    name: str | None = None
    profile_picture: str | None = None
    age: str | None = None
    gender: str | None = None
    pronouns: str | None = None
    response_style: str | None = None
    style_modifiers: list[str] | None = None
    style_guidance: str | None = None
    traits: list[str] | None = None
    dere_types: list[str] | None = None
    core_values: list[str] | None = None
    likes: list[str] | None = None
    dislikes: list[str] | None = None
    immutable_traits: list[str] | None = None
    description: str | None = None
    personality_guidance: str | None = None
    appearance: AppearanceProfile | None = None
    appearance_notes: str | None = None
    backstory: str | None = None
    behavior_rules: str | None = None
    custom_instructions: str | None = None


class CharacterProfilePublic(CharacterProfileBase):
    id: str
    source_file: str
    active: bool = False


class TraitOption(BaseModel):
    id: str
    label: str
    category: str
    description: str = ""
    guidance: str = ""
    tags: list[str] = Field(default_factory=list)


class CharacterTraitLibrary(BaseModel):
    styles: list[str] = Field(default_factory=list)
    style_modifiers: list[str] = Field(default_factory=list)
    traits: list[TraitOption] = Field(default_factory=list)
    dere_types: list[TraitOption] = Field(default_factory=list)
    core_values: list[str] = Field(default_factory=list)
    immutable_traits: list[str] = Field(default_factory=list)
    appearance_options: dict[str, list[str]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
