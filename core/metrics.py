"""
Metrics module for chatbot queries.
Provides 15 atomic functions to answer nutrition questions about historical data.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from integrations.db import DB_PATH


def get_calories_for_date(date: str, validated_only: bool = True) -> float:
    """
    Get total calories for a specific date.

    Args:
        date: Date string in 'YYYY-MM-DD' format
        validated_only: If True, only include validated sessions

    Returns:
        Total calories for that date (0 if no data)
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') = ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (date,))

    rows = cur.fetchall()
    con.close()

    total_calories = 0.0
    for (final_json_str,) in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])
            total_calories += sum(item.get("calories", 0) for item in breakdown)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    return total_calories


def get_macros_for_date(date: str, validated_only: bool = True) -> Optional[Dict[str, float]]:
    """
    Get complete macro breakdown for a specific date.

    Args:
        date: Date string in 'YYYY-MM-DD' format
        validated_only: If True, only include validated sessions

    Returns:
        Dict with {calories, protein, carbs, fat, fiber} for that date (None if no data)
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Use direct column sums instead of parsing JSON for better reliability
    cur.execute(f"""
        SELECT
            SUM(kcal) as total_kcal,
            SUM(protein_g) as total_protein,
            SUM(carbs_g) as total_carbs,
            SUM(fat_g) as total_fat,
            SUM(fiber_g) as total_fiber
        FROM sessions
        WHERE DATE(created_at, 'unixepoch', 'localtime') = ?
        AND kcal IS NOT NULL
    """, (date,))

    row = cur.fetchone()
    con.close()

    if not row or row[0] is None:
        return None

    totals = {
        "calories": float(row[0]) if row[0] else 0.0,
        "protein": float(row[1]) if row[1] else 0.0,
        "carbs": float(row[2]) if row[2] else 0.0,
        "fat": float(row[3]) if row[3] else 0.0,
        "fiber": float(row[4]) if row[4] else 0.0
    }

    return totals


def get_average_daily_calories(start_date: str, end_date: str, validated_only: bool = True) -> Optional[float]:
    """
    Get average daily calories over a date range.

    Args:
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        validated_only: If True, only include validated sessions

    Returns:
        Average calories per day (None if no data)
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT date(created_at, 'unixepoch') as date, final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    rows = cur.fetchall()
    con.close()

    if not rows:
        return None

    # Group by date
    daily_totals = {}
    for date_str, final_json_str in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])
            day_calories = sum(item.get("calories", 0) for item in breakdown)
            daily_totals[date_str] = daily_totals.get(date_str, 0) + day_calories
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    if not daily_totals:
        return None

    return sum(daily_totals.values()) / len(daily_totals)


def get_average_daily_macros(start_date: str, end_date: str, validated_only: bool = True) -> Optional[Dict[str, float]]:
    """
    Get average daily macros over a date range.

    Args:
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        validated_only: If True, only include validated sessions

    Returns:
        Dict with {protein, carbs, fat} averages per day (None if no data)
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT date(created_at, 'unixepoch') as date, final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    rows = cur.fetchall()
    con.close()

    if not rows:
        return None

    # Group by date
    daily_macros = {}
    for date_str, final_json_str in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])

            if date_str not in daily_macros:
                daily_macros[date_str] = {"protein": 0, "carbs": 0, "fat": 0}

            for item in breakdown:
                daily_macros[date_str]["protein"] += item.get("protein_grams", 0)
                daily_macros[date_str]["carbs"] += item.get("carbs_grams", 0)
                daily_macros[date_str]["fat"] += item.get("fat_grams", 0)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    if not daily_macros:
        return None

    num_days = len(daily_macros)
    total_protein = sum(day["protein"] for day in daily_macros.values())
    total_carbs = sum(day["carbs"] for day in daily_macros.values())
    total_fat = sum(day["fat"] for day in daily_macros.values())

    return {
        "protein": total_protein / num_days,
        "carbs": total_carbs / num_days,
        "fat": total_fat / num_days
    }


def get_macro_distribution(start_date: str, end_date: str, validated_only: bool = True) -> Optional[Dict[str, float]]:
    """
    Get macro distribution as percentages over a date range.

    Args:
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        validated_only: If True, only include validated sessions

    Returns:
        Dict with {protein_pct, carbs_pct, fat_pct} (None if no data)
    """
    macros = get_average_daily_macros(start_date, end_date, validated_only)

    if not macros:
        return None

    # Calculate calories from macros (4/4/9)
    protein_cal = macros["protein"] * 4
    carbs_cal = macros["carbs"] * 4
    fat_cal = macros["fat"] * 9

    total_cal = protein_cal + carbs_cal + fat_cal

    if total_cal == 0:
        return None

    return {
        "protein_pct": round((protein_cal / total_cal) * 100, 1),
        "carbs_pct": round((carbs_cal / total_cal) * 100, 1),
        "fat_pct": round((fat_cal / total_cal) * 100, 1)
    }


def get_most_recent_logged_date(validated_only: bool = True) -> Optional[str]:
    """
    Get the most recent date with logged meals.

    Args:
        validated_only: If True, only consider validated sessions

    Returns:
        Most recent date string in 'YYYY-MM-DD' format (None if no data)
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT date(created_at, 'unixepoch') as date
        FROM sessions
        WHERE final_json IS NOT NULL
        {validated_filter}
        ORDER BY created_at DESC
        LIMIT 1
    """)

    result = cur.fetchone()
    con.close()

    return result[0] if result else None


def get_days_logged(start_date: str, end_date: str, validated_only: bool = True) -> int:
    """
    Count unique days with logged meals in date range.

    Args:
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        validated_only: If True, only count validated sessions

    Returns:
        Number of unique days with data
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT COUNT(DISTINCT date(created_at, 'unixepoch'))
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    count = cur.fetchone()[0]
    con.close()

    return count


def get_meal_count(start_date: str, end_date: str, validated_only: bool = True) -> int:
    """
    Count total meals logged in date range.

    Args:
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        validated_only: If True, only count validated sessions

    Returns:
        Total number of meals
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT COUNT(*)
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    count = cur.fetchone()[0]
    con.close()

    return count


def get_average_calories_per_meal(start_date: str, end_date: str, validated_only: bool = True) -> Optional[float]:
    """
    Get average calories per meal over date range.

    Args:
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        validated_only: If True, only include validated sessions

    Returns:
        Average calories per meal (None if no data)
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    rows = cur.fetchall()
    con.close()

    if not rows:
        return None

    meal_calories = []
    for (final_json_str,) in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])
            total = sum(item.get("calories", 0) for item in breakdown)
            meal_calories.append(total)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    if not meal_calories:
        return None

    return sum(meal_calories) / len(meal_calories)


def get_average_macros_per_meal(start_date: str, end_date: str, validated_only: bool = True) -> Optional[Dict[str, float]]:
    """
    Get average macros per meal over date range.

    Args:
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        validated_only: If True, only include validated sessions

    Returns:
        Dict with {protein, carbs, fat} averages per meal (None if no data)
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    rows = cur.fetchall()
    con.close()

    if not rows:
        return None

    meal_macros = []
    for (final_json_str,) in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])

            meal_total = {
                "protein": sum(item.get("protein_grams", 0) for item in breakdown),
                "carbs": sum(item.get("carbs_grams", 0) for item in breakdown),
                "fat": sum(item.get("fat_grams", 0) for item in breakdown)
            }
            meal_macros.append(meal_total)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    if not meal_macros:
        return None

    num_meals = len(meal_macros)
    return {
        "protein": sum(m["protein"] for m in meal_macros) / num_meals,
        "carbs": sum(m["carbs"] for m in meal_macros) / num_meals,
        "fat": sum(m["fat"] for m in meal_macros) / num_meals
    }


def get_highest_calorie_days(start_date: str, end_date: str, limit: int = 5, validated_only: bool = True) -> List[Dict]:
    """
    Get top N highest calorie days in date range.

    Args:
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        limit: Number of days to return (default 5)
        validated_only: If True, only include validated sessions

    Returns:
        List of {date, calories} dicts, sorted highest first
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT date(created_at, 'unixepoch') as date, final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    rows = cur.fetchall()
    con.close()

    # Group by date
    daily_totals = {}
    for date_str, final_json_str in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])
            day_calories = sum(item.get("calories", 0) for item in breakdown)
            daily_totals[date_str] = daily_totals.get(date_str, 0) + day_calories
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    # Sort and limit
    sorted_days = sorted(daily_totals.items(), key=lambda x: x[1], reverse=True)
    return [{"date": date, "calories": cal} for date, cal in sorted_days[:limit]]


def get_lowest_calorie_days(start_date: str, end_date: str, limit: int = 5, validated_only: bool = True) -> List[Dict]:
    """
    Get top N lowest calorie days in date range.

    Args:
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        limit: Number of days to return (default 5)
        validated_only: If True, only include validated sessions

    Returns:
        List of {date, calories} dicts, sorted lowest first
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT date(created_at, 'unixepoch') as date, final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    rows = cur.fetchall()
    con.close()

    # Group by date
    daily_totals = {}
    for date_str, final_json_str in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])
            day_calories = sum(item.get("calories", 0) for item in breakdown)
            daily_totals[date_str] = daily_totals.get(date_str, 0) + day_calories
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    # Sort and limit
    sorted_days = sorted(daily_totals.items(), key=lambda x: x[1])
    return [{"date": date, "calories": cal} for date, cal in sorted_days[:limit]]


def get_highest_macro_days(macro_type: str, start_date: str, end_date: str, limit: int = 5, validated_only: bool = True) -> List[Dict]:
    """
    Get top N days with highest amount of a specific macro.

    Args:
        macro_type: One of 'protein', 'carbs', 'fat'
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        limit: Number of days to return (default 5)
        validated_only: If True, only include validated sessions

    Returns:
        List of {date, [macro_type]} dicts, sorted highest first
    """
    macro_field_map = {
        "protein": "protein_grams",
        "carbs": "carbs_grams",
        "fat": "fat_grams"
    }

    if macro_type not in macro_field_map:
        return []

    field = macro_field_map[macro_type]

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT date(created_at, 'unixepoch') as date, final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    rows = cur.fetchall()
    con.close()

    # Group by date
    daily_totals = {}
    for date_str, final_json_str in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])
            day_macro = sum(item.get(field, 0) for item in breakdown)
            daily_totals[date_str] = daily_totals.get(date_str, 0) + day_macro
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    # Sort and limit
    sorted_days = sorted(daily_totals.items(), key=lambda x: x[1], reverse=True)
    return [{"date": date, macro_type: value} for date, value in sorted_days[:limit]]


def get_lowest_macro_days(macro_type: str, start_date: str, end_date: str, limit: int = 5, validated_only: bool = True) -> List[Dict]:
    """
    Get top N days with lowest amount of a specific macro.

    Args:
        macro_type: One of 'protein', 'carbs', 'fat'
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        limit: Number of days to return (default 5)
        validated_only: If True, only include validated sessions

    Returns:
        List of {date, [macro_type]} dicts, sorted lowest first
    """
    macro_field_map = {
        "protein": "protein_grams",
        "carbs": "carbs_grams",
        "fat": "fat_grams"
    }

    if macro_type not in macro_field_map:
        return []

    field = macro_field_map[macro_type]

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT date(created_at, 'unixepoch') as date, final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    rows = cur.fetchall()
    con.close()

    # Group by date
    daily_totals = {}
    for date_str, final_json_str in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])
            day_macro = sum(item.get(field, 0) for item in breakdown)
            daily_totals[date_str] = daily_totals.get(date_str, 0) + day_macro
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    # Sort and limit
    sorted_days = sorted(daily_totals.items(), key=lambda x: x[1])
    return [{"date": date, macro_type: value} for date, value in sorted_days[:limit]]


def get_most_frequent_foods(start_date: str, end_date: str, limit: int = 10, validated_only: bool = True) -> List[Dict]:
    """
    Get most frequently logged food items.

    Args:
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        limit: Number of foods to return (default 10)
        validated_only: If True, only include validated sessions

    Returns:
        List of {food, count} dicts, sorted by frequency
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    rows = cur.fetchall()
    con.close()

    # Count food items
    food_counts = {}
    for (final_json_str,) in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])
            for item in breakdown:
                food_name = item.get("item", "unknown").lower()
                food_counts[food_name] = food_counts.get(food_name, 0) + 1
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    # Sort and limit
    sorted_foods = sorted(food_counts.items(), key=lambda x: x[1], reverse=True)
    return [{"food": food, "count": count} for food, count in sorted_foods[:limit]]


def get_food_calorie_contribution(food_name: str, start_date: str, end_date: str, validated_only: bool = True) -> Dict[str, float]:
    """
    Get total calories and macros from a specific food.

    Args:
        food_name: Name of food to search for (case-insensitive partial match)
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        validated_only: If True, only include validated sessions

    Returns:
        Dict with {calories, protein, carbs, fat, occurrences}
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') BETWEEN ? AND ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (start_date, end_date))

    rows = cur.fetchall()
    con.close()

    total_calories = 0
    total_protein = 0
    total_carbs = 0
    total_fat = 0
    occurrences = 0

    food_name_lower = food_name.lower()

    for (final_json_str,) in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])
            for item in breakdown:
                item_name = item.get("item", "").lower()
                if food_name_lower in item_name:
                    total_calories += item.get("calories", 0)
                    total_protein += item.get("protein_grams", 0)
                    total_carbs += item.get("carbs_grams", 0)
                    total_fat += item.get("fat_grams", 0)
                    occurrences += 1
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    return {
        "calories": total_calories,
        "protein": total_protein,
        "carbs": total_carbs,
        "fat": total_fat,
        "occurrences": occurrences
    }


def compare_time_periods(period1_start: str, period1_end: str, period2_start: str, period2_end: str, validated_only: bool = True) -> Dict:
    """
    Compare two time periods across multiple metrics.

    Args:
        period1_start: Period 1 start date 'YYYY-MM-DD'
        period1_end: Period 1 end date 'YYYY-MM-DD'
        period2_start: Period 2 start date 'YYYY-MM-DD'
        period2_end: Period 2 end date 'YYYY-MM-DD'
        validated_only: If True, only include validated sessions

    Returns:
        Dict with comparison data for both periods
    """
    period1_data = {
        "avg_calories": get_average_daily_calories(period1_start, period1_end, validated_only),
        "avg_macros": get_average_daily_macros(period1_start, period1_end, validated_only),
        "macro_distribution": get_macro_distribution(period1_start, period1_end, validated_only),
        "days_logged": get_days_logged(period1_start, period1_end, validated_only),
        "meal_count": get_meal_count(period1_start, period1_end, validated_only)
    }

    period2_data = {
        "avg_calories": get_average_daily_calories(period2_start, period2_end, validated_only),
        "avg_macros": get_average_daily_macros(period2_start, period2_end, validated_only),
        "macro_distribution": get_macro_distribution(period2_start, period2_end, validated_only),
        "days_logged": get_days_logged(period2_start, period2_end, validated_only),
        "meal_count": get_meal_count(period2_start, period2_end, validated_only)
    }

    # Calculate deltas
    deltas = {}
    if period1_data["avg_calories"] and period2_data["avg_calories"]:
        deltas["calories_delta"] = period2_data["avg_calories"] - period1_data["avg_calories"]

    if period1_data["avg_macros"] and period2_data["avg_macros"]:
        deltas["protein_delta"] = period2_data["avg_macros"]["protein"] - period1_data["avg_macros"]["protein"]
        deltas["carbs_delta"] = period2_data["avg_macros"]["carbs"] - period1_data["avg_macros"]["carbs"]
        deltas["fat_delta"] = period2_data["avg_macros"]["fat"] - period1_data["avg_macros"]["fat"]

    return {
        "period1": period1_data,
        "period2": period2_data,
        "deltas": deltas
    }
