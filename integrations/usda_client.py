import requests
import json
import os
import pickle
import hashlib
from functools import lru_cache
from typing import Dict, List, Optional, Any
from difflib import SequenceMatcher
import time
import re

# Global API key storage
_api_key: Optional[str] = None

# Constants
USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"
CACHE_DIR = ".cache/usda"
CACHE_SIZE = 512
REQUEST_TIMEOUT = 10
MAX_RETRIES = 3
BACKOFF_FACTOR = 1.5

# Data type preferences (higher score = preferred)
DATA_TYPE_SCORES = {
    "Survey (FNDDS)": 3,
    "SR Legacy": 2,
    "Branded": 1
}


def set_api_key(key: str) -> None:
    """Set the USDA API key for all requests."""
    global _api_key
    _api_key = key


def _ensure_cache_dir():
    """Ensure cache directory exists."""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)


def _normalize_query(query: str) -> str:
    """Normalize query for consistent caching and comparison."""
    return re.sub(r'[^\w\s]', '', query.lower().strip())


def _cache_key(query: str) -> str:
    """Generate cache key for a query."""
    normalized = _normalize_query(query)
    return hashlib.md5(normalized.encode()).hexdigest()


def _load_from_cache(query: str) -> Optional[Dict]:
    """Load result from disk cache."""
    try:
        _ensure_cache_dir()
        cache_file = os.path.join(CACHE_DIR, f"{_cache_key(query)}.pkl")
        if os.path.exists(cache_file):
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
    except Exception as e:
        print(f"Cache load error for query '{query}': {e}")
    return None


def _save_to_cache(query: str, result: Dict) -> None:
    """Save result to disk cache."""
    try:
        _ensure_cache_dir()
        cache_file = os.path.join(CACHE_DIR, f"{_cache_key(query)}.pkl")
        with open(cache_file, 'wb') as f:
            pickle.dump(result, f)
    except Exception as e:
        print(f"Cache save error for query '{query}': {e}")


@lru_cache(maxsize=CACHE_SIZE)
def _search_usda_api(query: str, page_size: int = 25) -> Optional[Dict]:
    """
    Search USDA API with retries and backoff.
    Uses LRU cache for in-memory caching.
    """
    if not _api_key:
        print("USDA API key not set. Call set_api_key() first.")
        return None

    # Check disk cache first
    cached_result = _load_from_cache(query)
    if cached_result:
        print(f"DEBUG: Using cached result for query '{query}'")
        return cached_result

    print(f"DEBUG: Making USDA API call for query '{query}'")

    url = f"{USDA_BASE_URL}/foods/search"
    params = {
        "api_key": _api_key,
        "query": query,
        "dataType": ["Survey (FNDDS)", "SR Legacy", "Branded"],
        "pageSize": page_size,
        "pageNumber": 1,
        "sortBy": "dataType.keyword",
        "sortOrder": "asc"
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            result = response.json()

            # Save to disk cache
            _save_to_cache(query, result)

            return result

        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                wait_time = BACKOFF_FACTOR ** attempt
                print(f"USDA API request failed (attempt {attempt + 1}), retrying in {wait_time}s: {e}")
                time.sleep(wait_time)
            else:
                print(f"USDA API request failed after {MAX_RETRIES} attempts: {e}")
                return None
        except Exception as e:
            print(f"Unexpected error during USDA API request: {e}")
            return None

    return None


def _calculate_similarity(query: str, food_description: str) -> float:
    """
    Calculate similarity between query and food description.
    Uses token-based overlap with case/diacritic insensitive comparison.
    """
    query_normalized = _normalize_query(query)
    desc_normalized = _normalize_query(food_description)

    query_tokens = set(query_normalized.split())
    desc_tokens = set(desc_normalized.split())

    if not query_tokens:
        return 0.0

    # Token overlap score
    overlap = len(query_tokens.intersection(desc_tokens))
    overlap_score = overlap / len(query_tokens)

    # Exact term boost - if query contains specific cooking terms
    cooking_terms = ['cooked', 'raw', 'steamed', 'grilled', 'baked', 'fried', 'boiled']
    for term in cooking_terms:
        if term in query_normalized and term in desc_normalized:
            overlap_score += 0.1  # Small boost for cooking method match

    # Sequence similarity as secondary factor
    sequence_sim = SequenceMatcher(None, query_normalized, desc_normalized).ratio()

    # Combine scores (overlap is primary, sequence is secondary)
    return 0.8 * overlap_score + 0.2 * sequence_sim


def _select_best_match(query: str, foods: List[Dict]) -> Optional[Dict]:
    """
    Select the best matching food from search results.
    Prefers data type (FNDDS > SR Legacy > Branded) and similarity.
    """
    if not foods:
        return None

    best_food = None
    best_score = -1

    for food in foods:
        description = food.get('description', '')
        data_type = food.get('dataType', '')

        # Calculate similarity score
        similarity = _calculate_similarity(query, description)

        # Add data type preference bonus
        type_bonus = DATA_TYPE_SCORES.get(data_type, 0) * 0.1

        final_score = similarity + type_bonus

        if final_score > best_score:
            best_score = final_score
            best_food = food

    return best_food


def search_best_match(query: str) -> Optional[Dict]:
    """
    Search for the best matching food in USDA database.

    Args:
        query: Food name to search for

    Returns:
        Dict with food data or None if no good match found
    """
    if not query or not query.strip():
        return None

    try:
        # Search USDA API
        result = _search_usda_api(query.strip())

        if not result or 'foods' not in result:
            return None

        foods = result['foods']
        if not foods:
            return None

        # Select best match
        best_match = _select_best_match(query, foods)

        if best_match:
            print(f"USDA match for '{query}': {best_match.get('description', 'Unknown')} (FDC: {best_match.get('fdcId', 'N/A')})")

        return best_match

    except Exception as e:
        print(f"Error searching USDA for '{query}': {e}")
        return None


def per100g_macros(food_json: Dict) -> Dict[str, float]:
    """
    Extract macronutrients per 100g from USDA food data.

    Args:
        food_json: USDA food data dictionary

    Returns:
        Dict with kcal, protein_g, carb_g, fat_g per 100g
    """
    macros = {
        "kcal": 0.0,
        "protein_g": 0.0,
        "carb_g": 0.0,
        "fat_g": 0.0
    }

    try:
        nutrients = food_json.get('foodNutrients', [])
        print(f"DEBUG: USDA food has {len(nutrients)} nutrients")

        found_nutrients = []
        for nutrient in nutrients:
            nutrient_id = nutrient.get('nutrientId')
            # USDA API can return either 'amount' or 'value' depending on the endpoint
            amount = nutrient.get('amount') or nutrient.get('value', 0.0)
            nutrient_name = nutrient.get('nutrient', {}).get('name', 'Unknown')

            print(f"DEBUG: Nutrient ID {nutrient_id} ({nutrient_name}): amount={amount}")

            # Map USDA nutrient IDs to our macros
            if nutrient_id == 1008:  # Energy (kcal)
                macros["kcal"] = float(amount)
                found_nutrients.append(f"kcal={amount}")
            elif nutrient_id == 1003:  # Protein
                macros["protein_g"] = float(amount)
                found_nutrients.append(f"protein={amount}g")
            elif nutrient_id == 1005:  # Carbohydrate, by difference
                macros["carb_g"] = float(amount)
                found_nutrients.append(f"carbs={amount}g")
            elif nutrient_id == 1004:  # Total lipid (fat)
                macros["fat_g"] = float(amount)
                found_nutrients.append(f"fat={amount}g")

        print(f"DEBUG: Extracted macros: {', '.join(found_nutrients) if found_nutrients else 'None found'}")
        print(f"DEBUG: Final macros dict: {macros}")

        # If calories are missing but we have macros, calculate using 4/4/9 rule
        if macros["kcal"] == 0.0 and (macros["protein_g"] > 0 or macros["carb_g"] > 0 or macros["fat_g"] > 0):
            calculated_kcal = (4 * macros["protein_g"]) + (4 * macros["carb_g"]) + (9 * macros["fat_g"])
            print(f"DEBUG: Missing calories in USDA data, calculated using 4/4/9 rule: {calculated_kcal:.1f} kcal")
            macros["kcal"] = round(calculated_kcal, 1)

    except Exception as e:
        print(f"ERROR: Failed to extract macros from USDA data: {e}")
        print(f"DEBUG: food_json structure: {list(food_json.keys()) if isinstance(food_json, dict) else type(food_json)}")

    return macros


def get_detailed_food_data(fdc_id: int) -> Optional[Dict]:
    """
    Get detailed food data by FDC ID.

    Args:
        fdc_id: USDA Food Data Central ID

    Returns:
        Detailed food data or None if not found
    """
    if not _api_key:
        print("USDA API key not set. Call set_api_key() first.")
        return None

    url = f"{USDA_BASE_URL}/food/{fdc_id}"
    params = {"api_key": _api_key}

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching detailed data for FDC ID {fdc_id}: {e}")
        return None


# Cache management utilities
def clear_cache() -> None:
    """Clear both in-memory and disk caches."""
    _search_usda_api.cache_clear()

    if os.path.exists(CACHE_DIR):
        for filename in os.listdir(CACHE_DIR):
            if filename.endswith('.pkl'):
                try:
                    os.remove(os.path.join(CACHE_DIR, filename))
                except Exception as e:
                    print(f"Error removing cache file {filename}: {e}")


def cache_info() -> Dict[str, Any]:
    """Get cache statistics."""
    lru_info = _search_usda_api.cache_info()

    disk_files = 0
    if os.path.exists(CACHE_DIR):
        disk_files = len([f for f in os.listdir(CACHE_DIR) if f.endswith('.pkl')])

    return {
        "lru_cache": {
            "hits": lru_info.hits,
            "misses": lru_info.misses,
            "maxsize": lru_info.maxsize,
            "currsize": lru_info.currsize
        },
        "disk_cache_files": disk_files,
        "cache_directory": CACHE_DIR
    }