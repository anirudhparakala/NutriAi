"""
WHOOP Data Sync Manager

Handles syncing WHOOP data to local database with auto-refresh capability.
Syncs recovery, strain, sleep, and workout data for daily analysis.
"""

import sqlite3
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import streamlit as st

from integrations.whoop_client import WhoopClient
from integrations.db import DB_PATH, get_user_setting, set_user_setting


class WhoopSyncManager:
    """Manages syncing WHOOP data to local database."""

    def __init__(self):
        """Initialize sync manager with WHOOP client."""
        self.client = WhoopClient()
        self.db_path = DB_PATH

    def get_last_sync_date(self) -> Optional[datetime]:
        """Get the most recent date with synced WHOOP data."""
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("SELECT MAX(date) FROM whoop_daily_data")
        result = cur.fetchone()
        con.close()

        if result and result[0]:
            return datetime.strptime(result[0], "%Y-%m-%d")
        return None

    def sync_date_range(self, start_date: datetime, end_date: datetime, force_refresh: bool = False) -> int:
        """
        Sync WHOOP data for a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            force_refresh: If True, re-sync even if data already exists

        Returns:
            Number of days synced
        """
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        days_synced = 0

        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")

            # Check if data already exists
            if not force_refresh:
                cur.execute("SELECT date FROM whoop_daily_data WHERE date = ?", (date_str,))
                if cur.fetchone():
                    current_date += timedelta(days=1)
                    continue

            # Fetch WHOOP data for this date
            try:
                summary = self.client.get_daily_summary(current_date)

                # Extract data with None fallbacks
                recovery_score = summary.get("recovery_score")
                hrv = summary.get("hrv")
                rhr = summary.get("rhr")
                strain = summary.get("strain")
                avg_hr = summary.get("avg_hr")
                sleep_performance = summary.get("sleep_performance")
                sleep_efficiency = summary.get("sleep_efficiency")
                sleep_duration_min = summary.get("sleep_duration_min")
                deep_sleep_min = summary.get("deep_sleep_min")
                rem_sleep_min = summary.get("rem_sleep_min")
                sleep_debt_min = summary.get("sleep_debt_min")
                calories_burned = summary.get("calories_burned")
                workouts = summary.get("workouts", [])
                workouts_json = json.dumps(workouts) if workouts else None

                synced_at = time.time()

                # Insert or replace
                cur.execute("""
                    INSERT OR REPLACE INTO whoop_daily_data (
                        date, recovery_score, hrv, rhr, strain, avg_hr,
                        sleep_performance, sleep_efficiency, sleep_duration_min,
                        deep_sleep_min, rem_sleep_min, sleep_debt_min,
                        calories_burned, workouts_json, synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    date_str, recovery_score, hrv, rhr, strain, avg_hr,
                    sleep_performance, sleep_efficiency, sleep_duration_min,
                    deep_sleep_min, rem_sleep_min, sleep_debt_min,
                    calories_burned, workouts_json, synced_at
                ))

                days_synced += 1

            except Exception as e:
                print(f"⚠️  Failed to sync {date_str}: {e}")

            current_date += timedelta(days=1)

        con.commit()
        con.close()
        return days_synced

    def sync_recent_days(self, days: int = 30, force_refresh: bool = False) -> int:
        """
        Sync the most recent N days of WHOOP data.

        Args:
            days: Number of recent days to sync (default 30 for correlation window)
            force_refresh: If True, re-sync even if data already exists

        Returns:
            Number of days synced
        """
        end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = end_date - timedelta(days=days - 1)

        print(f"Syncing WHOOP data from {start_date.date()} to {end_date.date()}...")
        days_synced = self.sync_date_range(start_date, end_date, force_refresh)
        print(f"✅ Synced {days_synced} days of WHOOP data")

        return days_synced

    def sync_since_last(self) -> int:
        """
        Sync all data since the last sync date.
        If no previous sync, syncs last 30 days.

        Returns:
            Number of days synced
        """
        last_sync = self.get_last_sync_date()

        if last_sync:
            # Sync from day after last sync to today
            start_date = last_sync + timedelta(days=1)
            end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

            if start_date > end_date:
                print("✅ WHOOP data is already up to date")
                return 0

            print(f"Syncing WHOOP data since {last_sync.date()}...")
            days_synced = self.sync_date_range(start_date, end_date)
            print(f"✅ Synced {days_synced} new days of WHOOP data")
            return days_synced
        else:
            # First sync - get last 30 days
            print("No previous WHOOP data found. Syncing last 30 days...")
            return self.sync_recent_days(days=30)

    def sync_body_weight(self) -> bool:
        """
        Sync current body weight from WHOOP API to user settings.

        Returns:
            True if successful, False otherwise
        """
        try:
            body_data = self.client.get_body_measurement()

            if body_data and "body_measurement" in body_data and len(body_data["body_measurement"]) > 0:
                # Get most recent body measurement
                latest = body_data["body_measurement"][0]
                weight_kg = latest.get("weight_kilogram")

                if weight_kg:
                    set_user_setting("body_weight_kg", str(weight_kg))
                    print(f"✅ Synced body weight: {weight_kg} kg")
                    return True

            print("⚠️  No body weight data available from WHOOP")
            return False

        except Exception as e:
            print(f"⚠️  Failed to sync body weight: {e}")
            return False

    def get_whoop_data_for_date(self, date: datetime) -> Optional[Dict]:
        """
        Get WHOOP data for a specific date from local database.

        Args:
            date: Date to query

        Returns:
            Dict with WHOOP metrics, or None if not found
        """
        date_str = date.strftime("%Y-%m-%d")
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()

        cur.execute("SELECT * FROM whoop_daily_data WHERE date = ?", (date_str,))
        row = cur.fetchone()
        con.close()

        if not row:
            return None

        # Map columns to dict
        return {
            "date": row[0],
            "recovery_score": row[1],
            "hrv": row[2],
            "rhr": row[3],
            "strain": row[4],
            "avg_hr": row[5],
            "sleep_performance": row[6],
            "sleep_efficiency": row[7],
            "sleep_duration_min": row[8],
            "deep_sleep_min": row[9],
            "rem_sleep_min": row[10],
            "sleep_debt_min": row[11],
            "calories_burned": row[12],
            "workouts_json": row[13],
            "synced_at": row[14]
        }

    def get_whoop_data_range(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """
        Get WHOOP data for a date range from local database.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of dicts with WHOOP metrics, sorted by date
        """
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        con = sqlite3.connect(self.db_path)
        cur = con.cursor()

        cur.execute("""
            SELECT * FROM whoop_daily_data
            WHERE date >= ? AND date <= ?
            ORDER BY date ASC
        """, (start_str, end_str))

        rows = cur.fetchall()
        con.close()

        results = []
        for row in rows:
            results.append({
                "date": row[0],
                "recovery_score": row[1],
                "hrv": row[2],
                "rhr": row[3],
                "strain": row[4],
                "avg_hr": row[5],
                "sleep_performance": row[6],
                "sleep_efficiency": row[7],
                "sleep_duration_min": row[8],
                "deep_sleep_min": row[9],
                "rem_sleep_min": row[10],
                "sleep_debt_min": row[11],
                "calories_burned": row[12],
                "workouts_json": row[13],
                "synced_at": row[14]
            })

        return results


def auto_sync_on_startup(days: int = 30) -> bool:
    """
    Auto-sync WHOOP data on app startup.
    Should be called once at the beginning of the Streamlit app.

    Args:
        days: Number of recent days to ensure are synced (default 30)

    Returns:
        True if sync was successful, False otherwise
    """
    try:
        sync_manager = WhoopSyncManager()

        # Sync new data since last sync
        sync_manager.sync_since_last()

        # Ensure we have at least the last N days
        sync_manager.sync_recent_days(days=days, force_refresh=False)

        # Sync body weight
        sync_manager.sync_body_weight()

        return True

    except Exception as e:
        print(f"⚠️  WHOOP auto-sync failed: {e}")
        return False
