"""
WHOOP API Client - Wrapper for WHOOP REST API endpoints.

Handles authentication, API calls, and token refresh logic.
API Documentation: https://developer.whoop.com/api
"""

import requests
import streamlit as st
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import time

WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"


class WhoopClient:
    """Client for interacting with WHOOP API."""

    def __init__(self):
        """Initialize WHOOP client with credentials from secrets."""
        self.access_token = st.secrets.get("WHOOP_ACCESS_TOKEN")
        self.refresh_token = st.secrets.get("WHOOP_REFRESH_TOKEN")
        self.client_id = st.secrets.get("WHOOP_CLIENT_ID")
        self.client_secret = st.secrets.get("WHOOP_CLIENT_SECRET")

        if not self.access_token:
            raise ValueError("WHOOP_ACCESS_TOKEN not found in secrets.toml")

        self.headers = {
            "Authorization": f"Bearer {self.access_token}"
        }

    def _make_request(self, method: str, endpoint: str, params: Dict = None) -> Dict:
        """
        Make authenticated request to WHOOP API with auto-refresh on 401.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            Response JSON data
        """
        url = f"{WHOOP_API_BASE}/{endpoint}"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                timeout=30
            )

            # Handle token expiration
            if response.status_code == 401:
                print("⚠️ WHOOP token expired, attempting refresh...")
                if self._refresh_access_token():
                    # Retry with new token
                    response = requests.request(
                        method=method,
                        url=url,
                        headers=self.headers,
                        params=params,
                        timeout=30
                    )
                else:
                    raise Exception("Failed to refresh WHOOP access token")

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"❌ WHOOP API request failed: {e}")
            raise

    def _refresh_access_token(self) -> bool:
        """
        Refresh access token using refresh token.

        Returns:
            True if refresh successful, False otherwise
        """
        if not self.refresh_token or not self.client_id or not self.client_secret:
            print("❌ Missing refresh token or client credentials")
            return False

        try:
            response = requests.post(
                WHOOP_TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "offline"
                },
                timeout=10
            )

            response.raise_for_status()
            data = response.json()

            # Update tokens
            self.access_token = data["access_token"]
            self.refresh_token = data.get("refresh_token", self.refresh_token)
            self.headers["Authorization"] = f"Bearer {self.access_token}"

            print("✅ WHOOP token refreshed successfully")
            print(f"⚠️ Update secrets.toml with new tokens:")
            print(f"   WHOOP_ACCESS_TOKEN = \"{self.access_token}\"")
            print(f"   WHOOP_REFRESH_TOKEN = \"{self.refresh_token}\"")

            return True

        except Exception as e:
            print(f"❌ Token refresh failed: {e}")
            return False

    def _exchange_code_for_token(self, authorization_code: str, redirect_uri: str = "http://localhost:8080/callback") -> Dict:
        """
        Exchange authorization code for access and refresh tokens.

        Args:
            authorization_code: Authorization code from OAuth redirect
            redirect_uri: Redirect URI (must match what was used in authorization request)

        Returns:
            Dict with access_token, refresh_token, expires_in
        """
        if not self.client_id or not self.client_secret:
            raise ValueError("Missing client_id or client_secret")

        response = requests.post(
            WHOOP_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": redirect_uri
            },
            timeout=10
        )

        response.raise_for_status()
        return response.json()

    def get_profile(self) -> Dict:
        """
        Get user profile information.

        Returns:
            User profile dict with user_id, email, first_name, last_name
        """
        return self._make_request("GET", "user/profile/basic")

    def get_user_profile(self) -> Dict:
        """Alias for get_profile() for backward compatibility."""
        return self.get_profile()

    def get_body_measurement(self) -> Dict:
        """
        Get body measurements (height, weight, max HR).

        Returns:
            Dict with height_meter, weight_kilogram, max_heart_rate
        """
        return self._make_request("GET", "user/measurement/body")

    def get_cycle(self, start: str, end: str, limit: int = 25) -> List[Dict]:
        """
        Get physiological cycles (day strain, average HR).

        Args:
            start: Start datetime in ISO format (e.g., "2025-01-01T00:00:00.000Z")
            end: End datetime in ISO format
            limit: Max number of records to return (default 25)

        Returns:
            List of cycle records
        """
        params = {
            "start": start,
            "end": end,
            "limit": limit
        }
        response = self._make_request("GET", "cycle", params=params)
        return response.get("records", [])

    def get_recovery(self, start: str, end: str, limit: int = 25) -> List[Dict]:
        """
        Get recovery data (recovery score, HRV, RHR).

        Args:
            start: Start datetime in ISO format
            end: End datetime in ISO format
            limit: Max number of records to return (default 25)

        Returns:
            List of recovery records
        """
        params = {
            "start": start,
            "end": end,
            "limit": limit
        }
        response = self._make_request("GET", "recovery", params=params)
        return response.get("records", [])

    def get_sleep(self, start: str, end: str, limit: int = 25) -> List[Dict]:
        """
        Get sleep data (performance, duration, stages).

        Args:
            start: Start datetime in ISO format
            end: End datetime in ISO format
            limit: Max number of records to return (default 25)

        Returns:
            List of sleep records
        """
        params = {
            "start": start,
            "end": end,
            "limit": limit
        }
        response = self._make_request("GET", "activity/sleep", params=params)
        return response.get("records", [])

    def get_workout(self, start: str, end: str, limit: int = 25) -> List[Dict]:
        """
        Get workout data (activity type, strain, duration).

        Args:
            start: Start datetime in ISO format
            end: End datetime in ISO format
            limit: Max number of records to return (default 25)

        Returns:
            List of workout records
        """
        params = {
            "start": start,
            "end": end,
            "limit": limit
        }
        response = self._make_request("GET", "activity/workout", params=params)
        return response.get("records", [])

    def get_daily_summary(self, date: datetime) -> Dict:
        """
        Get complete daily summary (recovery, strain, sleep, workouts).

        Aggregates all metrics for a single day into unified dict.

        Args:
            date: Date to fetch data for

        Returns:
            Dict with all daily metrics:
            {
                'date': '2025-01-20',
                'recovery_score': 75,
                'hrv': 68,
                'rhr': 52,
                'strain': 12.5,
                'avg_hr': 75,
                'calories_burned': 2400,
                'sleep_performance': 88,
                'sleep_efficiency': 92,
                'sleep_duration_min': 450,
                'deep_sleep_min': 90,
                'rem_sleep_min': 110,
                'sleep_debt_min': 30,
                'workouts': [{'activity': 'Strength Training', 'strain': 8.5}]
            }
        """
        # ISO format for API (UTC timezone)
        start = date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + ".000Z"
        end = (date + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + ".000Z"

        daily_data = {
            'date': date.strftime('%Y-%m-%d')
        }

        try:
            # Fetch all endpoints with retries
            cycles = self.get_cycle(start, end, limit=5)
            recovery = self.get_recovery(start, end, limit=5)
            sleeps = self.get_sleep(start, end, limit=5)
            workouts = self.get_workout(start, end, limit=10)

            # Extract cycle data (strain, avg HR, calories)
            if cycles:
                cycle = cycles[0]
                score = cycle.get('score', {})
                daily_data['strain'] = score.get('strain')
                daily_data['avg_hr'] = score.get('average_heart_rate')
                kilojoules = score.get('kilojoule', 0)
                daily_data['calories_burned'] = round(kilojoules * 0.239) if kilojoules else None

            # Extract recovery data (recovery score, HRV, RHR)
            if recovery:
                rec = recovery[0]
                score = rec.get('score', {})
                daily_data['recovery_score'] = score.get('recovery_score')
                daily_data['hrv'] = score.get('hrv_rmssd_milli')
                daily_data['rhr'] = score.get('resting_heart_rate')

            # Extract sleep data
            if sleeps:
                sleep = sleeps[0]
                score = sleep.get('score', {})
                daily_data['sleep_performance'] = score.get('sleep_performance_percentage')
                daily_data['sleep_efficiency'] = score.get('sleep_efficiency_percentage')

                # Convert milliseconds to minutes
                total_sleep_ms = score.get('total_in_bed_time_milli', 0)
                deep_sleep_ms = score.get('slow_wave_sleep_duration_milli', 0)
                rem_sleep_ms = score.get('rem_sleep_duration_milli', 0)
                sleep_debt_ms = score.get('sleep_debt_milli', 0)

                daily_data['sleep_duration_min'] = round(total_sleep_ms / 60000) if total_sleep_ms else None
                daily_data['deep_sleep_min'] = round(deep_sleep_ms / 60000) if deep_sleep_ms else None
                daily_data['rem_sleep_min'] = round(rem_sleep_ms / 60000) if rem_sleep_ms else None
                daily_data['sleep_debt_min'] = round(sleep_debt_ms / 60000) if sleep_debt_ms else None

            # Extract workout data
            daily_data['workouts'] = []
            for workout in workouts:
                score = workout.get('score', {})

                # v2 API uses ISO timestamps, parse them
                start_iso = workout.get('start')
                end_iso = workout.get('end')
                duration_min = None

                if start_iso and end_iso:
                    try:
                        start_dt = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
                        end_dt = datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
                        duration_min = round((end_dt - start_dt).total_seconds() / 60)
                    except:
                        pass

                daily_data['workouts'].append({
                    'activity': workout.get('sport_name', 'Unknown'),
                    'strain': score.get('strain'),
                    'duration_min': duration_min
                })

            return daily_data

        except Exception as e:
            print(f"⚠️ Failed to fetch complete daily summary for {date.strftime('%Y-%m-%d')}: {e}")
            return daily_data


# Convenience function for testing
def test_whoop_connection():
    """Test WHOOP API connection and print user info."""
    try:
        client = WhoopClient()

        print("🔄 Testing WHOOP API connection...")

        # Test profile
        profile = client.get_profile()
        print(f"✅ Connected to WHOOP API")
        print(f"   User: {profile.get('first_name')} {profile.get('last_name')}")
        print(f"   Email: {profile.get('email')}")

        # Test body measurement
        body = client.get_body_measurement()
        print(f"   Weight: {body.get('weight_kilogram')} kg")
        print(f"   Height: {body.get('height_meter')} m")

        # Test daily summary (yesterday)
        yesterday = datetime.now() - timedelta(days=1)
        summary = client.get_daily_summary(yesterday)
        print(f"\n📊 Yesterday's Summary ({summary['date']}):")
        print(f"   Recovery: {summary.get('recovery_score')}%")
        print(f"   Strain: {summary.get('strain')}")
        print(f"   Sleep Performance: {summary.get('sleep_performance')}%")

        return True

    except Exception as e:
        print(f"❌ WHOOP API test failed: {e}")
        return False


if __name__ == "__main__":
    # Run test when executed directly
    test_whoop_connection()
