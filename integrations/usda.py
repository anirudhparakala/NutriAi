import requests
import functools
from typing import Dict, List, Optional

# USDA FoodData Central API endpoints
FDC_SEARCH = "https://api.nal.usda.gov/fdc/v1/foods/search"
FDC_FOOD = "https://api.nal.usda.gov/fdc/v1/food"

# Will be set from app.py secrets
FDC_API_KEY = None


def set_api_key(api_key: str):
    """Set the USDA API key from app configuration."""
    global FDC_API_KEY
    FDC_API_KEY = api_key


@functools.lru_cache(maxsize=512)
def search_food(name: str, page_size: int = 5) -> List[Dict]:
    """
    Search for foods in USDA database.

    Args:
        name: Food name to search for
        page_size: Number of results to return

    Returns:
        List of food items from USDA database
    """
    if not FDC_API_KEY:
        print("Warning: USDA API key not set")
        return []

    params = {
        "api_key": FDC_API_KEY,
        "query": name,
        "pageSize": page_size,
        "dataType": "Survey (FNDDS),SR Legacy,Branded"  # Prefer comprehensive data
    }

    try:
        response = requests.get(FDC_SEARCH, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("foods", [])
    except Exception as e:
        print(f"USDA search failed for '{name}': {e}")
        return []


def get_food_details(fdc_id: int) -> Optional[Dict]:
    """
    Get detailed nutrition information for a specific food ID.

    Args:
        fdc_id: FoodData Central ID

    Returns:
        Detailed food information or None if not found
    """
    if not FDC_API_KEY:
        print("Warning: USDA API key not set")
        return None

    params = {
        "api_key": FDC_API_KEY
    }

    try:
        response = requests.get(f"{FDC_FOOD}/{fdc_id}", params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"USDA food details failed for ID {fdc_id}: {e}")
        return None


def per100g_macros(food: Dict) -> Dict[str, float]:
    """
    Extract macronutrients per 100g from USDA food data.

    Args:
        food: USDA food data dictionary

    Returns:
        Dict with calories, protein_grams, carbs_grams, fat_grams per 100g
    """
    nutrients = food.get("foodNutrients", [])

    # Create index by nutrient name (case-insensitive)
    nutrient_index = {}
    for nutrient in nutrients:
        name = nutrient.get("nutrientName", "").lower()
        nutrient_index[name] = nutrient

    def get_nutrient_value(name: str) -> float:
        """Get nutrient value, defaulting to 0 if not found."""
        nutrient = nutrient_index.get(name.lower(), {})
        return float(nutrient.get("value", 0))

    # Map common nutrient names to USDA names
    calories = (
        get_nutrient_value("energy") or
        get_nutrient_value("energy (atwater general factors)") or
        get_nutrient_value("energy (kcal)")
    )

    protein = (
        get_nutrient_value("protein") or
        get_nutrient_value("protein (g)")
    )

    carbs = (
        get_nutrient_value("carbohydrate, by difference") or
        get_nutrient_value("carbohydrate") or
        get_nutrient_value("total carbohydrate")
    )

    fat = (
        get_nutrient_value("total lipid (fat)") or
        get_nutrient_value("fat") or
        get_nutrient_value("total fat")
    )

    return {
        "calories": calories,
        "protein_grams": protein,
        "carbs_grams": carbs,
        "fat_grams": fat
    }


def find_best_match(ingredient_name: str, search_results: List[Dict]) -> Optional[Dict]:
    """
    Find the best matching food from search results.

    Args:
        ingredient_name: Name we're looking for
        search_results: List of USDA food search results

    Returns:
        Best matching food item or None
    """
    if not search_results:
        return None

    ingredient_lower = ingredient_name.lower()

    # Scoring function for matches
    def score_match(food: Dict) -> float:
        description = food.get("description", "").lower()
        score = 0

        # Exact match gets highest score
        if ingredient_lower == description:
            score += 100

        # Partial matches
        ingredient_words = ingredient_lower.split()
        description_words = description.split()

        for word in ingredient_words:
            if word in description:
                score += 10

        # Prefer "raw" over "cooked" for base ingredients
        if "raw" in description:
            score += 5
        elif "cooked" in description:
            score += 2

        # Prefer SR Legacy (most comprehensive) over branded
        data_type = food.get("dataType", "")
        if "SR Legacy" in data_type:
            score += 3
        elif "Survey" in data_type:
            score += 2

        return score

    # Sort by score and return best match
    scored_results = [(food, score_match(food)) for food in search_results]
    scored_results.sort(key=lambda x: x[1], reverse=True)

    best_match, best_score = scored_results[0]
    if best_score > 0:
        return best_match

    return None


def lookup_nutrition(ingredient_name: str, amount_grams: float) -> Optional[Dict[str, float]]:
    """
    Look up nutrition information for an ingredient and scale to specified amount.

    Args:
        ingredient_name: Name of ingredient
        amount_grams: Amount in grams

    Returns:
        Scaled nutrition info or None if not found
    """
    try:
        # Search for the ingredient
        search_results = search_food(ingredient_name)
        if not search_results:
            print(f"No USDA results found for '{ingredient_name}'")
            return None

        # Find best match
        best_match = find_best_match(ingredient_name, search_results)
        if not best_match:
            print(f"No good USDA match found for '{ingredient_name}'")
            return None

        # Get nutrition per 100g
        per100g = per100g_macros(best_match)

        # Scale to actual amount
        scale_factor = amount_grams / 100.0
        scaled_nutrition = {
            "calories": per100g["calories"] * scale_factor,
            "protein_grams": per100g["protein_grams"] * scale_factor,
            "carbs_grams": per100g["carbs_grams"] * scale_factor,
            "fat_grams": per100g["fat_grams"] * scale_factor,
            "usda_match": best_match.get("description", ""),
            "usda_id": best_match.get("fdcId", "")
        }

        print(f"USDA lookup: '{ingredient_name}' -> '{scaled_nutrition['usda_match']}'")
        return scaled_nutrition

    except Exception as e:
        print(f"USDA lookup failed for '{ingredient_name}': {e}")
        return None


def batch_lookup_nutrition(ingredients: List[Dict]) -> List[Dict]:
    """
    Look up nutrition for multiple ingredients.

    Args:
        ingredients: List of ingredient dicts with 'name' and 'amount' fields

    Returns:
        List of nutrition results (may include None for failed lookups)
    """
    results = []
    for ingredient in ingredients:
        name = ingredient.get("name", "")
        amount = float(ingredient.get("amount", 0))

        if name and amount > 0:
            nutrition = lookup_nutrition(name, amount)
            results.append(nutrition)
        else:
            results.append(None)

    return results


def validate_nutrition_totals(nutrition_data: List[Dict]) -> Dict[str, bool]:
    """
    Validate nutrition totals using the 4/4/9 rule (protein/carbs/fat calories).

    Args:
        nutrition_data: List of nutrition dicts from USDA lookup

    Returns:
        Dict with validation results
    """
    total_calories = sum(item["calories"] for item in nutrition_data if item)
    total_protein = sum(item["protein_grams"] for item in nutrition_data if item)
    total_carbs = sum(item["carbs_grams"] for item in nutrition_data if item)
    total_fat = sum(item["fat_grams"] for item in nutrition_data if item)

    # Calculate calories from macros (4 kcal/g protein & carbs, 9 kcal/g fat)
    calculated_calories = (total_protein * 4) + (total_carbs * 4) + (total_fat * 9)

    # Allow 10% variance for validation
    variance = abs(total_calories - calculated_calories) / max(total_calories, 1)
    calories_valid = variance <= 0.10

    return {
        "calories_valid": calories_valid,
        "total_calories": total_calories,
        "calculated_calories": calculated_calories,
        "variance_percent": variance * 100,
        "total_protein": total_protein,
        "total_carbs": total_carbs,
        "total_fat": total_fat
    }