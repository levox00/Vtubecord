from __future__ import annotations

import unittest

from app.character.profiles import (
    ensure_profile_migration,
    load_trait_library,
    list_profiles,
    parse_profile,
    serialize_profile,
)
from app.core.config import AppConfig, CharacterConfig
from app.schemas.character_profile import AppearanceProfile, CharacterProfileBase


class CharacterProfileTests(unittest.TestCase):
    def test_markdown_round_trip_preserves_structured_fields(self) -> None:
        profile = CharacterProfileBase(
            name="Mira",
            gender="Non-binary",
            pronouns="they/them",
            response_style="Professional",
            style_modifiers=["Detailed"],
            traits=["analytical"],
            dere_types=["kuudere"],
            appearance=AppearanceProfile(hair="silver", visual_style="Anime"),
            description="A careful guide.",
            behavior_rules="Respect boundaries.",
            custom_instructions="Use clear headings.",
        )
        parsed = parse_profile(serialize_profile("mira", profile), "mira")
        self.assertEqual(parsed.name, "Mira")
        self.assertEqual(parsed.appearance.hair, "silver")
        self.assertEqual(parsed.response_style, "Professional")
        self.assertEqual(parsed.dere_types, ["kuudere"])
        self.assertEqual(parsed.behavior_rules, "Respect boundaries.")

    def test_invalid_markdown_front_matter_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_profile("# Not a profile", "broken")

    def test_existing_migration_is_idempotent(self) -> None:
        config = AppConfig(character=CharacterConfig(name="Aiko", profiles_dir="data/character-profiles"))
        first = ensure_profile_migration(config)
        second = ensure_profile_migration(config)
        profiles = list_profiles(config)
        self.assertEqual(first, second)
        self.assertTrue(any(profile_id == "1293fc83" for profile_id, _, _ in profiles))

    def test_trait_library_contains_a_to_z_and_dere_options(self) -> None:
        library = load_trait_library()
        categories = {option.category for option in library.traits}
        self.assertIn("A", categories)
        self.assertIn("Z", categories)
        self.assertIn("tsundere", {option.id for option in library.dere_types})
        self.assertIn("kuudere", {option.id for option in library.dere_types})


if __name__ == "__main__":
    unittest.main()
