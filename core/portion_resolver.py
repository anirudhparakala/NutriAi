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


# Beverage density map (g/mL)
BEVERAGE_DENSITY = {
    "milk": 1.03,
    "whole milk": 1.03,
    "2% milk": 1.03,
    "skim milk": 1.03,
    "almond milk": 1.01,
    "soy milk": 1.03,
    "oat milk": 1.03,
    "water": 1.0,
    "juice": 1.04,
    "soda": 1.04,
    "cola": 1.04,
    "default": 1.0,  # default for unknown liquids
}


# Scoop sizes for powder products (grams per scoop)
SCOOP_SIZES = {
    "protein powder": 30,  # standard scoop
    "whey": 30,
    "casein": 30,
    "plant protein": 30,
    "default": 30,
}


# Container capacity mappings: (container_type, size, category) -> (base_grams, clamp_min, clamp_max)
CONTAINER_CAPACITY = {
    # Rice-based mixed mains (biryani, pulao, fried rice, etc.)
    ("plate", "small", "rice_mixed_main"): (400, 300, 550),
    ("plate", "medium", "rice_mixed_main"): (550, 400, 700),
    ("plate", "large", "rice_mixed_main"): (700, 550, 900),
    ("bowl", "small", "rice_mixed_main"): (300, 250, 450),
    ("bowl", "medium", "rice_mixed_main"): (450, 350, 600),
    ("bowl", "large", "rice_mixed_main"): (600, 450, 750),

    # Yogurt sides (raita, tzatziki, etc.)
    ("bowl", "small", "yogurt_side"): (80, 50, 120),
    ("bowl", "medium", "yogurt_side"): (120, 80, 180),
    ("side", "portion", "yogurt_side"): (100, 60, 150),

    # Curries and stews
    ("bowl", "small", "curry"): (250, 200, 350),
    ("bowl", "medium", "curry"): (350, 300, 500),
    ("bowl", "large", "curry"): (500, 400, 650),

    # Salads
    ("plate", "small", "salad"): (150, 100, 250),
    ("plate", "medium", "salad"): (250, 200, 350),
    ("plate", "large", "salad"): (350, 250, 500),
    ("bowl", "small", "salad"): (150, 100, 250),
    ("bowl", "medium", "salad"): (250, 200, 350),
    ("bowl", "large", "salad"): (350, 250, 500),
}

# Fill level multipliers
FILL_LEVEL_MULTIPLIERS = {
    "half": 0.6,
    "level": 1.0,
    "heaping": 1.2,
    "default": 1.0,
}

# Category-based portion bounds (for sanity clamping - legacy)
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


def _extract_brand_and_size(name: str, notes: str, portion_label: str = "") -> tuple[Optional[str], Optional[str]]:
    """
    Extract brand and size from ingredient name, notes, and portion_label.

    Args:
        name: Ingredient name
        notes: Notes field (often contains brand like "McDonald's")
        portion_label: Portion size label (like "large", "medium", "small")

    Returns:
        (brand, size) - both lowercase, or (None, None)
    """
    combined = f"{name} {notes}".lower()

    # Brand detection (primarily from notes field)
    brand = None
    if "mcdonald" in combined or "mcdonalds" in combined or "mcd" in combined:
        brand = "mcdonalds"
    elif "starbucks" in combined or "sbux" in combined:
        brand = "starbucks"
    elif "subway" in combined:
        brand = "subway"
    elif "kfc" in combined:
        brand = "kfc"

    # Size detection - PREFER portion_label over notes/name
    size = None
    portion_lower = portion_label.lower() if portion_label else ""

    # Check portion_label first (most reliable source)
    if "small" in portion_lower or "sm" in portion_lower:
        size = "small"
    elif "medium" in portion_lower or "med" in portion_lower:
        size = "medium"
    elif "large" in portion_lower or "lg" in portion_lower or "lrg" in portion_lower:
        size = "large"
    elif "grande" in portion_lower:  # Starbucks
        size = "large"
    elif "venti" in portion_lower:  # Starbucks
        size = "large"
    elif "tall" in portion_lower:  # Starbucks
        size = "small"

    # Fallback: check combined name+notes only if portion_label didn't have size
    if not size:
        if "small" in combined or "sm" in combined:
            size = "small"
        elif "medium" in combined or "med" in combined or " m " in combined:
            size = "medium"
        elif "large" in combined or "lg" in combined or "lrg" in combined:
            size = "large"

    return brand, size


def _brand_size_lookup(name: str, notes: str, portion_label: str = "") -> Optional[float]:
    """
    Look up portion grams from brand+size cache.

    Args:
        name: Ingredient name (e.g., "cheeseburger", "potato fries", "cola")
        notes: Notes field (e.g., "McDonald's")
        portion_label: Portion size (e.g., "large", "medium", "small")

    Returns:
        Grams or None if no match
    """
    brand, size = _extract_brand_and_size(name, notes, portion_label)
    print(f"DEBUG: _brand_size_lookup(name='{name}', notes='{notes}', portion_label='{portion_label}') -> brand='{brand}', size='{size}'")

    if not brand:
        return None

    name_lower = name.lower()

    # Try exact brand+item+size match first
    if size:
        # Detect item category
        if "fries" in name_lower or "fry" in name_lower:
            key = (brand, "fries", size)
            if key in BRAND_SIZE_PORTIONS:
                grams = BRAND_SIZE_PORTIONS[key]
                print(f"DEBUG: Brand+size match found! key={key} -> {grams}g")
                return grams
            else:
                print(f"DEBUG: Brand+size key not in table: {key}")

        if "cola" in name_lower or "coke" in name_lower or "soda" in name_lower or "pop" in name_lower:
            key = (brand, "cola", size)
            if key in BRAND_SIZE_PORTIONS:
                grams = BRAND_SIZE_PORTIONS[key]
                print(f"DEBUG: Brand+size match found! key={key} -> {grams}g")
                return grams
            else:
                print(f"DEBUG: Brand+size key not in table: {key}")

    # Try brand+item without size
    for item_keyword in ["cheeseburger", "hamburger", "big mac", "quarter pounder", "mcdouble"]:
        if item_keyword.replace(" ", "") in name_lower.replace(" ", ""):
            key = (brand, item_keyword.replace(" ", ""))
            if key in BRAND_SIZE_PORTIONS:
                grams = BRAND_SIZE_PORTIONS[key]
                print(f"DEBUG: Brand+item match found! key={key} -> {grams}g")
                return grams

    print(f"DEBUG: No brand+size match found for name='{name}', brand='{brand}', size='{size}'")
    return None


def _category_heuristics(name: str, notes: str, portion_label: str = "") -> Optional[float]:
    """
    Estimate grams using category-based heuristics.

    Args:
        name: Ingredient name
        notes: Notes field
        portion_label: Portion size label

    Returns:
        Estimated grams or None
    """
    combined = f"{name} {notes}".lower()
    _, size = _extract_brand_and_size(name, notes, portion_label)

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


def _extract_grams_from_label(portion_label: str) -> Optional[float]:
    """
    Extract grams from portion_label like '300g', '250 grams', '1.5kg'.

    Returns:
        Grams as float, or None if not found
    """
    if not portion_label:
        return None

    label_lower = portion_label.lower()

    # Match kg first (convert to grams)
    kg_match = re.search(r'(\d+(?:\.\d+)?)\s*kg', label_lower)
    if kg_match:
        return float(kg_match.group(1)) * 1000.0

    # Match grams
    g_match = re.search(r'(\d+(?:\.\d+)?)\s*g(?:rams?)?(?:\s|$)', label_lower)
    if g_match:
        return float(g_match.group(1))

    return None


def _extract_ml_from_label(portion_label: str) -> Optional[float]:
    """
    Extract milliliters from portion_label like '250ml', '500 mL', '1.5L'.

    Returns:
        Milliliters as float, or None if not found
    """
    if not portion_label:
        return None

    label_lower = portion_label.lower()

    # Match liters first (convert to mL)
    l_match = re.search(r'(\d+(?:\.\d+)?)\s*l(?:iters?)?(?:\s|$)', label_lower)
    if l_match:
        return float(l_match.group(1)) * 1000.0

    # Match milliliters
    ml_match = re.search(r'(\d+(?:\.\d+)?)\s*ml', label_lower)
    if ml_match:
        return float(ml_match.group(1))

    return None


def _extract_oz_from_label(portion_label: str) -> Optional[float]:
    """
    Extract ounces from portion_label like '14 oz', '16oz', '12 fl oz'.

    Returns:
        Ounces as float, or None if not found
    """
    if not portion_label:
        return None

    # Match patterns like "14 oz", "16oz", "12 fl oz"
    match = re.search(r'(\d+(?:\.\d+)?)\s*(?:fl\s*)?oz', portion_label.lower())
    if match:
        return float(match.group(1))
    return None


def _extract_scoops_from_label(portion_label: str) -> Optional[int]:
    """
    Extract scoop count from portion_label like '1 scoop', '2 scoops'.

    Returns:
        Number of scoops as int, or None if not found
    """
    if not portion_label:
        return None

    # Match patterns like "1 scoop", "2 scoops"
    match = re.search(r'(\d+)\s*scoops?', portion_label.lower())
    if match:
        return int(match.group(1))
    return None


def _extract_tbsp_from_label(portion_label: str) -> Optional[int]:
    """
    Extract tablespoon count from portion_label like '2 tbsp', '1 tablespoon'.

    Returns:
        Number of tablespoons as int, or None if not found
    """
    if not portion_label:
        return None

    # Match patterns like "2 tbsp", "1 tablespoon", "3 tablespoons"
    match = re.search(r'(\d+)\s*(?:tbsp|tablespoons?|tbs)', portion_label.lower())
    if match:
        return int(match.group(1))
    return None


def _get_density_for_ingredient(name: str) -> float:
    """
    Get density (g/mL) for an ingredient based on name.

    Returns:
        Density in g/mL
    """
    name_lower = name.lower()

    # Check for exact matches first
    for key in BEVERAGE_DENSITY:
        if key in name_lower:
            return BEVERAGE_DENSITY[key]

    # Default to 1.0 g/mL (water)
    return BEVERAGE_DENSITY["default"]


def _get_scoop_size_for_ingredient(name: str) -> float:
    """
    Get scoop size (grams per scoop) for a powder ingredient.

    Returns:
        Grams per scoop
    """
    name_lower = name.lower()

    # Check for exact matches
    for key in SCOOP_SIZES:
        if key in name_lower:
            return SCOOP_SIZES[key]

    # Default to 30g per scoop
    return SCOOP_SIZES["default"]


def _has_powder_sibling(items: List[Dict[str, Any]]) -> bool:
    """
    Check if any ingredient in the list is a protein powder.
    Used to apply "headroom" reduction for shake/smoothie base liquids.

    Returns:
        True if powder present
    """
    for item in items:
        name_lower = item.get("name", "").lower()
        if any(kw in name_lower for kw in ["protein powder", "whey", "casein", "plant protein"]):
            return True
    return False


def _infer_container_type(portion_label: str) -> Optional[str]:
    """
    Infer container type from portion_label text.

    Returns:
        Container type: "plate", "bowl", "glass", "side", or None
    """
    if not portion_label:
        return None

    label_lower = portion_label.lower()

    if "plate" in label_lower:
        return "plate"
    elif "bowl" in label_lower:
        return "bowl"
    elif any(kw in label_lower for kw in ["glass", "cup", "oz", "ml"]):
        return "glass"
    elif "side" in label_lower:
        return "side"

    return None


def _container_capacity_lookup(
    name: str,
    portion_label: str,
    category: Optional[str] = None,
    fill_level: str = "level"
) -> Optional[float]:
    """
    Look up portion grams from container capacity tables.

    Args:
        name: Ingredient name
        portion_label: Portion description (e.g., "large plate", "small bowl")
        category: Food category (e.g., "rice_mixed_main", "yogurt_side")
        fill_level: Fill level ("half", "level", "heaping")

    Returns:
        Grams or None if no match
    """
    if not category:
        return None

    # Infer container type from portion_label
    container_type = _infer_container_type(portion_label)
    if not container_type:
        return None

    # Extract size from portion_label
    _, size = _extract_brand_and_size(name, "", portion_label)
    if not size:
        # Default to medium if no size specified but container type exists
        size = "medium"

    # Special handling for "side portion" labels
    if "side" in portion_label.lower() and "portion" in portion_label.lower():
        container_type = "side"
        size = "portion"

    # Lookup in capacity table
    key = (container_type, size, category)
    if key not in CONTAINER_CAPACITY:
        return None

    base_grams, clamp_min, clamp_max = CONTAINER_CAPACITY[key]

    # Apply fill level multiplier
    multiplier = FILL_LEVEL_MULTIPLIERS.get(fill_level, FILL_LEVEL_MULTIPLIERS["default"])
    grams = base_grams * multiplier

    # Clamp to category-specific bounds
    clamped = False
    if grams < clamp_min:
        grams = clamp_min
        clamped = True
    elif grams > clamp_max:
        grams = clamp_max
        clamped = True

    print(f"DEBUG: _container_capacity_lookup(name='{name}', portion_label='{portion_label}', category='{category}') -> container='{container_type}', size='{size}' → {grams}g (clamped={clamped})")

    return grams


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
        # Exclude syrups, sauces, and condiments from beverage category
        if not any(exclude in name_lower for exclude in ["syrup", "sauce", "ketchup", "mayo", "dressing", "condiment"]):
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

        # 2) Brand+size lookup (pass portion_label separately!)
        resolved_grams = _brand_size_lookup(name, notes, portion_label)
        if resolved_grams:
            resolution_source = "brand-size-lookup"
            metrics["brand_size"] += 1
            print(f"DEBUG: Portion resolver tier 2 (brand+size): '{name}' = {resolved_grams}g")

        # 2.4) User-volunteered grams (e.g., "300g", "1.5kg")
        if not resolved_grams:
            user_grams = _extract_grams_from_label(portion_label)
            if user_grams:
                resolved_grams = user_grams
                resolution_source = "user-grams-label"
                metrics["brand_size"] += 1  # Count as deterministic
                print(f"DEBUG: Portion resolver tier 2.4 (user-grams): '{name}' = {user_grams}g from portion_label")

        # 2.45) User-volunteered mL (e.g., "250ml", "1.5L") - convert via density
        if not resolved_grams:
            user_ml = _extract_ml_from_label(portion_label)
            if user_ml:
                density = _get_density_for_ingredient(name)
                resolved_grams = user_ml * density
                resolution_source = "user-ml-label"
                metrics["brand_size"] += 1  # Count as deterministic
                print(f"DEBUG: Portion resolver tier 2.45 (user-ml): '{name}' = {user_ml}mL × {density}g/mL = {resolved_grams:.1f}g")

        # 2.5) Scoop-based resolution for powders (protein powder, etc.)
        if not resolved_grams:
            scoops = _extract_scoops_from_label(portion_label)
            if scoops:
                scoop_size = _get_scoop_size_for_ingredient(name)
                resolved_grams = scoops * scoop_size
                resolution_source = "scoop-label"
                metrics["brand_size"] += 1  # Count as deterministic like brand+size
                print(f"DEBUG: Portion resolver tier 2.5 (scoop): '{name}' = {scoops} scoops × {scoop_size}g = {resolved_grams}g")

        # 2.6) Ounce-based resolution for liquids (milk, water, etc.)
        if not resolved_grams:
            oz = _extract_oz_from_label(portion_label)
            if oz:
                # Check if powder is present in the ingredient list (for headroom)
                has_powder = _has_powder_sibling(items)

                # Apply headroom if this is a shake/smoothie base liquid with powder
                name_lower = name.lower()
                is_shake_base = any(kw in name_lower for kw in ["milk", "water", "juice", "base"])
                notes_lower = notes.lower() if notes else ""
                is_smoothie_context = "smoothie" in notes_lower or "shake" in notes_lower

                if has_powder and is_shake_base and is_smoothie_context:
                    # Apply headroom: 16oz → 14oz, 12oz → 10oz
                    if oz >= 16:
                        oz = oz - 2
                        print(f"DEBUG: Applied -2oz headroom for shake base (powder present): {oz + 2}oz → {oz}oz")
                    elif oz >= 12:
                        oz = oz - 2
                        print(f"DEBUG: Applied -2oz headroom for shake base (powder present): {oz + 2}oz → {oz}oz")

                # Convert oz to mL (1 oz = 29.5735 mL)
                ml = oz * 29.5735

                # Get density for this ingredient
                density = _get_density_for_ingredient(name)

                # Convert mL to grams
                resolved_grams = ml * density
                resolution_source = "oz-label-density"
                metrics["brand_size"] += 1  # Count as deterministic
                print(f"DEBUG: Portion resolver tier 2.6 (oz+density): '{name}' = {oz}oz × {ml:.1f}mL × {density}g/mL = {resolved_grams:.1f}g")

        # 2.7) Tablespoon-based resolution for syrups, sauces, oils
        if not resolved_grams:
            tbsp = _extract_tbsp_from_label(portion_label)
            if tbsp:
                # 1 tbsp = ~15 mL for most liquids/syrups
                ml = tbsp * 15.0

                # Get density for this ingredient
                density = _get_density_for_ingredient(name)

                # For thick syrups, use higher density
                name_lower = name.lower()
                if any(kw in name_lower for kw in ['syrup', 'honey', 'molasses']):
                    density = 1.4  # Syrups are denser than water
                elif any(kw in name_lower for kw in ['oil', 'butter']):
                    density = 0.92  # Oils/fats are less dense

                # Convert mL to grams
                resolved_grams = ml * density
                resolution_source = "tbsp-label-density"
                metrics["brand_size"] += 1  # Count as deterministic
                print(f"DEBUG: Portion resolver tier 2.7 (tbsp): '{name}' = {tbsp} tbsp × 15mL × {density}g/mL = {resolved_grams:.1f}g")

        # 2.8) Container-capacity lookup (plates, bowls - universal across cuisines)
        if not resolved_grams:
            category = item.get("category")  # Will be set by canonicalization
            fill_level = item.get("fill_level", "level")

            resolved_grams = _container_capacity_lookup(name, portion_label, category, fill_level)
            if resolved_grams:
                resolution_source = "container-capacity"
                metrics["brand_size"] += 1  # Count as deterministic
                print(f"DEBUG: Portion resolver tier 2.8 (container-capacity): '{name}' = {resolved_grams}g")

        # 3) USDA foodPortions (TODO: implement when needed)
        # if not resolved_grams and usda_client:
        #     resolved_grams = _grams_from_usda_portions(usda_client, name, portion_label)
        #     resolution_source = "usda-portions"
        #     metrics["usda_portions"] += 1

        # 4) Category heuristics (pass portion_label separately!)
        if not resolved_grams:
            resolved_grams = _category_heuristics(name, notes, portion_label)
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
