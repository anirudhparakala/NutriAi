from typing import TypedDict, Literal, Dict, List, Optional, Any
from integrations import usda_client, normalize
import re

# Type definitions for structured data
class GroundedItem(TypedDict):
    """Item with USDA grounding information."""
    name: str
    normalized_name: str
    fdc_id: Optional[int]
    source: Literal["USDA", "fallback"]
    per100g: Dict[str, float]  # {"kcal": float, "protein_g": float, "carb_g": float, "fat_g": float}


class ScaledItem(TypedDict):
    """Item scaled to actual portion size."""
    name: str
    grams: float
    kcal: float
    protein_g: float
    carb_g: float
    fat_g: float
    source: str
    fdc_id: Optional[int]


# Configuration policy
GROUNDING_POLICY = {
    "usda_first": True,
    "allow_fallback_zeroes": True
}


def normalize_and_ground(name: str, search_fn=None) -> tuple[GroundedItem, int]:
    """
    Normalize ingredient name and ground it with USDA data.

    Args:
        name: Raw ingredient name from vision/user input
        search_fn: Optional search function for web-assisted normalization

    Returns:
        Tuple of (GroundedItem with USDA data or fallback zeros, tool_calls_count)
    """
    print(f"DEBUG: normalize_and_ground() called with name='{name}', search_fn={'available' if search_fn else 'None'}")

    tool_calls_count = 0
    try:
        # Step 1: Normalize the ingredient name
        if search_fn:
            print(f"DEBUG: Using web search to normalize '{name}'")
            normalized_name = normalize.normalize_with_web(name, search_fn)
            tool_calls_count += 1  # Count actual web search usage
            print(f"DEBUG: Web normalization result: '{name}' -> '{normalized_name}'")
        else:
            # Basic normalization without web assistance
            import re
            normalized_name = re.sub(r"\(.*?\)", "", name).lower().strip()
            print(f"DEBUG: Basic normalization result: '{name}' -> '{normalized_name}'")

        # Step 2: Search USDA database
        print(f"DEBUG: Searching USDA for normalized name '{normalized_name}'")
        usda_match = usda_client.search_best_match(normalized_name)

        if usda_match:
            print(f"DEBUG: USDA match found - FDC ID: {usda_match.get('fdcId')}, Description: {usda_match.get('description', 'N/A')}")

            # Extract macros from USDA data
            macros = usda_client.per100g_macros(usda_match)
            print(f"DEBUG: Extracted per100g macros: {macros}")

            # Sanity check: diet/zero beverages should have near-zero calories
            name_lower = name.lower()
            variant_keywords = ['diet', 'zero', 'sugar-free', 'sugar free', 'no sugar', 'unsweetened', 'black', 'plain']
            has_variant = any(kw in name_lower for kw in variant_keywords)
            is_beverage = any(bev in name_lower for bev in ['cola', 'soda', 'pop', 'drink', 'tea', 'coffee', 'water', 'juice'])

            if has_variant and is_beverage and macros['kcal'] > 10:
                print(f"WARNING: Beverage '{name}' has variant keyword (diet/zero/unsweetened) but USDA returned {macros['kcal']} kcal/100g")
                print(f"WARNING: This likely indicates wrong USDA match. Expected near-zero calories for this variant.")
                print(f"WARNING: Matched description: {usda_match.get('description', 'N/A')}")
                # Still return the data but log the warning for debugging

            fdc_id = usda_match.get('fdcId')

            grounded_item = GroundedItem(
                name=name,
                normalized_name=normalized_name,
                fdc_id=fdc_id,
                source="USDA",
                per100g=macros
            )
            print(f"DEBUG: Created GroundedItem: {grounded_item}")
            return grounded_item, tool_calls_count
        else:
            # Fallback to zeros if no USDA match found
            print(f"WARNING: No USDA match found for '{normalized_name}', using fallback zeros")
            return GroundedItem(
                name=name,
                normalized_name=normalized_name,
                fdc_id=None,
                source="fallback",
                per100g={
                    "kcal": 0.0,
                    "protein_g": 0.0,
                    "carb_g": 0.0,
                    "fat_g": 0.0
                }
            ), tool_calls_count

    except Exception as e:
        print(f"Error grounding ingredient '{name}': {e}")
        # Return fallback on any error
        return GroundedItem(
            name=name,
            normalized_name=name.lower().strip(),
            fdc_id=None,
            source="fallback",
            per100g={
                "kcal": 0.0,
                "protein_g": 0.0,
                "carb_g": 0.0,
                "fat_g": 0.0
            }
        ), tool_calls_count


def scale_item(grounded: GroundedItem, grams: float) -> ScaledItem:
    """
    Scale a grounded item to actual portion size.

    Args:
        grounded: GroundedItem with per-100g macros
        grams: Actual portion size in grams

    Returns:
        ScaledItem with macros scaled to portion size
    """
    try:
        # Calculate scaling factor (grams / 100)
        scale_factor = grams / 100.0
        print(f"DEBUG: Scaling '{grounded['name']}' from {grounded['per100g']['kcal']} kcal/100g to {grams}g (factor: {scale_factor})")

        # Scale macros (round internally to 2 decimals for consistency)
        scaled_kcal = round(grounded["per100g"]["kcal"] * scale_factor, 2)
        scaled_protein = round(grounded["per100g"]["protein_g"] * scale_factor, 2)
        scaled_carb = round(grounded["per100g"]["carb_g"] * scale_factor, 2)
        scaled_fat = round(grounded["per100g"]["fat_g"] * scale_factor, 2)

        print(f"DEBUG: Scaled macros for '{grounded['name']}': {scaled_kcal} kcal, {scaled_protein}g protein, {scaled_carb}g carbs, {scaled_fat}g fat")

        scaled_item = ScaledItem(
            name=grounded["name"],
            grams=grams,
            kcal=scaled_kcal,
            protein_g=scaled_protein,
            carb_g=scaled_carb,
            fat_g=scaled_fat,
            source=grounded["source"],
            fdc_id=grounded["fdc_id"]
        )

        return scaled_item

    except Exception as e:
        print(f"Error scaling item '{grounded['name']}': {e}")
        # Return zeros on error
        return ScaledItem(
            name=grounded["name"],
            grams=grams,
            kcal=0.0,
            protein_g=0.0,
            carb_g=0.0,
            fat_g=0.0,
            source="error",
            fdc_id=None
        )


def compute_totals(items: List[ScaledItem]) -> Dict[str, Any]:
    """
    Compute total macros from a list of scaled items.

    Args:
        items: List of ScaledItem objects

    Returns:
        Dict with float totals and integer display fields
    """
    try:
        # Sum with full precision
        total_kcal = sum(item["kcal"] for item in items)
        total_protein = sum(item["protein_g"] for item in items)
        total_carb = sum(item["carb_g"] for item in items)
        total_fat = sum(item["fat_g"] for item in items)

        return {
            # Full precision for calculations
            "kcal": total_kcal,
            "protein_g": total_protein,
            "carb_g": total_carb,
            "fat_g": total_fat,
            # Integer display values
            "kcal_display": int(round(total_kcal)),
            "protein_display": int(round(total_protein)),
            "carb_display": int(round(total_carb)),
            "fat_display": int(round(total_fat)),
            # Meta information
            "item_count": len(items),
            "usda_count": sum(1 for item in items if item["source"] == "USDA"),
            "fallback_count": sum(1 for item in items if item["source"] == "fallback")
        }

    except Exception as e:
        print(f"Error computing totals: {e}")
        return {
            "kcal": 0.0,
            "protein_g": 0.0,
            "carb_g": 0.0,
            "fat_g": 0.0,
            "kcal_display": 0,
            "protein_display": 0,
            "carb_display": 0,
            "fat_display": 0,
            "item_count": 0,
            "usda_count": 0,
            "fallback_count": 0
        }


def ground_ingredients_list(ingredients: List[Dict], search_fn=None) -> tuple[List[GroundedItem], int]:
    """
    Ground a list of ingredients with USDA data.

    Args:
        ingredients: List of ingredient dicts with 'name' and 'amount' fields
        search_fn: Optional search function for web-assisted normalization

    Returns:
        Tuple of (List of GroundedItem objects, total_tool_calls_count)
    """
    grounded_items = []
    total_tool_calls = 0

    for ingredient in ingredients:
        try:
            name = ingredient.get('name', '')
            if name:
                grounded, tool_calls = normalize_and_ground(name, search_fn)
                grounded_items.append(grounded)
                total_tool_calls += tool_calls
            else:
                print(f"Skipping ingredient with missing name: {ingredient}")
        except Exception as e:
            print(f"Error grounding ingredient {ingredient}: {e}")
            # Add fallback item
            fallback = GroundedItem(
                name=str(ingredient),
                normalized_name="unknown",
                fdc_id=None,
                source="fallback",
                per100g={"kcal": 0.0, "protein_g": 0.0, "carb_g": 0.0, "fat_g": 0.0}
            )
            grounded_items.append(fallback)

    return grounded_items, total_tool_calls


def scale_ingredients_list(ingredients: List[Dict], grounded_items: List[GroundedItem]) -> List[ScaledItem]:
    """
    Scale grounded ingredients to their actual portion sizes.

    Args:
        ingredients: List of ingredient dicts with 'name' and 'amount' fields
        grounded_items: List of corresponding GroundedItem objects

    Returns:
        List of ScaledItem objects
    """
    scaled_items = []

    for ingredient, grounded in zip(ingredients, grounded_items):
        try:
            amount = ingredient.get('amount', 0)
            if isinstance(amount, (int, float)) and amount > 0:
                scaled = scale_item(grounded, float(amount))
                scaled_items.append(scaled)
            else:
                print(f"Skipping ingredient with invalid amount: {ingredient}")
        except Exception as e:
            print(f"Error scaling ingredient {ingredient}: {e}")

    return scaled_items


def build_deterministic_breakdown(ingredients: List[Dict], search_fn=None) -> tuple[Dict[str, Any], int]:
    """
    Build a complete deterministic breakdown from ingredients list.

    Args:
        ingredients: List of ingredient dicts with 'name' and 'amount' fields
        search_fn: Optional search function for web-assisted normalization

    Returns:
        Tuple of (Complete breakdown with items, totals, and metadata, tool_calls_count)
    """
    print(f"DEBUG: build_deterministic_breakdown() called with {len(ingredients)} ingredients")
    for i, ing in enumerate(ingredients):
        print(f"DEBUG: Ingredient {i}: {ing}")

    try:
        # Step 1: Ground all ingredients
        print(f"DEBUG: Step 1 - Grounding all ingredients")
        grounded_items, tool_calls_count = ground_ingredients_list(ingredients, search_fn)
        print(f"DEBUG: Grounding completed - got {len(grounded_items)} grounded items, {tool_calls_count} tool calls")

        # Step 2: Scale to actual portions
        print(f"DEBUG: Step 2 - Scaling to actual portions")
        scaled_items = scale_ingredients_list(ingredients, grounded_items)
        print(f"DEBUG: Scaling completed - got {len(scaled_items)} scaled items")

        # Step 3: Compute totals
        print(f"DEBUG: Step 3 - Computing totals")
        totals = compute_totals(scaled_items)
        print(f"DEBUG: Totals computed: {totals}")

        # Step 4: Build attribution for USDA-backed items
        print(f"DEBUG: Step 4 - Building USDA attribution")
        attribution = []
        for item in scaled_items:
            if item["fdc_id"]:
                attribution.append({
                    "name": item["name"],
                    "fdc_id": item["fdc_id"]
                })

        return {
            "items": scaled_items,
            "totals": totals,
            "attribution": attribution,
            "grounding_policy": GROUNDING_POLICY
        }, tool_calls_count

    except Exception as e:
        print(f"Error building deterministic breakdown: {e}")
        return {
            "items": [],
            "totals": compute_totals([]),
            "attribution": [],
            "grounding_policy": GROUNDING_POLICY
        }, 0