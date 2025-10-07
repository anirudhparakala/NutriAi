from typing import Dict, List, Any, Union
from .nutrition_lookup import ScaledItem

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

        # Clamp to valid range
        confidence = max(0.1, min(0.95, confidence))

        return confidence

    except Exception as e:
        print(f"Error computing confidence: {e}")
        return 0.1  # Lowest confidence on error


def run_all_validations(scaled_items: List[ScaledItem]) -> Dict[str, Any]:
    """
    Run all validation checks and compute confidence score.

    Args:
        scaled_items: List of ScaledItem objects

    Returns:
        Complete validation results with confidence score
    """
    try:
        # Run individual validations
        four_four_nine = validate_4_4_9(scaled_items)
        portion_warnings = validate_portion_bounds(scaled_items)

        # Package validation results
        validations = {
            "four_four_nine": four_four_nine,
            "portion_warnings": portion_warnings
        }

        # Compute confidence
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
                "confidence_score": confidence
            }
        }

    except Exception as e:
        print(f"Error running validations: {e}")
        return {
            "four_four_nine": {"ok": False, "error": str(e)},
            "portion_warnings": [],
            "confidence": 0.1,
            "summary": {
                "total_items": 0,
                "usda_grounded": 0,
                "fallback_items": 0,
                "macro_validation_passed": False,
                "portion_warnings_count": 0,
                "confidence_score": 0.1
            }
        }


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