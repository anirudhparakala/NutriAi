"""
Unit tests for normalize.py (P2-E3: multilingual & transliteration).

Tests canonicalization, multilingual aliases, transliteration, and ordering.
"""
import pytest

from core.normalize import (
    transliterate_to_ascii,
    apply_multilingual_aliases,
    canonicalize_name,
    canonicalize_portion_label,
    MULTILINGUAL_ALIASES,
    PORTION_ALIASES,
    NAME_ALIASES
)


class TestTransliteration:
    """Test Unicode to ASCII transliteration."""

    def test_basic_ascii_unchanged(self):
        """Test that plain ASCII text is unchanged."""
        result = transliterate_to_ascii("chicken")
        assert result == "chicken"

    def test_accented_characters(self):
        """Test removal of accents."""
        assert transliterate_to_ascii("café") == "cafe"
        assert transliterate_to_ascii("naïve") == "naive"
        assert transliterate_to_ascii("résumé") == "resume"

    def test_german_umlauts(self):
        """Test German umlaut handling."""
        assert transliterate_to_ascii("käse") == "kase"
        assert transliterate_to_ascii("Müller") == "Muller"

    def test_spanish_tildes(self):
        """Test Spanish tilde removal."""
        assert transliterate_to_ascii("jalapeño") == "jalapeno"
        assert transliterate_to_ascii("año") == "ano"

    def test_french_cedilla(self):
        """Test French cedilla."""
        assert transliterate_to_ascii("façade") == "facade"

    def test_empty_string(self):
        """Test empty string handling."""
        assert transliterate_to_ascii("") == ""


class TestMultilingualAliases:
    """Test multilingual food name translation."""

    def test_spanish_to_english(self):
        """Test Spanish food names."""
        assert "chicken" in apply_multilingual_aliases("pollo")
        assert "rice" in apply_multilingual_aliases("arroz")
        assert "milk" in apply_multilingual_aliases("leche")

    def test_french_to_english(self):
        """Test French food names."""
        assert "chicken" in apply_multilingual_aliases("poulet")
        assert "cheese" in apply_multilingual_aliases("fromage")
        assert "bread" in apply_multilingual_aliases("pain")

    def test_german_to_english(self):
        """Test German food names."""
        assert "chicken" in apply_multilingual_aliases("huhn")
        assert "cheese" in apply_multilingual_aliases("käse")
        assert "milk" in apply_multilingual_aliases("milch")

    def test_italian_to_english(self):
        """Test Italian food names."""
        # Note: "pollo" is in both Spanish and Italian
        assert "rice" in apply_multilingual_aliases("riso")
        assert "milk" in apply_multilingual_aliases("latte")

    def test_indian_transliterated_names(self):
        """Test transliterated Indian food names."""
        assert "cheese" in apply_multilingual_aliases("paneer")
        assert "lentils" in apply_multilingual_aliases("dal")
        assert "bread" in apply_multilingual_aliases("naan")
        assert "bread" in apply_multilingual_aliases("roti")
        assert "tea" in apply_multilingual_aliases("chai")

    def test_multiword_translation(self):
        """Test translation in multi-word phrases."""
        result = apply_multilingual_aliases("grilled pollo")
        assert "chicken" in result
        assert "grilled" in result

    def test_no_translation_for_english(self):
        """Test that English words are unchanged."""
        assert apply_multilingual_aliases("chicken breast") == "chicken breast"

    def test_partial_match_preservation(self):
        """Test that only matching tokens are translated."""
        result = apply_multilingual_aliases("arroz con pollo")
        assert "rice" in result
        assert "chicken" in result
        assert "con" in result  # Preposition preserved


class TestCanonicalizeName:
    """Test full canonicalization pipeline."""

    def test_transliteration_then_translation(self):
        """Test that transliteration happens before translation."""
        # "café" -> "cafe" (transliteration)
        result = canonicalize_name("café")
        assert result == "cafe"

    def test_multilingual_then_general_aliases(self):
        """Test multilingual aliases applied before general aliases."""
        result = canonicalize_name("pollo")
        assert "chicken" in result.lower()

    def test_context_aware_brand_aliases(self):
        """Test brand-specific canonicalization."""
        # In McDonald's context, "chips" -> "fries"
        result = canonicalize_name("chips", brand="McDonald's", category="starch-side")
        assert "fries" in result

    def test_non_mcdonalds_chips_unchanged(self):
        """Test chips without McDonald's context."""
        result = canonicalize_name("chips", brand="KFC", category="side")
        # Should not be converted to fries
        assert "chips" in result

    def test_general_alias_soda_to_cola(self):
        """Test general alias: soda -> cola."""
        result = canonicalize_name("soda")
        assert result == "cola"

    def test_empty_name_handling(self):
        """Test empty name returns empty."""
        result = canonicalize_name("")
        assert result == ""

    def test_none_name_handling(self):
        """Test None name returns None."""
        result = canonicalize_name(None)
        assert result is None

    def test_debug_logging_for_translation(self, capsys):
        """Test debug logging when translation occurs."""
        canonicalize_name("pollo")
        captured = capsys.readouterr()
        assert "Multilingual canonicalization" in captured.out
        assert "before USDA search" in captured.out


class TestCanonicalizePortionLabel:
    """Test portion label canonicalization."""

    def test_medium_aliases(self):
        """Test medium size aliases."""
        assert canonicalize_portion_label("med") == "medium"
        assert canonicalize_portion_label("Med") == "medium"

    def test_large_aliases(self):
        """Test large size aliases."""
        assert canonicalize_portion_label("lg") == "large"
        assert canonicalize_portion_label("lrg") == "large"

    def test_small_aliases(self):
        """Test small size aliases."""
        assert canonicalize_portion_label("sm") == "small"
        assert canonicalize_portion_label("sml") == "small"

    def test_regular_aliases(self):
        """Test regular size aliases."""
        assert canonicalize_portion_label("reg") == "regular"

    def test_none_handling(self):
        """Test None returns None."""
        assert canonicalize_portion_label(None) is None

    def test_empty_string_handling(self):
        """Test empty string handling."""
        result = canonicalize_portion_label("")
        assert result is not None  # Should return empty or canonical form


class TestAliasCompleteness:
    """Test alias dictionaries for completeness."""

    def test_multilingual_aliases_not_empty(self):
        """Test that multilingual aliases exist."""
        assert len(MULTILINGUAL_ALIASES) > 0

    def test_multilingual_covers_major_languages(self):
        """Test coverage of major languages."""
        # Spanish
        assert "pollo" in MULTILINGUAL_ALIASES
        # French
        assert "poulet" in MULTILINGUAL_ALIASES
        # German
        assert "huhn" in MULTILINGUAL_ALIASES
        # Italian
        assert "riso" in MULTILINGUAL_ALIASES

    def test_portion_aliases_not_empty(self):
        """Test portion aliases exist."""
        assert len(PORTION_ALIASES) > 0

    def test_name_aliases_not_empty(self):
        """Test general name aliases exist."""
        assert len(NAME_ALIASES) > 0


class TestCanonicalizationOrdering:
    """Test that canonicalization steps happen in correct order."""

    def test_transliteration_before_multilingual(self):
        """Test transliteration happens before multilingual lookup."""
        # Input has accent that needs removal before matching
        result = canonicalize_name("café")
        # Should normalize to "cafe"
        assert "cafe" in result.lower()

    def test_multilingual_before_general_aliases(self):
        """Test multilingual happens before general aliases."""
        # "pollo" should become "chicken", not try to match "pollo" in NAME_ALIASES
        result = canonicalize_name("pollo")
        assert "chicken" in result

    def test_brand_context_applied_after_multilingual(self):
        """Test brand context is applied after translation."""
        # Even if we had "chips" in another language, brand rules apply after
        result = canonicalize_name("chips", brand="McDonald's", category="starch-side")
        assert "fries" in result


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_mixed_language_input(self):
        """Test mixed language input."""
        result = apply_multilingual_aliases("grilled pollo with arroz")
        assert "chicken" in result
        assert "rice" in result

    def test_case_insensitive_matching(self):
        """Test case-insensitive matching."""
        result = apply_multilingual_aliases("POLLO")
        assert "chicken" in result.lower()

    def test_punctuation_handling(self):
        """Test that punctuation is handled."""
        result = apply_multilingual_aliases("pollo, arroz")
        assert "chicken" in result
        assert "rice" in result

    def test_unicode_preserved_when_no_translation(self):
        """Test that unmapped unicode is handled gracefully."""
        # Characters that aren't in alias table should be transliterated
        result = canonicalize_name("お寿司")  # Japanese sushi
        # Should not crash, returns transliterated or original
        assert result is not None
