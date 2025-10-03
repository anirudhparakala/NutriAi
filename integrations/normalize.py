import json
import re

# Regex to capture diet/zero/unsweetened variants
VARIANT_RX = re.compile(
    r'\b(diet|zero|sugar[- ]?free|no\s*sugar|unsweetened|black|plain|skim|nonfat|fat[- ]?free|1%|2%|whole)\b',
    re.I
)


def _preserve_variants(name: str) -> str:
    """
    Extract and preserve variant keywords (diet, zero, unsweetened, etc.)
    from the ingredient name, returning a searchable form.

    Examples:
        "cola (diet)" -> "diet cola"
        "milk (2%)" -> "2% milk"
        "iced tea (unsweetened)" -> "unsweetened iced tea"
        "regular chicken" -> "chicken"
    """
    raw = name.strip()
    # Capture any parenthetical parts e.g., "(diet)"
    paren_parts = re.findall(r'\((.*?)\)', raw)
    tokens = " ".join(paren_parts + [raw])
    variants = [m.group(0).lower() for m in VARIANT_RX.finditer(tokens)]

    # Remove parentheses but keep base
    base = re.sub(r'\(.*?\)', '', raw).strip()
    base = re.sub(r'\s+', ' ', base)

    if variants:
        # Prefer "diet cola" style (prefix) for USDA searchability
        return f"{variants[0]} {base}".strip()
    return base


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
    # Preserve variants (diet, zero, unsweetened, etc.) before cleaning
    base = _preserve_variants(name).lower()
    base = re.sub(r"[\d\-]+(g|ml|grams|milliliters)\b", "", base).strip()
    base = re.sub(r"\b(fresh|frozen|canned|organic|free-range|grass-fed|raw|cooked)\b", "", base).strip()

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
        search_result = search_fn(query=query)

        # Handle error responses from search function
        if isinstance(search_result, str) and search_result.startswith("Error"):
            print(f"Search error for '{name}': {search_result}")
            return base

        # Parse search results - expecting JSON string with list of {"content": "..."} objects
        results = json.loads(search_result)

        # Ensure results is a list
        if not isinstance(results, list):
            print(f"Unexpected search result format for '{name}': expected list, got {type(results)}")
            return base

        text = " ".join(r.get("content", "") for r in results if isinstance(r, dict))[:5000]

        # Enhanced synonym map for ingredient normalization
        normalization_pairs = [
            ("paneer", "cottage cheese"),
            ("ghee", "clarified butter"),
            ("jaggery", "cane sugar"),
            ("maida", "all-purpose flour"),
            ("curd", "yogurt"),
            ("kimchi", "fermented cabbage"),
            ("tempeh", "fermented soybeans"),
            ("tahini", "sesame seed paste"),
            ("naan", "flatbread"),
            ("biryani", "seasoned rice"),
            ("masala", "spice mix"),
            ("chutney", "sauce"),
            ("dal", "lentils"),
            ("besan", "chickpea flour"),
            ("atta", "whole wheat flour"),
            ("rajma", "kidney beans"),
            ("chana", "chickpeas"),
            ("palak", "spinach"),
            ("gobi", "cauliflower"),
            ("aloo", "potato"),
            ("pyaz", "onion"),
            ("adrak", "ginger"),
            ("lehsun", "garlic")
        ]

        # Apply synonym mapping - check both web results and exact matches
        for original, normalized in normalization_pairs:
            # Direct match in base name
            if original in base:
                # Confirm via web search if available, otherwise use direct mapping
                if normalized in text.lower() or not text.strip():
                    print(f"Normalized '{name}' -> '{normalized}' via synonym mapping")
                    return normalized

        # Try to extract common food terms from search results
        food_terms = re.findall(r'\b(chicken|beef|pork|fish|rice|pasta|bread|cheese|oil|butter|sauce|vegetable|fruit)\b', text.lower())
        if food_terms:
            # Return the most common food term found
            most_common = max(set(food_terms), key=food_terms.count)
            print(f"Normalized '{name}' -> '{most_common}' via web search pattern")
            return most_common

    except Exception as e:
        print(f"Web normalization failed for '{name}': {e}")

    # Fallback to basic cleaning
    return base


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
            # Basic normalization without web assistance - preserve variants
            normalized_name = _preserve_variants(original_name).lower().strip()

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

    Args:
        ingredient_name: Normalized ingredient name

    Returns:
        List of search terms to try for USDA lookup, ordered by specificity
    """
    base_name = ingredient_name.lower().strip()

    # Start with the exact name
    search_terms = [base_name]

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
    for term in search_terms + variations:
        if term not in seen:
            seen.add(term)
            unique_terms.append(term)

    return unique_terms[:5]  # Limit to top 5 most relevant terms