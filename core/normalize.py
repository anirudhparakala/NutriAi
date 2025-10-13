"""
Post-LLM canonicalizer: Normalizes ingredient names deterministically after LLM parsing.

Reduces LLM surface area by handling common variations in code instead of prompts.
"""
import re
import unicodedata
from typing import Optional


# Portion label normalization
PORTION_ALIASES = {
    "med": "medium",
    "lg": "large",
    "sm": "small",
    "reg": "regular",
    "lrg": "large",
    "sml": "small",
}

# Name aliases (context-free)
NAME_ALIASES = {
    "soda": "cola",
    "pop": "cola",
    "coke": "cola",
    "chips": "fries",  # Only in fast-food context (McDonald's, etc.)
    "french fries": "fries",
    "potato fries": "fries",
    # Protein powder variants
    "whey protein": "protein powder (whey)",
    "whey powder": "protein powder (whey)",
    "protein shake powder": "protein powder (whey)",
    "casein protein": "protein powder (casein)",
    "plant protein": "protein powder (plant)",
    "pea protein": "protein powder (plant)",
    # Milk variants
    "whole milk": "milk (whole)",
    "2% milk": "milk (2%)",
    "skim milk": "milk (skim)",
    "nonfat milk": "milk (skim)",
    "fat free milk": "milk (skim)",
}

# Negative checks: if these words appear, DOWN-RANK or reject certain matches
EXCLUSION_MODIFIERS = {
    "sweet": ["fries", "potato"],  # "sweet potato" should NOT match "potato"
    "veggie": ["burger"],  # "veggie burger" should NOT match regular "burger"
}

# Multilingual aliases (P2-E3) - Common food names in other languages/scripts
MULTILINGUAL_ALIASES = {
    # Spanish
    "pollo": "chicken",
    "arroz": "rice",
    "leche": "milk",
    "queso": "cheese",
    "pan": "bread",
    "huevo": "egg",
    "carne": "meat",
    "pescado": "fish",
    "manzana": "apple",
    "naranja": "orange",

    # French
    "poulet": "chicken",
    "riz": "rice",
    "lait": "milk",
    "fromage": "cheese",
    "pain": "bread",
    "oeuf": "egg",
    "viande": "meat",
    "poisson": "fish",
    "pomme": "apple",

    # German
    "huhn": "chicken",
    "reis": "rice",
    "milch": "milk",
    "käse": "cheese",
    "brot": "bread",
    "ei": "egg",
    "fleisch": "meat",
    "fisch": "fish",
    "apfel": "apple",

    # Italian
    "pollo": "chicken",  # duplicate with Spanish
    "riso": "rice",
    "latte": "milk",
    "formaggio": "cheese",
    "pane": "bread",
    "uovo": "egg",
    "carne": "meat",  # duplicate with Spanish
    "pesce": "fish",
    "mela": "apple",

    # Transliterated/common variants
    "chai": "tea",
    "paneer": "cheese",
    "dal": "lentils",
    "naan": "bread",
    "roti": "bread",
    "chapati": "bread",
    "dosa": "rice pancake",
    "idli": "rice cake",
}


def transliterate_to_ascii(text: str) -> str:
    """
    Transliterate Unicode text to closest ASCII equivalents.

    Handles accented characters, diacritics, and some non-Latin scripts.
    Example: "café" -> "cafe", "naïve" -> "naive"

    Args:
        text: Text potentially containing non-ASCII characters

    Returns:
        ASCII-normalized text
    """
    # NFKD normalization separates base chars from combining marks
    normalized = unicodedata.normalize('NFKD', text)
    # Filter out combining characters (diacritics)
    ascii_text = ''.join(c for c in normalized if not unicodedata.combining(c))
    # Encode to ASCII, ignore unmappable chars
    return ascii_text.encode('ascii', 'ignore').decode('ascii')


def apply_multilingual_aliases(name: str) -> str:
    """
    Apply multilingual food name aliases.

    Handles common non-English food names by translating them to English equivalents.

    Args:
        name: Ingredient name (may be in non-English language)

    Returns:
        English name if alias found, otherwise original name
    """
    name_lower = name.lower().strip()

    # Check each token against multilingual aliases
    tokens = name_lower.split()
    translated_tokens = []

    for token in tokens:
        # Remove common punctuation
        clean_token = re.sub(r'[,;.]', '', token)
        # Check if token has multilingual alias
        if clean_token in MULTILINGUAL_ALIASES:
            translated_tokens.append(MULTILINGUAL_ALIASES[clean_token])
            print(f"DEBUG: Translated '{clean_token}' -> '{MULTILINGUAL_ALIASES[clean_token]}'")
        else:
            translated_tokens.append(token)

    result = ' '.join(translated_tokens)
    return result if result != name_lower else name


def canonicalize_portion_label(portion_label: Optional[str]) -> Optional[str]:
    """
    Normalize portion labels to canonical forms.

    Args:
        portion_label: Raw portion label from LLM (e.g., "med", "lg", "2 cups")

    Returns:
        Canonicalized portion label (e.g., "medium", "large", "2 cups")
    """
    if not portion_label:
        return None

    label_lower = portion_label.lower().strip()

    # Replace aliases
    for alias, canonical in PORTION_ALIASES.items():
        if alias in label_lower:
            label_lower = label_lower.replace(alias, canonical)

    return label_lower


def categorize_food(name: str) -> Optional[str]:
    """
    Categorize food by type for portion resolution.

    Args:
        name: Ingredient name

    Returns:
        Category string or None
    """
    name_lower = name.lower()

    # Rice-based mixed mains
    if any(kw in name_lower for kw in ["biryani", "pulao", "pilaf", "fried rice", "nasi goreng", "paella"]):
        return "rice_mixed_main"

    # Yogurt sides
    if any(kw in name_lower for kw in ["raita", "tzatziki", "yogurt dip"]):
        return "yogurt_side"

    # Curries and stews
    if any(kw in name_lower for kw in ["curry", "dal", "daal", "stew", "chili"]):
        return "curry"

    # Salads
    if "salad" in name_lower:
        return "salad"

    return None


def canonicalize_name(name: str, brand: Optional[str] = None, category: Optional[str] = None) -> str:
    """
    Normalize ingredient names to canonical forms.

    Supports:
    - Transliteration (accents, diacritics)
    - Multilingual aliases (Spanish, French, German, Italian, Hindi/Urdu)
    - Context-aware aliases (brand-specific)
    - General aliases (soda->cola, chips->fries)

    IMPORTANT: This runs BEFORE USDA matching, ensuring multilingual names are translated
    to English before searching USDA database.

    Args:
        name: Raw ingredient name from LLM
        brand: Brand context (e.g., "McDonald's")
        category: Category tag (e.g., "beverage", "starch-side")

    Returns:
        Canonicalized name
    """
    if not name:
        return name

    original_name = name

    # Step 1: Transliterate to ASCII (handles "café" -> "cafe")
    name_ascii = transliterate_to_ascii(name)

    # Step 2: Apply multilingual aliases (handles "pollo" -> "chicken")
    # This runs BEFORE USDA search to ensure we search in English
    name_translated = apply_multilingual_aliases(name_ascii)

    name_lower = name_translated.lower().strip()

    if name_translated != original_name:
        print(f"DEBUG: Multilingual canonicalization: '{original_name}' → '{name_translated}' (before USDA search)")

    # Step 3: Apply context-aware aliases
    if brand and "mcdonald" in brand.lower():
        # In McDonald's context, "chips" means fries (UK English)
        if "chips" in name_lower and category in ("starch-side", "side"):
            name_lower = name_lower.replace("chips", "fries")

    # Step 4: Apply general aliases
    for alias, canonical in NAME_ALIASES.items():
        if alias == name_lower:  # Exact match only to avoid over-replacement
            name_lower = canonical
            break

    return name_lower


def check_exclusion_conflict(query: str, candidate_description: str) -> bool:
    """
    Check if candidate has exclusion modifiers that conflict with query.

    Args:
        query: Original search query (e.g., "french fries")
        candidate_description: USDA candidate description (e.g., "SWEET POTATO FRIES")

    Returns:
        True if conflict detected (should reject match), False otherwise
    """
    query_lower = query.lower()
    desc_lower = candidate_description.lower()

    for modifier, blocked_terms in EXCLUSION_MODIFIERS.items():
        # If modifier appears in candidate but NOT in query, and query contains blocked term
        if modifier in desc_lower and modifier not in query_lower:
            for blocked_term in blocked_terms:
                if blocked_term in query_lower:
                    print(f"DEBUG: Exclusion conflict - '{modifier}' in candidate but not query for '{blocked_term}'")
                    return True

    return False


def extract_variant_tokens(name: str) -> tuple[str, set[str]]:
    """
    Extract base name and variant tokens (diet, zero, 2%, etc.).

    Args:
        name: Ingredient name (e.g., "cola (diet)", "milk (2%)")

    Returns:
        Tuple of (base_name, variant_tokens)
    """
    # Extract parenthetical variants
    match = re.match(r'^(.+?)\s*\(([^)]+)\)', name)
    if match:
        base = match.group(1).strip()
        variant_text = match.group(2).strip()
        # Split on common delimiters
        variants = {v.strip() for v in re.split(r'[,/]', variant_text)}
        return base, variants

    # No parentheses - return full name as base
    return name.strip(), set()


def normalize_for_matching(name: str) -> str:
    """
    Normalize ingredient name for Stage-2 matching.

    Lowercases, strips punctuation, applies aliases, and tokenizes.

    Args:
        name: Ingredient name (e.g., "Basmati Rice", "dal (yellow)")

    Returns:
        Normalized name as space-separated tokens (e.g., "rice", "dal")
    """
    # Lowercase
    name_lower = name.lower()

    # Remove parenthetical variants for matching (treat "rice" same as "rice (basmati)")
    name_lower = re.sub(r'\([^)]*\)', '', name_lower)

    # Strip punctuation
    name_lower = re.sub(r'[^\w\s]', ' ', name_lower)

    # Apply aliases
    for alias, canonical in NAME_ALIASES.items():
        if alias in name_lower:
            name_lower = name_lower.replace(alias, canonical)

    # Normalize whitespace and tokenize
    tokens = name_lower.split()

    # Return space-separated tokens
    return ' '.join(tokens)
