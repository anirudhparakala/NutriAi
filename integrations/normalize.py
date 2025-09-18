import json
import re


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
    # Heuristics: strip brand-ish tokens, parentheses, descriptors
    base = re.sub(r"\(.*?\)", "", name).lower()
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
        results = json.loads(search_fn(query=query))
        text = " ".join(r.get("content", "") for r in results)[:5000]

        # Crude pattern matching for known substitutions
        normalization_pairs = [
            ("paneer", "cottage cheese"),
            ("ghee", "clarified butter"),
            ("jaggery", "brown sugar"),
            ("kimchi", "fermented cabbage"),
            ("tempeh", "fermented soybeans"),
            ("tahini", "sesame seed paste"),
            ("naan", "flatbread"),
            ("biryani", "seasoned rice"),
            ("masala", "spice mix"),
            ("chutney", "sauce")
        ]

        for original, normalized in normalization_pairs:
            if original in base and normalized in text.lower():
                print(f"Normalized '{name}' -> '{normalized}' via web search")
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
            # Basic normalization without web assistance
            normalized_name = re.sub(r"\(.*?\)", "", original_name).lower().strip()

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