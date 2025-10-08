"""
Portion Resolver: Deterministically converts ingredient sizes to grams.

Decouples grams from LLM estimates - uses authoritative data instead.
Resolution order (high to low trust):
1. User-stated grams
2. Brand+size lookup (McDonald's medium fries, Starbucks grande latte, etc.)
3. USDA foodPortions (from FDC details)
4. Category heuristics (medium beverage, large burger, etc.)
5. Vision estimate (fallback only)
"""

from typing import Dict, List, Optional, Any
import re


# Brand + Size lookup cache (one-time authoring, heavily amortized)
BRAND_SIZE_PORTIONS = {
    # McDonald's
    ("mcdonalds", "cheeseburger"): 119,
    ("mcdonalds", "hamburger"): 100,
    ("mcdonalds", "big mac"): 219,
    ("mcdonalds", "quarter pounder"): 198,
    ("mcdonalds", "mcdouble"): 170,

    # Fries
    ("mcdonalds", "fries", "small"): 71,
    ("mcdonalds", "fries", "medium"): 111,
    ("mcdonalds", "fries", "large"): 154,

    # Beverages (using 1.04 g/ml for cola density)
    ("mcdonalds", "cola", "small"): 336,  # 12 oz ≈ 355ml
    ("mcdonalds", "cola", "medium"): 567,  # 21 oz ≈ 621ml → realistic ~545ml
    ("mcdonalds", "cola", "large"): 851,   # 30 oz ≈ 887ml → realistic ~820ml

    # Generic beverage sizes (g, assuming ~1.0 density for most)
    ("generic", "beverage", "small"): 340,   # ~12 oz
    ("generic", "beverage", "medium"): 475,  # ~16 oz
    ("generic", "beverage", "large"): 680,   # ~24 oz
}


# Category-based portion bounds (for sanity clamping)
CATEGORY_BOUNDS = {
    "burger": (80, 250),       # cheeseburger to double/triple
    "fries": (50, 200),        # small to large
    "beverage": (200, 1000),   # small to extra large
    "sandwich": (100, 350),
    "pizza_slice": (80, 150),
    "rice": (100, 300),        # cooked
    "chicken_piece": (80, 250),
    "salad": (150, 400),
}


def _extract_brand_and_size(name: str, notes: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract brand and size from ingredient name and notes.

    Returns:
        (brand, size) - both lowercase, or (None, None)
    """
    combined = f"{name} {notes}".lower()

    # Brand detection
    brand = None
    if "mcdonald" in combined or "mcdonalds" in combined or "mcd" in combined:
        brand = "mcdonalds"
    elif "starbucks" in combined or "sbux" in combined:
        brand = "starbucks"
    elif "subway" in combined:
        brand = "subway"
    elif "kfc" in combined:
        brand = "kfc"

    # Size detection
    size = None
    if "small" in combined or "sm" in combined:
        size = "small"
    elif "medium" in combined or "med" in combined or "m" in combined:
        size = "medium"
    elif "large" in combined or "lg" in combined or "lrg" in combined:
        size = "large"

    return brand, size


def _brand_size_lookup(name: str, notes: str) -> Optional[float]:
    """
    Look up portion grams from brand+size cache.

    Args:
        name: Ingredient name (e.g., "cheeseburger", "potato fries", "cola")
        notes: Notes field (e.g., "McDonald's medium")

    Returns:
        Grams or None if no match
    """
    brand, size = _extract_brand_and_size(name, notes)

    if not brand:
        return None

    name_lower = name.lower()

    # Try exact brand+item+size match first
    if size:
        # Detect item category
        if "fries" in name_lower or "fry" in name_lower:
            key = (brand, "fries", size)
            if key in BRAND_SIZE_PORTIONS:
                return BRAND_SIZE_PORTIONS[key]

        if "cola" in name_lower or "coke" in name_lower or "soda" in name_lower or "pop" in name_lower:
            key = (brand, "cola", size)
            if key in BRAND_SIZE_PORTIONS:
                return BRAND_SIZE_PORTIONS[key]

    # Try brand+item without size
    for item_keyword in ["cheeseburger", "hamburger", "big mac", "quarter pounder", "mcdouble"]:
        if item_keyword.replace(" ", "") in name_lower.replace(" ", ""):
            key = (brand, item_keyword.replace(" ", ""))
            if key in BRAND_SIZE_PORTIONS:
                return BRAND_SIZE_PORTIONS[key]

    return None


def _category_heuristics(name: str, notes: str) -> Optional[float]:
    """
    Estimate grams using category-based heuristics.

    Args:
        name: Ingredient name
        notes: Notes field

    Returns:
        Estimated grams or None
    """
    combined = f"{name} {notes}".lower()
    _, size = _extract_brand_and_size(name, notes)

    # Burgers
    if any(kw in combined for kw in ["burger", "sandwich"]):
        if size == "small":
            return 100
        elif size == "large":
            return 200
        else:  # medium or no size
            return 150

    # Fries
    if "fries" in combined or "fry" in combined:
        if size == "small":
            return 70
        elif size == "large":
            return 155
        else:  # medium
            return 110

    # Beverages (detect by cola/soda/drink/juice/tea/coffee/water)
    if any(kw in combined for kw in ["cola", "soda", "pop", "drink", "juice", "tea", "coffee", "water", "latte", "cappuccino"]):
        # Use density factor (cola ≈ 1.04 g/ml, water/tea/coffee ≈ 1.0 g/ml)
        density = 1.04 if "cola" in combined or "soda" in combined else 1.0

        if size == "small":
            return int(340 * density)  # ~12 oz
        elif size == "large":
            return int(680 * density)  # ~24 oz
        else:  # medium
            return int(475 * density)  # ~16 oz

    # Rice (cooked)
    if "rice" in combined:
        if size == "small":
            return 150
        elif size == "large":
            return 250
        else:
            return 200

    return None


def _clamp_by_category(name: str, grams: float) -> float:
    """
    Clamp grams to category bounds (prevents outliers like 500g fries).

    Args:
        name: Ingredient name
        grams: Proposed grams

    Returns:
        Clamped grams
    """
    name_lower = name.lower()

    # Detect category
    category = None
    if any(kw in name_lower for kw in ["burger", "sandwich"]):
        category = "burger"
    elif "fries" in name_lower or "fry" in name_lower:
        category = "fries"
    elif any(kw in name_lower for kw in ["cola", "soda", "pop", "drink", "juice", "tea", "coffee", "water", "latte"]):
        category = "beverage"
    elif "rice" in name_lower:
        category = "rice"
    elif "chicken" in name_lower and ("piece" in name_lower or "breast" in name_lower or "thigh" in name_lower):
        category = "chicken_piece"
    elif "pizza" in name_lower and "slice" in name_lower:
        category = "pizza_slice"
    elif "salad" in name_lower:
        category = "salad"

    if category and category in CATEGORY_BOUNDS:
        min_g, max_g = CATEGORY_BOUNDS[category]
        if grams < min_g:
            print(f"DEBUG: Clamping {name} portion from {grams}g to {min_g}g (category min)")
            return min_g
        elif grams > max_g:
            print(f"DEBUG: Clamping {name} portion from {grams}g to {max_g}g (category max)")
            return max_g

    return grams


def resolve_portions(items: List[Dict[str, Any]], usda_client=None) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Resolve portion sizes to deterministic grams.

    Resolution order:
    1. User/vision-stated grams (source='user' or 'vision' with amount set)
    2. Brand+size lookup (using portion_label + notes)
    3. USDA foodPortions (TODO: requires FDC details API)
    4. Category heuristics (using portion_label)
    5. Vision estimate (fallback)

    Args:
        items: List of ingredient dicts with name, amount, portion_label, source, notes
        usda_client: Optional USDA client for foodPortions lookup

    Returns:
        Tuple of (updated items list with resolved grams, metrics dict with tier counts)
    """
    out = []
    metrics = {
        "user_vision": 0,
        "brand_size": 0,
        "usda_portions": 0,
        "category_heuristic": 0,
        "unresolved": 0
    }

    for item in items:
        name = item.get("name", "")
        notes = item.get("notes", "") or ""
        grams = item.get("amount")
        source = item.get("source", "").lower()
        portion_label = item.get("portion_label", "") or ""

        # 1) Keep user/vision-stated grams (explicit amounts only)
        if source in ("user", "vision") and isinstance(grams, (int, float)) and grams > 0:
            print(f"DEBUG: Portion resolver tier 1 (user/vision): '{name}' = {grams}g")
            # Still apply sanity clamp even for user/vision
            item["amount"] = _clamp_by_category(name, grams)
            metrics["user_vision"] += 1
            out.append(item)
            continue

        resolved_grams = None
        resolution_source = None

        # Combine portion_label and notes for size extraction
        combined_context = f"{portion_label} {notes}".strip()

        # 2) Brand+size lookup
        resolved_grams = _brand_size_lookup(name, combined_context)
        if resolved_grams:
            resolution_source = "brand-size-lookup"
            metrics["brand_size"] += 1
            print(f"DEBUG: Portion resolver tier 2 (brand+size): '{name}' = {resolved_grams}g")

        # 3) USDA foodPortions (TODO: implement when needed)
        # if not resolved_grams and usda_client:
        #     resolved_grams = _grams_from_usda_portions(usda_client, name, portion_label)
        #     resolution_source = "usda-portions"
        #     metrics["usda_portions"] += 1

        # 4) Category heuristics (uses portion_label)
        if not resolved_grams:
            resolved_grams = _category_heuristics(name, combined_context)
            if resolved_grams:
                resolution_source = "category-heuristic"
                metrics["category_heuristic"] += 1
                print(f"DEBUG: Portion resolver tier 4 (category heuristic): '{name}' = {resolved_grams}g")

        # 5) Fallback to vision estimate (only if amount was set from vision but source wasn't 'vision')
        if not resolved_grams and isinstance(grams, (int, float)) and grams > 0:
            resolved_grams = grams
            resolution_source = "vision-estimate-fallback"
            metrics["category_heuristic"] += 1  # Count as heuristic since it's not explicit
            print(f"DEBUG: Portion resolver tier 5 (vision fallback): '{name}' = {resolved_grams}g")

        # Apply category-based sanity clamp
        if resolved_grams:
            resolved_grams = _clamp_by_category(name, resolved_grams)
            item["amount"] = resolved_grams
            item["portion_source"] = resolution_source
            item["source"] = "portion-resolver"  # Mark that resolver set this
        else:
            # No resolution found - set a safe default to prevent None errors downstream
            metrics["unresolved"] += 1
            print(f"WARNING: Portion resolver tier N/A (unresolved): '{name}' using 100g default")
            item["amount"] = 100.0  # Safe default
            item["portion_source"] = "default-fallback"
            item["source"] = "portion-resolver"

        out.append(item)

    # Log metrics summary as JSON for easy parsing
    import json
    total_items = sum(metrics.values())
    tier_rates = {tier: (count / total_items) * 100 if total_items > 0 else 0 for tier, count in metrics.items()}

    print(f"METRICS: {json.dumps({'event': 'portion_resolver', 'tiers': metrics, 'tier_rates_pct': tier_rates})}")

    # Log warning if heuristic rate is high (colleague wants this trending down)
    heuristic_rate = tier_rates.get('category_heuristic', 0)
    if heuristic_rate > 20:  # >20% using heuristics
        print(f"WARNING: High heuristic usage rate: {heuristic_rate:.1f}% (target: <20%)")

    return out, metrics
