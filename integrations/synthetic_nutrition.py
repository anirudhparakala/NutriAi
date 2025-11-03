"""
Synthetic Nutrition Data Generator

Generates realistic synthetic nutrition data that correlates with WHOOP metrics
for academic demonstration purposes. Creates meals with varying macro profiles
that show meaningful correlations with recovery, sleep, and strain.
"""

import random
import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sqlite3

from integrations.db import DB_PATH
from integrations.whoop_sync import WhoopSyncManager


class SyntheticNutritionGenerator:
    """Generates synthetic nutrition data correlated with WHOOP metrics."""

    def __init__(self, db_path: str = DB_PATH):
        """Initialize generator with database path."""
        self.db_path = db_path
        self.whoop_sync = WhoopSyncManager()

        # Meal templates with macro profiles
        self.meal_templates = {
            # High protein meals (good for recovery)
            "high_protein": [
                {"dish": "Grilled Chicken Breast with Quinoa", "kcal": 520, "protein": 55, "carbs": 45, "fat": 12, "fiber": 6},
                {"dish": "Greek Yogurt Bowl with Berries and Nuts", "kcal": 380, "protein": 28, "carbs": 35, "fat": 14, "fiber": 5},
                {"dish": "Salmon with Sweet Potato and Broccoli", "kcal": 580, "protein": 48, "carbs": 42, "fat": 22, "fiber": 8},
                {"dish": "Turkey and Egg White Scramble", "kcal": 320, "protein": 42, "carbs": 12, "fat": 11, "fiber": 2},
                {"dish": "Protein Smoothie with Banana and Peanut Butter", "kcal": 450, "protein": 35, "carbs": 48, "fat": 14, "fiber": 6},
            ],
            # Balanced meals
            "balanced": [
                {"dish": "Chicken Stir-Fry with Brown Rice", "kcal": 480, "protein": 32, "carbs": 52, "fat": 14, "fiber": 5},
                {"dish": "Pasta with Marinara and Lean Ground Turkey", "kcal": 520, "protein": 28, "carbs": 68, "fat": 12, "fiber": 6},
                {"dish": "Burrito Bowl with Chicken and Black Beans", "kcal": 550, "protein": 35, "carbs": 58, "fat": 18, "fiber": 10},
                {"dish": "Grilled Fish Tacos with Avocado", "kcal": 420, "protein": 30, "carbs": 38, "fat": 16, "fiber": 8},
                {"dish": "Oatmeal with Eggs and Fruit", "kcal": 380, "protein": 22, "carbs": 48, "fat": 10, "fiber": 7},
            ],
            # High carb meals (good for sleep and recovery after high strain)
            "high_carb": [
                {"dish": "Whole Wheat Pasta with Vegetables", "kcal": 480, "protein": 18, "carbs": 82, "fat": 8, "fiber": 10},
                {"dish": "Rice Bowl with Tofu and Vegetables", "kcal": 450, "protein": 20, "carbs": 72, "fat": 10, "fiber": 8},
                {"dish": "Pancakes with Fresh Berries and Honey", "kcal": 520, "protein": 16, "carbs": 88, "fat": 12, "fiber": 6},
                {"dish": "Banana Bread with Almond Butter", "kcal": 380, "protein": 12, "carbs": 62, "fat": 14, "fiber": 5},
                {"dish": "Sweet Potato and Chickpea Curry", "kcal": 420, "protein": 15, "carbs": 68, "fat": 11, "fiber": 12},
            ],
            # Lower calorie/fat meals
            "light": [
                {"dish": "Garden Salad with Grilled Chicken", "kcal": 280, "protein": 28, "carbs": 18, "fat": 10, "fiber": 6},
                {"dish": "Vegetable Soup with Lentils", "kcal": 220, "protein": 14, "carbs": 32, "fat": 4, "fiber": 9},
                {"dish": "Grilled Shrimp with Zucchini Noodles", "kcal": 240, "protein": 26, "carbs": 14, "fat": 8, "fiber": 4},
                {"dish": "Egg White Omelette with Vegetables", "kcal": 180, "protein": 20, "carbs": 10, "fat": 6, "fiber": 3},
                {"dish": "Fruit and Cottage Cheese Plate", "kcal": 260, "protein": 22, "carbs": 32, "fat": 4, "fiber": 4},
            ],
            # Higher fat meals (moderate impact)
            "higher_fat": [
                {"dish": "Avocado Toast with Poached Eggs", "kcal": 480, "protein": 18, "carbs": 42, "fat": 28, "fiber": 10},
                {"dish": "Salmon Salad with Olive Oil Dressing", "kcal": 520, "protein": 32, "carbs": 18, "fat": 36, "fiber": 6},
                {"dish": "Almond Butter and Banana Sandwich", "kcal": 420, "protein": 14, "carbs": 48, "fat": 20, "fiber": 8},
                {"dish": "Cheese and Nut Platter with Crackers", "kcal": 480, "protein": 18, "carbs": 32, "fat": 32, "fiber": 4},
                {"dish": "Beef Stir-Fry with Cashews", "kcal": 580, "protein": 35, "carbs": 38, "fat": 32, "fiber": 5},
            ],
        }

    def _select_meals_for_day(self, recovery_score: Optional[float],
                              strain: Optional[float],
                              sleep_performance: Optional[float]) -> List[Dict]:
        """
        Select random meals for a day (no correlation with WHOOP metrics).

        Args:
            recovery_score: Recovery score (0-100) or None (ignored)
            strain: Strain score or None (ignored)
            sleep_performance: Sleep performance (0-100) or None (ignored)

        Returns:
            List of 2-4 meal dicts for the day
        """
        meals = []
        num_meals = random.randint(2, 4)

        # Randomly select meals from all categories with equal probability
        all_categories = ["high_protein", "balanced", "high_carb", "light", "higher_fat"]

        for _ in range(num_meals):
            category = random.choice(all_categories)
            meals.append(random.choice(self.meal_templates[category]))

        return meals

    def generate_for_date_range(self, start_date: datetime, end_date: datetime,
                                use_whoop_correlation: bool = True) -> int:
        """
        Generate synthetic nutrition data for a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            use_whoop_correlation: If True, correlate meals with WHOOP metrics

        Returns:
            Number of sessions (meals) created
        """
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        sessions_created = 0

        current_date = start_date
        while current_date <= end_date:
            # Get WHOOP data for this date if using correlation
            whoop_data = None
            if use_whoop_correlation:
                whoop_data = self.whoop_sync.get_whoop_data_for_date(current_date)

            recovery = whoop_data["recovery_score"] if whoop_data else None
            strain = whoop_data["strain"] if whoop_data else None
            sleep = whoop_data["sleep_performance"] if whoop_data else None

            # Select meals for this day
            meals = self._select_meals_for_day(recovery, strain, sleep)

            # Create session entries for each meal
            for i, meal in enumerate(meals):
                # Distribute meals throughout the day
                hour = 7 + (i * 4) + random.randint(-1, 1)  # Meals at ~7am, 11am, 3pm, 7pm
                minute = random.randint(0, 59)

                meal_datetime = current_date.replace(hour=hour, minute=minute)
                created_at = meal_datetime.timestamp()

                # Insert session (with dummy values for required fields)
                cur.execute("""
                    INSERT INTO sessions (
                        dish, portion_guess_g, ingredients_json,
                        kcal, protein_g, carbs_g, fat_g, fiber_g,
                        created_at, validated, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'Synthetic data for demo')
                """, (
                    meal["dish"],
                    100.0,  # Dummy portion guess
                    json.dumps([]),  # Empty ingredients list
                    meal["kcal"],
                    meal["protein"],
                    meal["carbs"],
                    meal["fat"],
                    meal["fiber"],
                    created_at
                ))

                sessions_created += 1

            current_date += timedelta(days=1)

        con.commit()
        con.close()

        return sessions_created

    def clear_synthetic_data(self):
        """Remove all synthetic nutrition data (sessions with 'Synthetic data' in notes)."""
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()

        cur.execute("DELETE FROM sessions WHERE notes = 'Synthetic data for demo'")
        deleted = cur.rowcount

        con.commit()
        con.close()

        print(f"Deleted {deleted} synthetic sessions")
        return deleted
