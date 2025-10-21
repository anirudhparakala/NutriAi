import requests
import json
import os
import pickle
import hashlib
from functools import lru_cache
from typing import Dict, List, Optional, Any, Set
from difflib import SequenceMatcher
import time
import re
import math
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.privacy import sanitize_metrics

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

# Pattern for tokenization
WORD_RX = re.compile(r"[a-z0-9]+")

# Critical modifiers that change food nutritional properties
CRITICAL_RX = re.compile(
    r'\b(diet|zero|sugar[- ]?free|unsweetened|no\s*sugar|nonfat|fat[- ]?free|skim|whole|1%|2%|\d{2}%\s*lean|lean\s*\d{2}%)\b',
    re.I
)


def set_api_key(key: str) -> None:
    """Set the USDA API key for all requests."""
    global _api_key
    _api_key = key


def _ensure_cache_dir():
    """Ensure cache directory exists."""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)


def _tokens(s: str) -> List[str]:
    """Extract alphanumeric tokens from a string."""
    return WORD_RX.findall(s.lower())


def _normalize_query(query: str) -> str:
    """Normalize query for consistent caching and comparison."""
    return " ".join(_tokens(query))


def _head_token(q: str) -> Optional[str]:
    """
    Extract the head (first) token before any parenthesis.
    Example: "cola (regular)" -> "cola"
    """
    base = q.split('(', 1)[0]
    toks = _tokens(base)
    return toks[0] if toks else None


def _extract_critical_tokens(q: str) -> Set[str]:
    """
    Extract critical modifier tokens that affect nutritional properties.
    Examples: diet, zero, 2%, 90% lean, skim, etc.
    """
    toks = set(_tokens(q))
    crit = set()

    # Check each token against critical patterns
    for t in toks:
        if CRITICAL_RX.search(t):
            crit.add(t)

    # Also keep raw percentage tokens ("2%", "90%")
    perc = set(re.findall(r'\b\d{1,2}%\b', q.lower()))
    crit |= set(_tokens(' '.join(perc)))

    return crit


def _idf_map(candidates: List[Dict]) -> Dict[str, float]:
    """
    Calculate IDF (inverse document frequency) for tokens in candidate list.
    This helps downweight common/generic terms dynamically without stopword lists.
    """
    N = max(1, len(candidates))
    df: Dict[str, int] = {}

    for c in candidates:
        dtoks = set(_tokens(c.get("description", "")))
        for t in dtoks:
            df[t] = df.get(t, 0) + 1

    # Calculate IDF: log((N + 1) / (df + 1)) + 1.0
    return {t: math.log((N + 1) / (df[t] + 1)) + 1.0 for t in df}


def _bm25_like(query_tokens: List[str], desc_tokens: List[str], idf: Dict[str, float]) -> float:
    """
    Simple BM25-like scoring: sum IDF for matched tokens, normalized by query length.
    Higher scores = better match with downweighting of common terms.
    """
    if not query_tokens:
        return 0.0

    dset = set(desc_tokens)
    score = sum(idf.get(t, 1.0) for t in query_tokens if t in dset)
    return score / len(query_tokens)


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
    Uses BM25-like scoring with sequence matching.
    Note: This is kept for backwards compatibility but _select_best_match now does its own scoring.
    """
    query_normalized = _normalize_query(query)
    desc_normalized = _normalize_query(food_description)

    q_tokens = _tokens(query)
    d_tokens = _tokens(food_description)

    if not q_tokens:
        return 0.0

    # Simple token overlap
    overlap = len(set(q_tokens).intersection(set(d_tokens)))
    overlap_score = overlap / len(q_tokens)

    # Sequence similarity as secondary factor
    sequence_sim = SequenceMatcher(None, query_normalized, desc_normalized).ratio()

    # Combine scores
    final_score = 0.7 * overlap_score + 0.3 * sequence_sim
    return max(0.0, final_score)


def _is_likely_non_food(food: Dict) -> bool:
    """
    Detect if a USDA result is likely a spice mix, seasoning, or sauce rather than actual food.
    Uses nutrition profile heuristics (cuisine-agnostic).

    Indicators of non-food items (spice mixes, seasonings, sauces):
    - Very high sodium (>5000mg/100g suggests seasoning blend)
    - Very high carbs with zero protein (>40g carbs, 0g protein suggests spice/starch mix)
    - Description length (spice mixes often have verbose descriptions)
    """
    try:
        nutrients = food.get('foodNutrients', [])

        # Extract key nutrients
        sodium_mg = 0.0
        protein_g = 0.0
        carb_g = 0.0

        for nutrient in nutrients:
            nutrient_id = nutrient.get('nutrientId')
            amount = nutrient.get('amount') or nutrient.get('value', 0.0)

            if nutrient_id == 1093:  # Sodium
                sodium_mg = float(amount)
            elif nutrient_id == 1003:  # Protein
                protein_g = float(amount)
            elif nutrient_id == 1005:  # Carbs
                carb_g = float(amount)

        # Heuristic checks
        # 1. Extremely high sodium (seasoning blends)
        if sodium_mg > 5000:
            print(f"DEBUG: Rejecting '{food.get('description')}' - extremely high sodium ({sodium_mg}mg)")
            return True

        # 2. High carbs with zero protein (spice mixes, pure starches)
        if carb_g > 40 and protein_g == 0:
            print(f"DEBUG: Rejecting '{food.get('description')}' - likely spice mix (0g protein, {carb_g}g carbs)")
            return True

        return False

    except Exception as e:
        print(f"DEBUG: Error checking food profile: {e}")
        return False  # Don't reject on error


def _llm_tiebreaker(query: str, candidates: List[Dict]) -> Optional[Dict]:
    """
    Use LLM to pick the best match when multiple candidates have similar scores.

    Args:
        query: Original search query
        candidates: List of candidate foods with similar scores (sorted by score descending)

    Returns:
        Best matching food or first candidate if tiebreaker fails
    """
    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    # Import here to avoid circular dependency
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.tool_runner import llm_tiebreak

    # Call centralized tiebreaker (safe box with frozen config)
    pick_index = llm_tiebreak(query, candidates[:3])  # Limit to top 3
    return candidates[pick_index] if 0 <= pick_index < len(candidates) else candidates[0]


def _select_best_match(query: str, foods: List[Dict], must_tokens: Optional[Set[str]] = None) -> Optional[Dict]:
    """
    Select the best matching food from search results using structure-aware scoring.

    Features:
    - Head-anchoring: requires the first noun of the query to appear in candidates
    - Critical modifiers: enforces diet/zero/skim/2%/90% lean etc. if present in query
    - BM25-like scoring: dynamically downweights generic terms without stopword lists
    - Data type preference: FNDDS > SR Legacy > Branded
    - LLM tiebreaker: when multiple candidates have close scores (<10% difference)

    Args:
        query: Search query
        foods: List of candidate foods from USDA
        must_tokens: Optional set of critical modifier tokens that must appear

    Returns:
        Best matching food or None
    """
    if not foods:
        return None

    head = _head_token(query)
    q_tokens = _tokens(query)
    idf = _idf_map(foods)

    # Pattern to detect non-food items in descriptions
    NONFOOD_PAT = re.compile(
        r'\b(seasoning|bouillon|broth powder|gravy mix|spice mix|rub|coating|breading|powder)\b',
        re.I
    )

    scored_foods = []  # Track all scored foods for tiebreaking

    for food in foods:
        desc = food.get('description', '') or ''
        data_type = food.get('dataType', '')
        d_tokens = _tokens(desc)

        # Skip obvious non-foods unless explicitly asked
        if NONFOOD_PAT.search(desc) and not NONFOOD_PAT.search(query):
            print(f"DEBUG: Skipping non-food item: {desc}")
            continue

        # Skip if likely a spice mix/seasoning based on nutrition
        if _is_likely_non_food(food):
            continue

        # 1) HEAD ANCHOR: candidate must contain the head noun (prevents "cola" -> "tofu")
        if head and head not in d_tokens:
            continue

        # 2) CRITICAL MODIFIERS: all must appear (handles diet/zero, 1%/2%, 90% lean, etc.)
        if must_tokens:
            # Check if all critical tokens are in description tokens
            # Special handling for percentages which might be formatted differently
            has_all_critical = True
            for mt in must_tokens:
                if mt not in d_tokens:
                    # For percentage tokens, also check if they appear in original description
                    if '%' in mt and mt not in desc.lower():
                        has_all_critical = False
                        break
                    elif '%' not in mt:
                        has_all_critical = False
                        break

            if not has_all_critical:
                continue

        # 3) SCORE: BM25-like over tokens + sequence similarity + dataType preference + penalties
        bm25 = _bm25_like(q_tokens, d_tokens, idf)
        seq = SequenceMatcher(None, _normalize_query(query), _normalize_query(desc)).ratio()
        dtype_bonus = DATA_TYPE_SCORES.get(data_type, 0) * 0.1

        # Penalty for extra tokens in description (prevents "fries" -> "sweet potato fries")
        # and missing tokens in description (ensures query terms are matched)
        q_set = set(q_tokens)
        d_set = set(d_tokens)
        extra = d_set - q_set  # tokens in description but not in query
        missing = q_set - d_set  # tokens in query but not in description

        # IDF-weighted penalties (generic - no stopword lists needed)
        extra_penalty = 0.3 * sum(idf.get(t, 1.0) for t in extra)
        missing_penalty = 0.2 * sum(idf.get(t, 1.0) for t in missing)

        score = 0.75 * bm25 + 0.25 * seq + dtype_bonus - extra_penalty - missing_penalty

        # Store scored food
        scored_foods.append((score, food))

    # Sort by score descending
    scored_foods.sort(key=lambda x: x[0], reverse=True)

    if not scored_foods:
        return None

    # Get best score
    best_score = scored_foods[0][0]

    # Store top-3 candidates for explainability (P2-E2)
    top3_candidates = [
        {
            "description": food.get('description'),
            "fdcId": food.get('fdcId'),
            "score": score,
            "dataType": food.get('dataType', 'Unknown')
        }
        for score, food in scored_foods[:3]
    ]

    # Check for close matches (within 10% of best score)
    close_threshold = best_score * 0.9
    close_matches = [food for score, food in scored_foods if score >= close_threshold]

    # If multiple close matches AND they're ambiguous, re   turn clarification metadata
    # Caller can decide to ask user or use tiebreaker
    if len(close_matches) > 1:
        # Check if matches are semantically different (e.g., "sweet potato fries" vs "fries")
        descriptions = [food.get('description', '').lower() for food in close_matches[:3]]

        # If descriptions differ by key modifiers, this is ambiguous
        key_modifiers = ["sweet", "veggie", "turkey", "chicken", "beef", "pork"]
        has_conflicting_modifiers = False
        for mod in key_modifiers:
            appears_in = [mod in desc for desc in descriptions]
            if any(appears_in) and not all(appears_in):
                has_conflicting_modifiers = True
                break

        if has_conflicting_modifiers:
            print(f"DEBUG: Ambiguous matches detected - conflicting modifiers")
            metric = {'event': 'usda_ambiguous', 'query': query, 'candidates': len(close_matches)}
            print(f"METRICS: {json.dumps(sanitize_metrics(metric))}")
            # Return special marker for caller to handle
            return {
                "_ambiguous": True,
                "_query": query,
                "_candidates": top3_candidates,
                "_top3": top3_candidates  # P2-E2 explainability
            }

        # Check if top-2 candidates have sanity gate conflicts
        # If one would pass and one would fail, abstain and return ambiguous for user clarification
        if len(close_matches) >= 2:
            top2 = close_matches[:2]
            sanity_results = []

            for candidate in top2:
                macros = per100g_macros(candidate)
                # Quick sanity check (simplified version of nutrition_lookup sanity gate)
                passes_sanity = True

                desc_lower = candidate.get('description', '').lower()

                # Check diet/zero keywords with high calories
                if any(kw in desc_lower for kw in ['diet', 'zero', 'sugar-free', 'unsweetened']):
                    if macros['kcal'] > 20:  # Diet should be <10 kcal per 100g
                        passes_sanity = False

                # Check "lean" with high fat
                if 'lean' in desc_lower:
                    if macros['fat_g'] > 15:  # Lean should be <15% fat
                        passes_sanity = False

                # Check protein powder with low protein
                if any(kw in desc_lower for kw in ['protein powder', 'whey', 'casein', 'protein supplement']):
                    if macros['protein_g'] < 50:  # Protein powder should be ≥50g protein per 100g
                        passes_sanity = False
                        print(f"DEBUG: Sanity gate reject - '{desc_lower}' has only {macros['protein_g']}g protein/100g (expected ≥50g)")

                sanity_results.append(passes_sanity)

            # If exactly one passes sanity (conflict), abstain and ask user
            if sum(sanity_results) == 1:
                print(f"DEBUG: Tiebreaker abstain - sanity gate conflict between top-2 candidates")
                metric = {'event': 'usda_tiebreak_abstain', 'reason': 'sanity_conflict', 'query': query}
                print(f"METRICS: {json.dumps(sanitize_metrics(metric))}")
                return {
                    "_ambiguous": True,
                    "_query": query,
                    "_candidates": top3_candidates,
                    "_top3": top3_candidates,
                    "_reason": "sanity_gate_conflict"
                }

        # No conflicting modifiers or sanity issues - safe to use tiebreaker
        print(f"DEBUG: Found {len(close_matches)} close matches (no conflicts), using LLM tiebreaker")
        metric = {'event': 'usda_tiebreak', 'invoked': True, 'query': query, 'candidates': len(close_matches)}
        print(f"METRICS: {json.dumps(sanitize_metrics(metric))}")
        best_match = _llm_tiebreaker(query, close_matches)
        # Attach explainability metadata
        best_match["_top3"] = top3_candidates
        return best_match

    # Return best match with explainability metadata
    best_match = scored_foods[0][1]
    best_match["_top3"] = top3_candidates
    return best_match


def search_best_match(query: str) -> Optional[Dict]:
    """
    Search for the best matching food in USDA database.
    Uses multi-strategy search with critical modifier extraction and LLM tiebreaking.

    Args:
        query: Food name to search for

    Returns:
        Dict with food data or None if no good match found
    """
    if not query or not query.strip():
        return None

    try:
        query_clean = query.strip()
        critical_tokens = _extract_critical_tokens(query_clean)

        # Strategy 1: Try exact query as provided (preserves all qualifiers)
        print(f"DEBUG: USDA search strategy 1 - trying '{query_clean}'")
        result = _search_usda_api(query_clean)

        if result and 'foods' in result and result['foods']:
            best_match = _select_best_match(query_clean, result['foods'], must_tokens=critical_tokens)
            if best_match and _calculate_similarity(query_clean, best_match.get('description', '')) > 0.5:
                print(f"METRICS: {json.dumps({'event': 'usda_match', 'strategy': '1_exact_query', 'query': query_clean, 'fdc_id': best_match.get('fdcId')})}")
                print(f"USDA match for '{query_clean}': {best_match.get('description', 'Unknown')} (FDC: {best_match.get('fdcId', 'N/A')})")
                return best_match

        # Strategy 2: If query has parentheses, try base-before-parens first, then no-parens
        if '(' in query_clean:
            # 2a: Try just the base before parentheses (e.g., "cola (diet)" -> "cola")
            base_before = query_clean.split('(', 1)[0].strip()
            if base_before:
                print(f"DEBUG: USDA search strategy 2a - trying base before parens '{base_before}'")
                result = _search_usda_api(base_before)
                if result and result.get('foods'):
                    best_match = _select_best_match(base_before, result['foods'], must_tokens=critical_tokens)
                    if best_match and _calculate_similarity(base_before, best_match.get('description', '')) > 0.5:
                        print(f"METRICS: {json.dumps({'event': 'usda_match', 'strategy': '2a_base_before_parens', 'query': query_clean, 'fdc_id': best_match.get('fdcId')})}")
                        print(f"USDA match for '{base_before}': {best_match.get('description', 'Unknown')} (FDC: {best_match.get('fdcId', 'N/A')})")
                        return best_match

            # 2b: Try removing parentheses (e.g., "cola (diet)" -> "cola diet")
            query_no_parens = re.sub(r'[()]', ' ', query_clean)
            query_no_parens = re.sub(r'\s+', ' ', query_no_parens).strip()
            print(f"DEBUG: USDA search strategy 2b - trying without parentheses '{query_no_parens}'")

            result = _search_usda_api(query_no_parens)
            if result and 'foods' in result and result['foods']:
                best_match = _select_best_match(query_no_parens, result['foods'], must_tokens=critical_tokens)
                if best_match and _calculate_similarity(query_no_parens, best_match.get('description', '')) > 0.5:
                    print(f"METRICS: {json.dumps({'event': 'usda_match', 'strategy': '2b_no_parens', 'query': query_clean, 'fdc_id': best_match.get('fdcId')})}")
                    print(f"USDA match for '{query_no_parens}': {best_match.get('description', 'Unknown')} (FDC: {best_match.get('fdcId', 'N/A')})")
                    return best_match

        # Strategy 3: Try just the base ingredient (first 1-2 words before any qualifiers)
        # Head-anchoring in _select_best_match prevents bad matches like "cola" -> "tofu"
        base_words = query_clean.split()[:2]
        if len(base_words) > 0:
            query_base = ' '.join(base_words)
            print(f"DEBUG: USDA search strategy 3 - trying base form '{query_base}'")

            result = _search_usda_api(query_base)
            if result and 'foods' in result and result['foods']:
                best_match = _select_best_match(query_base, result['foods'], must_tokens=critical_tokens)
                # Require similarity > 0.45 to avoid bad tail matches
                if best_match and _calculate_similarity(query_base, best_match.get('description', '')) > 0.45:
                    print(f"METRICS: {json.dumps({'event': 'usda_match', 'strategy': '3_base_words', 'query': query_clean, 'fdc_id': best_match.get('fdcId')})}")
                    print(f"USDA match for '{query_base}': {best_match.get('description', 'Unknown')} (FDC: {best_match.get('fdcId', 'N/A')})")
                    return best_match

        print(f"WARNING: No USDA match found for '{query_clean}' after trying all strategies")
        return None

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