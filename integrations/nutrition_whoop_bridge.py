"""
Nutrition-WHOOP Bridge

Joins nutrition data from sessions with WHOOP physiological data.
Creates unified dataset for correlation analysis.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd

from integrations.db import DB_PATH


class NutritionWhoopBridge:
    """Bridges nutrition tracking data with WHOOP physiological metrics."""

    def __init__(self, db_path: str = DB_PATH):
        """Initialize bridge with database path."""
        self.db_path = db_path

    def get_daily_nutrition(self, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """
        Get aggregated daily nutrition data from sessions.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            DataFrame with columns: date, total_kcal, total_protein, total_carbs,
            total_fat, total_fiber, meal_count
        """
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")  # Exclusive upper bound

        con = sqlite3.connect(self.db_path)

        query = """
        SELECT
            DATE(created_at, 'unixepoch', 'localtime') as date,
            SUM(kcal) as total_kcal,
            SUM(protein_g) as total_protein,
            SUM(carbs_g) as total_carbs,
            SUM(fat_g) as total_fat,
            SUM(fiber_g) as total_fiber,
            COUNT(*) as meal_count
        FROM sessions
        WHERE DATE(created_at, 'unixepoch', 'localtime') >= ?
          AND DATE(created_at, 'unixepoch', 'localtime') < ?
          AND kcal IS NOT NULL
        GROUP BY DATE(created_at, 'unixepoch', 'localtime')
        ORDER BY date ASC
        """

        df = pd.read_sql_query(query, con, params=(start_str, end_str))
        con.close()

        return df

    def get_daily_whoop(self, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """
        Get daily WHOOP data.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            DataFrame with WHOOP metrics
        """
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        con = sqlite3.connect(self.db_path)

        query = """
        SELECT
            date,
            recovery_score,
            hrv,
            rhr,
            strain,
            avg_hr,
            sleep_performance,
            sleep_efficiency,
            sleep_duration_min,
            deep_sleep_min,
            rem_sleep_min,
            sleep_debt_min,
            calories_burned
        FROM whoop_daily_data
        WHERE date >= ? AND date <= ?
        ORDER BY date ASC
        """

        df = pd.read_sql_query(query, con, params=(start_str, end_str))
        con.close()

        return df

    def create_unified_dataset(self, start_date: datetime, end_date: datetime,
                               lag_days: int = 0) -> pd.DataFrame:
        """
        Create unified dataset joining nutrition and WHOOP data.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            lag_days: Number of days to lag nutrition data (0=same day, 1=next day, etc.)
                     For example, lag_days=1 means "nutrition on day N affects WHOOP on day N+1"

        Returns:
            DataFrame with both nutrition and WHOOP metrics aligned by date
        """
        # Get nutrition data
        nutrition_df = self.get_daily_nutrition(start_date, end_date)

        # Adjust WHOOP date range to account for lag
        whoop_start = start_date + timedelta(days=lag_days)
        whoop_end = end_date + timedelta(days=lag_days)
        whoop_df = self.get_daily_whoop(whoop_start, whoop_end)

        # Shift nutrition dates forward by lag_days for alignment
        if lag_days > 0:
            nutrition_df['date'] = pd.to_datetime(nutrition_df['date'])
            nutrition_df['date'] = nutrition_df['date'] + pd.Timedelta(days=lag_days)
            nutrition_df['date'] = nutrition_df['date'].dt.strftime('%Y-%m-%d')

        # Merge on date (inner join - only days with both nutrition and WHOOP data)
        merged_df = pd.merge(
            nutrition_df,
            whoop_df,
            on='date',
            how='inner',
            suffixes=('_nutrition', '_whoop')
        )

        # Add multi-factor derived features
        original_cols = len(merged_df.columns) if not merged_df.empty else 0
        merged_df = self._add_derived_features(merged_df)
        new_cols = len(merged_df.columns) if not merged_df.empty else 0
        derived_count = new_cols - original_cols

        if derived_count > 0:
            print(f"  [+] Added {derived_count} derived multi-factor features")

        return merged_df

    def _add_derived_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add multi-factor derived features for correlation analysis.

        Args:
            df: DataFrame with nutrition and WHOOP columns

        Returns:
            DataFrame with additional derived feature columns
        """
        if df.empty:
            return df

        # Avoid modifying original
        df = df.copy()

        # Multi-Factor Macro Combinations
        if 'total_protein' in df.columns and 'total_carbs' in df.columns:
            # 1. Combined protein and carbs
            df['combined_protein_and_carbs'] = df['total_protein'] + df['total_carbs']

            # 2. Protein times carbs (interaction term)
            df['protein_times_carbs'] = df['total_protein'] * df['total_carbs']

            # 3. Protein per gram of carbs
            df['protein_per_gram_of_carbs'] = df['total_protein'] / (df['total_carbs'] + 1)

        if 'total_protein' in df.columns and 'total_carbs' in df.columns and 'total_fat' in df.columns:
            # 4. Protein plus carbs per fat
            df['protein_plus_carbs_per_fat'] = (df['total_protein'] + df['total_carbs']) / (df['total_fat'] + 1)

            # 5. Total calories from macros
            df['total_calories_from_macros'] = (df['total_protein'] * 4 +
                                                df['total_carbs'] * 4 +
                                                df['total_fat'] * 9)

        if 'total_protein' in df.columns and 'total_kcal' in df.columns:
            # 6. Protein grams per 100 calories
            df['protein_grams_per_100_calories'] = (df['total_protein'] / (df['total_kcal'] + 1)) * 100

            # 7. Percent calories from protein
            df['percent_calories_from_protein'] = (df['total_protein'] * 4 / (df['total_kcal'] + 1)) * 100

        if 'total_carbs' in df.columns and 'total_kcal' in df.columns:
            # 8. Percent calories from carbs
            df['percent_calories_from_carbs'] = (df['total_carbs'] * 4 / (df['total_kcal'] + 1)) * 100

        if 'total_fat' in df.columns and 'total_kcal' in df.columns:
            # 9. Percent calories from fat
            df['percent_calories_from_fat'] = (df['total_fat'] * 9 / (df['total_kcal'] + 1)) * 100

        # Note: We do NOT create features that include WHOOP metrics in their calculation
        # (like carbs_divided_by_strain or protein_times_low_recovery) because those
        # create circular/tautological correlations when tested against the same WHOOP
        # metric they contain. We only create nutrition-only derived features.

        # Macro Balance Score (distance from ideal 30/40/30 split)
        if all(col in df.columns for col in ['percent_calories_from_protein', 'percent_calories_from_carbs', 'percent_calories_from_fat']):
            # 17. How far from ideal macro split
            df['how_far_from_ideal_macro_split'] = (
                abs(df['percent_calories_from_protein'] - 30) +
                abs(df['percent_calories_from_carbs'] - 40) +
                abs(df['percent_calories_from_fat'] - 30)
            ) / 3

        return df

    def create_lagged_datasets(self, start_date: datetime, end_date: datetime,
                               max_lag: int = 2) -> Dict[int, pd.DataFrame]:
        """
        Create multiple unified datasets with different lag periods.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            max_lag: Maximum number of lag days to test (default 2)
                    Creates datasets for lag 0, 1, 2

        Returns:
            Dict mapping lag days to DataFrame
            {0: same_day_df, 1: next_day_df, 2: two_days_later_df}
        """
        lagged_datasets = {}

        for lag in range(max_lag + 1):
            lagged_datasets[lag] = self.create_unified_dataset(start_date, end_date, lag_days=lag)

        return lagged_datasets

    def get_macros_summary(self, start_date: datetime, end_date: datetime) -> Dict:
        """
        Get summary statistics for macros over a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dict with mean, median, min, max for each macro
        """
        nutrition_df = self.get_daily_nutrition(start_date, end_date)

        if nutrition_df.empty:
            return {}

        summary = {
            "total_kcal": {
                "mean": nutrition_df["total_kcal"].mean(),
                "median": nutrition_df["total_kcal"].median(),
                "min": nutrition_df["total_kcal"].min(),
                "max": nutrition_df["total_kcal"].max(),
            },
            "total_protein": {
                "mean": nutrition_df["total_protein"].mean(),
                "median": nutrition_df["total_protein"].median(),
                "min": nutrition_df["total_protein"].min(),
                "max": nutrition_df["total_protein"].max(),
            },
            "total_carbs": {
                "mean": nutrition_df["total_carbs"].mean(),
                "median": nutrition_df["total_carbs"].median(),
                "min": nutrition_df["total_carbs"].min(),
                "max": nutrition_df["total_carbs"].max(),
            },
            "total_fat": {
                "mean": nutrition_df["total_fat"].mean(),
                "median": nutrition_df["total_fat"].median(),
                "min": nutrition_df["total_fat"].min(),
                "max": nutrition_df["total_fat"].max(),
            },
            "meal_count": {
                "mean": nutrition_df["meal_count"].mean(),
                "median": nutrition_df["meal_count"].median(),
                "min": nutrition_df["meal_count"].min(),
                "max": nutrition_df["meal_count"].max(),
            },
        }

        return summary

    def get_whoop_summary(self, start_date: datetime, end_date: datetime) -> Dict:
        """
        Get summary statistics for WHOOP metrics over a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dict with mean, median, min, max for each WHOOP metric
        """
        whoop_df = self.get_daily_whoop(start_date, end_date)

        if whoop_df.empty:
            return {}

        metrics = ["recovery_score", "hrv", "rhr", "strain", "sleep_performance",
                   "sleep_duration_min", "calories_burned"]

        summary = {}
        for metric in metrics:
            if metric in whoop_df.columns:
                summary[metric] = {
                    "mean": whoop_df[metric].mean(),
                    "median": whoop_df[metric].median(),
                    "min": whoop_df[metric].min(),
                    "max": whoop_df[metric].max(),
                }

        return summary

    def get_data_availability(self, start_date: datetime, end_date: datetime) -> Dict:
        """
        Check data availability for nutrition and WHOOP over a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dict with data availability stats
        """
        total_days = (end_date - start_date).days + 1

        nutrition_df = self.get_daily_nutrition(start_date, end_date)
        whoop_df = self.get_daily_whoop(start_date, end_date)

        nutrition_days = len(nutrition_df)
        whoop_days = len(whoop_df)

        # Count days with both
        merged_df = self.create_unified_dataset(start_date, end_date, lag_days=0)
        both_days = len(merged_df)

        return {
            "total_days": total_days,
            "nutrition_days": nutrition_days,
            "whoop_days": whoop_days,
            "both_days": both_days,
            "nutrition_coverage": nutrition_days / total_days if total_days > 0 else 0,
            "whoop_coverage": whoop_days / total_days if total_days > 0 else 0,
            "both_coverage": both_days / total_days if total_days > 0 else 0,
        }
