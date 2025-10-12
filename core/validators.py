from typing import Dict, List, Any, Union
import json
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.privacy import sanitize_metrics
from .nutrition_lookup import ScaledItem
from .schemas import Ingredient

# Beverage density approximations (g/ml) for per-100ml normalization
BEVERAGE_DENSITY = {
    "water": 1.0,
    "soda": 1.04,  # Slightly denser due to sugar
    "cola": 1.04,
    "juice": 1.05,
    "milk": 1.03,
    "beer": 1.01,
    "wine": 0.99,
    "default": 1.0  # Fallback assumption: 1ml ≈ 1g
}

# Default portion bound heuristics (editable)
PORTION_BOUNDS = {
    # Oils and fats
    "oil": {"max_grams": 30, "category": "fat"},
    "butter": {"max_grams": 30, "category": "fat"},
    "ghee": {"max_grams": 30, "category": "fat"},
    "olive oil": {"max_grams": 30, "category": "fat"},
    "coconut oil": {"max_grams": 30, "category": "fat"},
    "avocado oil": {"max_grams": 30, "category": "fat"},

    # Spices and condiments
    "salt": {"max_grams": 20, "category": "condiment"},
    "pepper": {"max_grams": 20, "category": "spice"},
    "cumin": {"max_grams": 20, "category": "spice"},
    "turmeric": {"max_grams": 20, "category": "spice"},
    "paprika": {"max_grams": 20, "category": "spice"},
    "oregano": {"max_grams": 20, "category": "spice"},
    "basil": {"max_grams": 20, "category": "spice"},
    "thyme": {"max_grams": 20, "category": "spice"},
    "rosemary": {"max_grams": 20, "category": "spice"},
    "garlic powder": {"max_grams": 20, "category": "spice"},
    "onion powder": {"max_grams": 20, "category": "spice"},
    "chili powder": {"max_grams": 20, "category": "spice"},
    "cayenne": {"max_grams": 20, "category": "spice"},
    "cinnamon": {"max_grams": 20, "category": "spice"},
    "nutmeg": {"max_grams": 20, "category": "spice"},
    "soy sauce": {"max_grams": 20, "category": "condiment"},
    "vinegar": {"max_grams": 20, "category": "condiment"},
    "lemon juice": {"max_grams": 20, "category": "condiment"},
    "lime juice": {"max_grams": 20, "category": "condiment"},

    # Carb bases (typical caps)
    "rice": {"max_grams": 500, "category": "carb_base"},
    "pasta": {"max_grams": 500, "category": "carb_base"},
    "bread": {"max_grams": 500, "category": "carb_base"},
    "quinoa": {"max_grams": 500, "category": "carb_base"},
    "oats": {"max_grams": 500, "category": "carb_base"},
    "noodles": {"max_grams": 500, "category": "carb_base"},
    "couscous": {"max_grams": 500, "category": "carb_base"},
    "barley": {"max_grams": 500, "category": "carb_base"},
}


def validate_4_4_9(items_or_totals: Union[List[ScaledItem], Dict[str, float]], tolerance: float = 0.10) -> Dict[str, Any]:
    """
    Validate that calories roughly match 4p+4c+9f formula (±tolerance).

    Args:
        items_or_totals: Either list of ScaledItem objects or totals dict
        tolerance: Allowed percentage deviation (default 10%)

    Returns:
        Dict with validation results: {"ok": bool, "delta_pct": float, "expected": float, "actual": float}
    """
    try:
        # Extract totals if we got a list of items
        if isinstance(items_or_totals, list):
            total_kcal = sum(item["kcal"] for item in items_or_totals)
            total_protein = sum(item["protein_g"] for item in items_or_totals)
            total_carb = sum(item["carb_g"] for item in items_or_totals)
            total_fat = sum(item["fat_g"] for item in items_or_totals)
        else:
            # Assume it's a totals dict
            total_kcal = items_or_totals.get("kcal", 0)
            total_protein = items_or_totals.get("protein_g", 0)
            total_carb = items_or_totals.get("carb_g", 0)
            total_fat = items_or_totals.get("fat_g", 0)

        # Calculate expected calories: 4 * protein + 4 * carbs + 9 * fat
        expected_kcal = (4 * total_protein) + (4 * total_carb) + (9 * total_fat)

        # Handle edge cases
        if expected_kcal == 0 and total_kcal == 0:
            return {"ok": True, "delta_pct": 0.0, "expected": 0.0, "actual": 0.0}

        if expected_kcal == 0:
            return {"ok": False, "delta_pct": 1.0, "expected": 0.0, "actual": total_kcal}

        # Calculate percentage difference
        delta_pct = abs(total_kcal - expected_kcal) / expected_kcal
        is_valid = delta_pct <= tolerance

        return {
            "ok": is_valid,
            "delta_pct": delta_pct,
            "expected": expected_kcal,
            "actual": total_kcal,
            "tolerance": tolerance
        }

    except Exception as e:
        print(f"Error in 4/4/9 validation: {e}")
        return {"ok": False, "delta_pct": 1.0, "expected": 0.0, "actual": 0.0, "error": str(e)}


def validate_portion_bounds(scaled_items: List[ScaledItem]) -> List[Dict[str, Any]]:
    """
    Validate portion sizes against reasonable bounds.

    Args:
        scaled_items: List of ScaledItem objects

    Returns:
        List of warning dictionaries for items that exceed bounds
    """
    warnings = []

    try:
        for item in scaled_items:
            item_name = item["name"].lower().strip()
            item_grams = item["grams"]

            # Check against exact matches first
            for bound_name, bounds in PORTION_BOUNDS.items():
                if bound_name in item_name:
                    max_grams = bounds["max_grams"]
                    category = bounds["category"]

                    if item_grams > max_grams:
                        warnings.append({
                            "item_name": item["name"],
                            "actual_grams": item_grams,
                            "expected_max": max_grams,
                            "category": category,
                            "severity": "high" if item_grams > max_grams * 2 else "medium",
                            "message": f"{item['name']} ({item_grams}g) exceeds typical {category} portion (max ~{max_grams}g)"
                        })
                    break  # Only apply first matching bound

            # Additional heuristic checks
            if item_grams > 1000:  # 1kg+ portions are suspicious for any single ingredient
                warnings.append({
                    "item_name": item["name"],
                    "actual_grams": item_grams,
                    "expected_max": 1000,
                    "category": "general",
                    "severity": "high",
                    "message": f"{item['name']} ({item_grams}g) is unusually large for a single ingredient"
                })

    except Exception as e:
        print(f"Error in portion bounds validation: {e}")
        warnings.append({
            "item_name": "validation_error",
            "actual_grams": 0,
            "expected_max": 0,
            "category": "error",
            "severity": "high",
            "message": f"Portion validation failed: {e}"
        })

    return warnings


def compute_confidence(scaled_items: List[ScaledItem], validations: Dict[str, Any]) -> float:
    """
    Compute confidence score based on USDA grounding and validation results.

    Args:
        scaled_items: List of ScaledItem objects
        validations: Dict containing validation results

    Returns:
        Confidence score between 0.1 and 0.95
    """
    try:
        # Base confidence
        confidence = 0.8

        # Count fallback items (no USDA data)
        fallback_count = sum(1 for item in scaled_items if item["source"] == "fallback")
        total_items = len(scaled_items)

        if total_items > 0:
            fallback_ratio = fallback_count / total_items
            # Subtract up to -0.3 for fallback items
            confidence -= min(0.3, fallback_ratio * 0.5)

        # Check 4/4/9 validation
        four_four_nine = validations.get("four_four_nine", {})
        if not four_four_nine.get("ok", False):
            confidence -= 0.1

        # Check portion warnings
        portion_warnings = validations.get("portion_warnings", [])
        warning_penalty = min(0.2, len(portion_warnings) * 0.05)
        confidence -= warning_penalty

        # Additional penalties for severe issues
        high_severity_warnings = [w for w in portion_warnings if w.get("severity") == "high"]
        if high_severity_warnings:
            confidence -= len(high_severity_warnings) * 0.05

        # Check combo sanity warnings (P2-E1) - capped at 0.3 max penalty
        combo_sanity_warnings = validations.get("combo_sanity_warnings", [])
        raw_combo_penalty = len(combo_sanity_warnings) * 0.1
        combo_penalty = min(0.3, raw_combo_penalty)  # Cap at 0.3
        confidence -= combo_penalty

        if combo_sanity_warnings:
            print(f"DEBUG: Combo sanity penalty: {raw_combo_penalty:.2f} (capped at {combo_penalty:.2f})")

        # Clamp to valid range
        confidence = max(0.1, min(0.95, confidence))

        return confidence

    except Exception as e:
        print(f"Error computing confidence: {e}")
        return 0.1  # Lowest confidence on error


# Category-based kcal/100g sanity bands
CATEGORY_KCAL_BANDS = {
    "rice_mixed_main": (150, 250),  # Biryani, pulao, fried rice
    "yogurt_side": (60, 120),        # Raita, tzatziki
    "curry": (80, 180),              # Curries and stews
    "salad": (30, 150),              # Salads
}


def validate_category_sanity_bands(scaled_items: List[ScaledItem]) -> List[str]:
    """
    Validate that food categories fall within expected kcal/100g ranges.

    Args:
        scaled_items: List of scaled items with nutrition data

    Returns:
        List of warning strings
    """
    warnings = []

    for item in scaled_items:
        # Calculate kcal per 100g
        grams = item.get("grams", 0)
        kcal = item.get("kcal", 0)

        if grams > 0:
            kcal_per_100g = (kcal / grams) * 100

            # Check category-specific bands
            name = item.get("name", "").lower()

            # Determine category from name
            category = None
            if any(kw in name for kw in ["biryani", "pulao", "fried rice", "paella"]):
                category = "rice_mixed_main"
            elif any(kw in name for kw in ["raita", "tzatziki"]):
                category = "yogurt_side"
            elif any(kw in name for kw in ["curry", "dal", "stew"]):
                category = "curry"
            elif "salad" in name:
                category = "salad"

            if category and category in CATEGORY_KCAL_BANDS:
                min_kcal, max_kcal = CATEGORY_KCAL_BANDS[category]

                if kcal_per_100g < min_kcal:
                    warnings.append(f"{item.get('name')}: {kcal_per_100g:.0f} kcal/100g below expected range ({min_kcal}-{max_kcal})")
                elif kcal_per_100g > max_kcal:
                    warnings.append(f"{item.get('name')}: {kcal_per_100g:.0f} kcal/100g above expected range ({min_kcal}-{max_kcal})")

    return warnings


def validate_composition_consistency(ingredients_raw: List[Dict[str, Any]]) -> List[str]:
    """
    Validate that compound items are properly decomposed when component notes exist.

    Warns if a compound category item (smoothie/shake/salad/sandwich) has component
    notes but wasn't decomposed into separate ingredients.

    Args:
        ingredients_raw: Raw ingredients before USDA grounding (need notes field)

    Returns:
        List of warning strings
    """
    warnings = []
    compound_keywords = ['smoothie', 'shake', 'protein shake', 'salad', 'sandwich', 'wrap', 'burrito', 'bowl']

    for ingredient in ingredients_raw:
        name_lower = ingredient.get('name', '').lower()
        notes = ingredient.get('notes', '') or ''
        notes_lower = notes.lower()

        # Check if this is a compound item that should have been decomposed
        is_compound = any(kw in name_lower for kw in compound_keywords)
        has_component_notes = any(word in notes_lower for word in ['protein powder', 'whey', 'casein', 'base', 'milk', 'with'])

        if is_compound and has_component_notes:
            warnings.append(f"Compound item '{ingredient.get('name')}' with component notes ('{notes}') was not decomposed - may have inaccurate macros")

    return warnings


def run_all_validations(scaled_items: List[ScaledItem], dish: str = "") -> Dict[str, Any]:
    """
    Run all validation checks and compute confidence score.

    Args:
        scaled_items: List of ScaledItem objects
        dish: Dish name for context (optional)

    Returns:
        Complete validation results with confidence score
    """
    try:
        # Run individual validations
        four_four_nine = validate_4_4_9(scaled_items)
        portion_warnings = validate_portion_bounds(scaled_items)
        combo_sanity_warnings = validate_combo_sanity_caps(scaled_items, dish)
        category_sanity_warnings = validate_category_sanity_bands(scaled_items)

        # Package validation results
        validations = {
            "four_four_nine": four_four_nine,
            "portion_warnings": portion_warnings,
            "combo_sanity_warnings": combo_sanity_warnings,
            "category_sanity_warnings": category_sanity_warnings
        }

        # Compute confidence (include combo sanity in penalty calculation)
        confidence = compute_confidence(scaled_items, validations)

        return {
            **validations,
            "confidence": confidence,
            "summary": {
                "total_items": len(scaled_items),
                "usda_grounded": sum(1 for item in scaled_items if item["source"] == "USDA"),
                "fallback_items": sum(1 for item in scaled_items if item["source"] == "fallback"),
                "macro_validation_passed": four_four_nine.get("ok", False),
                "portion_warnings_count": len(portion_warnings),
                "combo_sanity_warnings_count": len(combo_sanity_warnings),
                "confidence_score": confidence
            }
        }

    except Exception as e:
        print(f"Error running validations: {e}")
        return {
            "four_four_nine": {"ok": False, "error": str(e)},
            "portion_warnings": [],
            "combo_sanity_warnings": [],
            "confidence": 0.1,
            "summary": {
                "total_items": 0,
                "usda_grounded": 0,
                "fallback_items": 0,
                "macro_validation_passed": False,
                "portion_warnings_count": 0,
                "combo_sanity_warnings_count": 0,
                "confidence_score": 0.1
            }
        }


def validate_amount_source_contract(ingredients: List[Ingredient]) -> List[Dict[str, Any]]:
    """
    Validate that amount/source contract is satisfied for all ingredients.

    Contract rules:
    - If amount is set (not None), source MUST be 'user', 'vision', or 'portion-resolver'
    - If amount is None, portion_label should be present

    Args:
        ingredients: List of Ingredient objects

    Returns:
        List of validation errors (empty if all pass)
    """
    errors = []

    for i, ingredient in enumerate(ingredients):
        # Check if amount is set without proper source
        if ingredient.amount is not None and ingredient.amount > 0:
            if ingredient.source not in ("user", "vision", "portion-resolver"):
                errors.append({
                    "ingredient_index": i,
                    "ingredient_name": ingredient.name,
                    "error_type": "invalid_amount_source",
                    "message": f"Ingredient '{ingredient.name}' has amount={ingredient.amount}g but source='{ingredient.source}'. "
                               f"Amount can only be set with source='user'/'vision'/'portion-resolver'.",
                    "severity": "high"
                })

        # Check if both amount and portion_label are None (incomplete data)
        if ingredient.amount is None and not ingredient.portion_label:
            errors.append({
                "ingredient_index": i,
                "ingredient_name": ingredient.name,
                "error_type": "incomplete_portion_data",
                "message": f"Ingredient '{ingredient.name}' has neither amount nor portion_label. One must be set.",
                "severity": "high"
            })

    return errors


def validate_incomplete_portions(ingredients: List[Ingredient]) -> Dict[str, Any]:
    """
    Check for ingredients that still have unresolved portion labels.

    Args:
        ingredients: List of Ingredient objects

    Returns:
        Dict with validation results
    """
    incomplete_items = []

    for ingredient in ingredients:
        # Flag items that have portion_label but no amount (need portion resolution)
        if ingredient.amount is None and ingredient.portion_label:
            incomplete_items.append({
                "name": ingredient.name,
                "portion_label": ingredient.portion_label,
                "source": ingredient.source,
                "notes": ingredient.notes
            })

    return {
        "has_incomplete_portions": len(incomplete_items) > 0,
        "incomplete_count": len(incomplete_items),
        "incomplete_items": incomplete_items,
        "message": f"{len(incomplete_items)} ingredient(s) need portion resolution" if incomplete_items else "All portions resolved"
    }


def validate_combo_sanity_caps(scaled_items: List[ScaledItem], dish: str) -> List[Dict[str, Any]]:
    """
    Runtime guard: Detect implausible macro combinations.

    Examples:
    - 2000+ kcal from diet soda (diet = <10 kcal/100ml)
    - >50g protein from salad greens
    - >80g fat from grilled chicken breast

    Args:
        scaled_items: List of ScaledItem objects
        dish: Dish name for context

    Returns:
        List of warning dictionaries for implausible combos
    """
    warnings = []

    try:
        for item in scaled_items:
            item_name = item["name"].lower().strip()
            kcal = item["kcal"]
            protein_g = item["protein_g"]
            fat_g = item["fat_g"]
            carb_g = item["carb_g"]
            grams = item["grams"]

            # Diet/zero beverages should have <10 kcal per 100ml
            diet_keywords = ["diet", "zero", "light", "sugar-free"]
            if any(kw in item_name for kw in diet_keywords):
                if "soda" in item_name or "cola" in item_name or "beverage" in item_name or "drink" in item_name:
                    # Get density for beverage type (g/ml) - fallback to 1.00 if unknown
                    density = None
                    density_source = "unknown"
                    for bev_type, bev_density in BEVERAGE_DENSITY.items():
                        if bev_type in item_name:
                            density = bev_density
                            density_source = bev_type
                            break

                    if density is None:
                        density = BEVERAGE_DENSITY["default"]
                        density_source = "default"
                        print(f"DEBUG: Using default density (1.00 g/mL) for '{item_name}' - brand/type unknown")

                    ml_equivalent = grams / density  # Convert grams to ml
                    expected_max_kcal = (ml_equivalent / 100) * 10  # 10 kcal per 100ml

                    if kcal > expected_max_kcal * 2:  # Allow 2x tolerance
                        warnings.append({
                            "item_name": item["name"],
                            "kcal": kcal,
                            "expected_max": expected_max_kcal,
                            "category": "diet_beverage_kcal",
                            "severity": "high",
                            "unit": "per_100ml",
                            "density_used": density,
                            "density_source": density_source,  # "cola", "soda", or "default"
                            "message": f"'{item['name']}' is marked diet/zero but has {kcal}kcal (expected <{expected_max_kcal:.0f}kcal for {ml_equivalent:.0f}ml)"
                        })

            # Leafy greens/salad shouldn't have >10g protein per 100g
            leafy_keywords = ["lettuce", "spinach", "arugula", "kale", "salad", "greens"]
            if any(kw in item_name for kw in leafy_keywords):
                protein_per_100g = (protein_g / grams) * 100 if grams > 0 else 0
                if protein_per_100g > 10:
                    warnings.append({
                        "item_name": item["name"],
                        "protein_g": protein_g,
                        "protein_per_100g": protein_per_100g,
                        "category": "leafy_protein",
                        "severity": "high",
                        "message": f"'{item['name']}' (leafy green) has {protein_per_100g:.1f}g protein per 100g (expected <10g)"
                    })

            # Lean proteins (chicken breast, turkey, white fish) shouldn't exceed 15% fat by weight
            lean_keywords = ["chicken breast", "turkey breast", "cod", "tilapia", "haddock", "white fish", "tuna"]
            if any(kw in item_name for kw in lean_keywords):
                fat_pct = (fat_g / grams) * 100 if grams > 0 else 0
                if fat_pct > 15:
                    warnings.append({
                        "item_name": item["name"],
                        "fat_g": fat_g,
                        "fat_pct": fat_pct,
                        "category": "lean_protein_fat",
                        "severity": "high",
                        "message": f"'{item['name']}' (lean protein) has {fat_pct:.1f}% fat by weight (expected <15%)"
                    })

            # Skim/fat-free milk should have <1% fat by weight
            skim_keywords = ["skim", "fat-free", "nonfat", "0%"]
            if any(kw in item_name for kw in skim_keywords) and "milk" in item_name:
                fat_pct = (fat_g / grams) * 100 if grams > 0 else 0
                if fat_pct > 1:
                    warnings.append({
                        "item_name": item["name"],
                        "fat_g": fat_g,
                        "fat_pct": fat_pct,
                        "category": "skim_milk_fat",
                        "severity": "high",
                        "message": f"'{item['name']}' (skim/fat-free) has {fat_pct:.1f}% fat (expected <1%)"
                    })

            # Water should have 0 kcal
            if item_name == "water" or item_name == "plain water":
                if kcal > 0:
                    warnings.append({
                        "item_name": item["name"],
                        "kcal": kcal,
                        "expected": 0,
                        "category": "water_kcal",
                        "severity": "high",
                        "message": f"Water should have 0 kcal, got {kcal}kcal"
                    })

        if warnings:
            # Log each warning with unit information (privacy-aware)
            for warning in warnings:
                metric = {
                    "event": "combo_sanity_fail",
                    "dish": dish,
                    "item": warning["item_name"],
                    "category": warning["category"],
                    "severity": warning["severity"]
                }
                if "unit" in warning:
                    metric["unit"] = warning["unit"]
                if "density_used" in warning:
                    metric["density"] = warning["density_used"]
                print(f"METRICS: {json.dumps(sanitize_metrics(metric))}")

    except Exception as e:
        print(f"Error in combo sanity validation: {e}")
        warnings.append({
            "item_name": "validation_error",
            "category": "error",
            "severity": "high",
            "message": f"Combo sanity check failed: {e}"
        })

    return warnings


def format_validation_summary(validations: Dict[str, Any]) -> str:
    """
    Format validation results into a user-friendly summary.

    Args:
        validations: Validation results from run_all_validations

    Returns:
        Formatted string summary
    """
    try:
        summary = validations.get("summary", {})
        confidence = summary.get("confidence_score", 0.0)

        lines = []
        lines.append(f"**Confidence Score: {confidence:.1%}**")

        # USDA grounding status
        usda_count = summary.get("usda_grounded", 0)
        total_count = summary.get("total_items", 0)
        if total_count > 0:
            usda_pct = usda_count / total_count
            lines.append(f"• {usda_count}/{total_count} ingredients grounded with USDA data ({usda_pct:.0%})")

        # Macro validation
        if summary.get("macro_validation_passed", False):
            lines.append("• ✅ Macronutrient ratios are reasonable")
        else:
            four_four_nine = validations.get("four_four_nine", {})
            if "delta_pct" in four_four_nine:
                delta = four_four_nine["delta_pct"]
                lines.append(f"• ⚠️ Calorie calculation may be off by {delta:.1%}")

        # Portion warnings
        warning_count = summary.get("portion_warnings_count", 0)
        if warning_count == 0:
            lines.append("• ✅ All portion sizes look reasonable")
        else:
            lines.append(f"• ⚠️ {warning_count} portion size warning(s)")

        return "\n".join(lines)

    except Exception as e:
        return f"Validation summary error: {e}"