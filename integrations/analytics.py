"""
Analytics module for dashboard queries.
Provides atomic functions to query nutrition data from the database.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from integrations.db import DB_PATH


def get_today_totals(validated_only: bool = True) -> Dict[str, float]:
    """
    Get total macros for all meals logged today.

    Args:
        validated_only: If True, only include validated sessions (default True)

    Returns:
        Dict with {calories, protein, carbs, fat, meal_count}
        Returns zeros if no meals logged today.
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Query all sessions from today (filter to validated if requested)
    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') = date('now')
        AND final_json IS NOT NULL
        {validated_filter}
    """)

    rows = cur.fetchall()
    con.close()

    if not rows:
        return {
            "calories": 0,
            "protein": 0,
            "carbs": 0,
            "fat": 0,
            "meal_count": 0
        }

    # Aggregate macros from all meals
    total_calories = 0
    total_protein = 0
    total_carbs = 0
    total_fat = 0

    for (final_json_str,) in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])

            for item in breakdown:
                total_calories += item.get("calories", 0)
                total_protein += item.get("protein_grams", 0)
                total_carbs += item.get("carbs_grams", 0)
                total_fat += item.get("fat_grams", 0)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"WARNING: Failed to parse session final_json: {e}")
            continue

    return {
        "calories": total_calories,
        "protein": total_protein,
        "carbs": total_carbs,
        "fat": total_fat,
        "meal_count": len(rows)
    }


def get_meals_by_date(date_str: str, validated_only: bool = True) -> List[Dict]:
    """
    Get all meals logged on a specific date.

    Args:
        date_str: Date in format 'YYYY-MM-DD' (e.g., '2025-01-20')
        validated_only: If True, only include validated sessions (default True)

    Returns:
        List of meal dicts with {id, time, dish, calories, protein, carbs, fat, breakdown}
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT
            id,
            created_at,
            dish,
            final_json
        FROM sessions
        WHERE date(created_at, 'unixepoch') = ?
        AND final_json IS NOT NULL
        {validated_filter}
        ORDER BY created_at ASC
    """, (date_str,))

    rows = cur.fetchall()
    con.close()

    meals = []
    for session_id, created_at, dish, final_json_str in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])

            # Calculate meal totals
            meal_calories = sum(item.get("calories", 0) for item in breakdown)
            meal_protein = sum(item.get("protein_grams", 0) for item in breakdown)
            meal_carbs = sum(item.get("carbs_grams", 0) for item in breakdown)
            meal_fat = sum(item.get("fat_grams", 0) for item in breakdown)

            # Convert unix timestamp to readable time
            time_obj = datetime.fromtimestamp(created_at)
            time_str = time_obj.strftime("%I:%M %p")  # e.g., "09:30 AM"

            meals.append({
                "id": session_id,
                "time": time_str,
                "dish": dish,
                "calories": meal_calories,
                "protein": meal_protein,
                "carbs": meal_carbs,
                "fat": meal_fat,
                "breakdown": breakdown
            })
        except (json.JSONDecodeError, KeyError) as e:
            print(f"WARNING: Failed to parse session {session_id}: {e}")
            continue

    return meals


def get_macro_percentages(totals: Dict[str, float]) -> Dict[str, float]:
    """
    Calculate macro percentages from gram totals.

    Uses 4/4/9 calorie conversion:
    - Protein: 4 cal/g
    - Carbs: 4 cal/g
    - Fat: 9 cal/g

    Args:
        totals: Dict with {protein, carbs, fat} in grams

    Returns:
        Dict with {protein_pct, carbs_pct, fat_pct}
        Returns equal thirds if total calories is 0.
    """
    protein_g = totals.get("protein", 0)
    carbs_g = totals.get("carbs", 0)
    fat_g = totals.get("fat", 0)

    # Calculate calories from macros
    protein_cal = protein_g * 4
    carbs_cal = carbs_g * 4
    fat_cal = fat_g * 9

    total_cal = protein_cal + carbs_cal + fat_cal

    if total_cal == 0:
        # No data - return equal distribution for empty chart
        return {
            "protein_pct": 33.3,
            "carbs_pct": 33.3,
            "fat_pct": 33.4
        }

    return {
        "protein_pct": round((protein_cal / total_cal) * 100, 1),
        "carbs_pct": round((carbs_cal / total_cal) * 100, 1),
        "fat_pct": round((fat_cal / total_cal) * 100, 1)
    }


def get_daily_calorie_series(days: int = 7, validated_only: bool = True) -> List[Tuple[str, float]]:
    """
    Get daily calorie totals for the last N days.

    Args:
        days: Number of days to retrieve (default 7)
        validated_only: If True, only include validated sessions (default True)

    Returns:
        List of (date_str, calories) tuples, e.g., [('2025-01-15', 1850), ...]
        Ordered chronologically (oldest first).
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days - 1)

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT
            date(created_at, 'unixepoch') as date,
            final_json
        FROM sessions
        WHERE created_at >= ?
        AND final_json IS NOT NULL
        {validated_filter}
        ORDER BY created_at ASC
    """, (start_date.timestamp(),))

    rows = cur.fetchall()
    con.close()

    # Group by date and sum calories
    daily_totals = {}
    for date_str, final_json_str in rows:
        try:
            data = json.loads(final_json_str)
            breakdown = data.get("breakdown", [])
            day_calories = sum(item.get("calories", 0) for item in breakdown)

            if date_str in daily_totals:
                daily_totals[date_str] += day_calories
            else:
                daily_totals[date_str] = day_calories
        except (json.JSONDecodeError, KeyError):
            continue

    # Convert to sorted list of tuples
    series = sorted(daily_totals.items())
    return series


def get_days_with_data(validated_only: bool = True) -> int:
    """
    Count how many unique days have logged meals.

    Args:
        validated_only: If True, only count validated sessions (default True)

    Returns:
        Number of unique days with at least one meal logged.
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    validated_filter = "AND validated = 1" if validated_only else ""
    cur.execute(f"""
        SELECT COUNT(DISTINCT date(created_at, 'unixepoch'))
        FROM sessions
        WHERE final_json IS NOT NULL
        {validated_filter}
    """)

    count = cur.fetchone()[0]
    con.close()

    return count


def get_week_comparison(validated_only: bool = True) -> Dict[str, float]:
    """
    Compare this week's average to last week's average.

    Args:
        validated_only: If True, only include validated sessions (default True)

    Returns:
        Dict with {this_week_avg, last_week_avg, delta}
        Returns None values if insufficient data.
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    now = datetime.now()

    # This week (last 7 days)
    this_week_start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0)

    # Last week (days 7-13 ago)
    last_week_start = (now - timedelta(days=13)).replace(hour=0, minute=0, second=0)
    last_week_end = (now - timedelta(days=7)).replace(hour=23, minute=59, second=59)

    validated_filter = "AND validated = 1" if validated_only else ""

    # Query this week (include date to group properly)
    cur.execute(f"""
        SELECT date(created_at, 'unixepoch') as date, final_json
        FROM sessions
        WHERE created_at >= ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (this_week_start.timestamp(),))

    this_week_rows = cur.fetchall()

    # Query last week (include date to group properly)
    cur.execute(f"""
        SELECT date(created_at, 'unixepoch') as date, final_json
        FROM sessions
        WHERE created_at >= ? AND created_at <= ?
        AND final_json IS NOT NULL
        {validated_filter}
    """, (last_week_start.timestamp(), last_week_end.timestamp()))

    last_week_rows = cur.fetchall()
    con.close()

    def calculate_avg(rows):
        if not rows:
            return None

        # Group calories by date
        daily_totals = {}
        for date_str, final_json_str in rows:
            try:
                data = json.loads(final_json_str)
                breakdown = data.get("breakdown", [])
                day_calories = sum(item.get("calories", 0) for item in breakdown)

                # Sum calories for each unique date
                if date_str in daily_totals:
                    daily_totals[date_str] += day_calories
                else:
                    daily_totals[date_str] = day_calories
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        if not daily_totals:
            return None

        # Calculate average across actual days with data
        total_calories = sum(daily_totals.values())
        num_days = len(daily_totals)
        return total_calories / num_days

    this_week_avg = calculate_avg(this_week_rows)
    last_week_avg = calculate_avg(last_week_rows)

    delta = None
    if this_week_avg is not None and last_week_avg is not None:
        delta = this_week_avg - last_week_avg

    return {
        "this_week_avg": this_week_avg,
        "last_week_avg": last_week_avg,
        "delta": delta
    }
