import json
import re


def _minimal_normalize(name: str) -> str:
    """
    Minimal normalization that preserves all semantic qualifiers.
    Only removes: units, measurements, and extreme noise.

    Philosophy: Keep everything that might matter for USDA lookup.
    Let USDA's own search handle synonyms and variants.

    Examples:
        "cola (diet)" -> "cola (diet)"
        "rendang (beef)" -> "rendang (beef)"
        "jollof rice (party style)" -> "jollof rice (party style)"
        "milk 500ml (2%)" -> "milk (2%)"
    """
    cleaned = name.strip()

    # Only remove explicit weight/volume measurements (not descriptors)
    cleaned = re.sub(r'\b\d+[\s]?(g|ml|grams|milliliters|oz|fl\.?\s?oz)\b', '', cleaned, flags=re.I)

    # Remove brand markers but keep everything else
    cleaned = re.sub(r'[®™©]', '', cleaned)

    # Collapse multiple spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return cleaned


def normalize_with_web(name: str, search_fn) -> str:
    """
    Normalize ingredient names using web search assistance.
    Only queries web when the model marks uncertainty or name has special markers.

    Args:
        name: Original ingredient name from vision/user input
        search_fn: Function to perform web search (e.g., from search_bridge)

    Returns:
        Normalized ingredient name suitable for USDA lookup
    """
    # Start with minimal normalization - keep all qualifiers
    base = _minimal_normalize(name).lower()

    # Check if web assistance is needed
    needs_web_help = (
        "uncertain" in name.lower() or
        "(" in name or
        any(brand_marker in name.lower() for brand_marker in ["brand", "®", "™", "&", "co.", "inc."]) or
        any(ethnic_marker in name.lower() for ethnic_marker in ["paneer", "ghee", "jaggery", "kimchi", "tempeh", "tahini"])
    )

    if not needs_web_help:
        return base

    # Web assist: query for common name
    try:
        query = f"common name for '{base}' food ingredient nutrition"
        results = search_fn(query=query)  # Now returns Python list directly

        # Ensure results is a list
        if not isinstance(results, list):
            print(f"Unexpected search result format for '{name}': {type(results)}")
            return base

        # Web assist is available but we DON'T want to destructively rename
        # Preserve the original dish name - this keeps cultural/cuisine specificity
        # Only use web search for validation, not replacement
        print(f"Web search available for '{name}' but preserving original name for cultural specificity")

    except Exception as e:
        print(f"Web normalization failed for '{name}': {e}")

    # Fallback to basic cleaning
    return base


def canonicalize_name(name: str) -> str:
    """
    Canonicalize ingredient names with generic aliases (FIX E).
    Converts common variants to database-friendly names without brand specificity.

    Args:
        name: Raw ingredient name from user input

    Returns:
        Canonicalized name suitable for USDA lookup

    Examples:
        "whey protein" -> "protein powder (whey)"
        "protein shake powder" -> "protein powder"
        "skim milk" -> "milk (nonfat)"
        "2% milk" -> "milk (2%)"
    """
    name_lower = name.lower().strip()

    # Protein powder aliases
    if "whey protein" in name_lower or "whey" in name_lower:
        return "protein powder (whey)"
    if "protein shake powder" in name_lower or "protein mix" in name_lower:
        return "protein powder"
    if "casein" in name_lower:
        return "protein powder (casein)"

    # Milk variants
    if "skim milk" in name_lower or "fat free milk" in name_lower:
        return "milk (nonfat)"
    if "2% milk" in name_lower:
        return "milk (2%)"
    if "whole milk" in name_lower:
        return "milk (whole)"
    if "1% milk" in name_lower:
        return "milk (1%)"

    # Oil aliases
    if "olive oil" in name_lower:
        return "oil (olive)"
    if "vegetable oil" in name_lower:
        return "oil (vegetable)"

    # Otherwise, apply minimal normalization
    return _minimal_normalize(name)


def normalize_ingredient_list(ingredients: list, search_fn=None) -> list:
    """
    Normalize a list of ingredients, applying web search normalization selectively.

    Args:
        ingredients: List of Ingredient objects or dicts with 'name' field
        search_fn: Optional search function for web assistance

    Returns:
        List of ingredients with normalized names
    """
    normalized = []

    for ingredient in ingredients:
        if hasattr(ingredient, 'name'):
            original_name = ingredient.name
        elif isinstance(ingredient, dict) and 'name' in ingredient:
            original_name = ingredient['name']
        else:
            normalized.append(ingredient)
            continue

        if search_fn:
            normalized_name = normalize_with_web(original_name, search_fn)
        else:
            # Basic normalization without web assistance - minimal cleaning only
            normalized_name = _minimal_normalize(original_name).lower().strip()

        # Update the ingredient name
        if hasattr(ingredient, 'name'):
            ingredient.name = normalized_name
        elif isinstance(ingredient, dict):
            ingredient['name'] = normalized_name

        normalized.append(ingredient)

    return normalized


def suggest_usda_search_terms(ingredient_name: str) -> list[str]:
    """
    Generate multiple search terms for USDA lookup based on ingredient name.
    Variant-first ordering to get best hit on first try.

    Args:
        ingredient_name: Normalized ingredient name

    Returns:
        List of search terms to try for USDA lookup, ordered by specificity
    """
    base_name = ingredient_name.lower().strip()
    terms = [base_name]

    # Detect common variants and create variant-first term
    VARS = ["diet", "zero", "sugar-free", "sugar free", "unsweetened", "black", "plain", "1%", "2%", "whole"]
    variant = next((v for v in VARS if v in base_name), None)

    if variant:
        # Make a prefixed variant form: "diet cola", "1% milk", etc.
        core = base_name.replace("(", " ").replace(")", " ").strip()
        # Keep only one space
        core = re.sub(r"\s+", " ", core)
        # Insert variant-first term at the front so it's tried first
        variant_first = f"{variant} " + core.replace(variant, "").strip()
        terms.insert(0, variant_first)

    # Add variations
    variations = [
        f"{base_name} raw",
        f"{base_name} cooked",
        f"{base_name} fresh",
        base_name.replace(" ", ""),  # Remove spaces
        base_name.split()[0] if " " in base_name else base_name,  # First word only
    ]

    # Add common food category expansions
    category_expansions = {
        "chicken": ["chicken breast", "chicken thigh", "chicken meat"],
        "beef": ["beef ground", "beef sirloin", "beef chuck"],
        "rice": ["rice white", "rice brown", "rice long grain"],
        "oil": ["oil vegetable", "oil olive", "oil canola"],
        "cheese": ["cheese cheddar", "cheese mozzarella", "cheese american"]
    }

    if base_name in category_expansions:
        variations.extend(category_expansions[base_name])

    # Remove duplicates while preserving order
    seen = set()
    unique_terms = []
    for term in terms + variations:
        if term and term not in seen:
            seen.add(term)
            unique_terms.append(term)

    return unique_terms[:5]  # Limit to top 5 most relevant terms