"""
Generate Demo Data Script

One-time backend script to generate synthetic nutrition data correlated
with real WHOOP data for academic demonstration.

Usage:
    python scripts/generate_demo_data.py
"""

import sys
import os

# Add parent directory to path so we can import integrations
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, timedelta
from integrations.synthetic_nutrition import SyntheticNutritionGenerator
from integrations.whoop_sync import WhoopSyncManager

print("=" * 70)
print("WHOOP-Nutrition Demo Data Generator")
print("=" * 70)

# Initialize
generator = SyntheticNutritionGenerator()
whoop_sync = WhoopSyncManager()

# Step 1: Sync WHOOP data (last 30 days)
print("\n[Step 1/3] Syncing WHOOP data...")
print("-" * 70)
days_synced = whoop_sync.sync_recent_days(days=30, force_refresh=False)
print(f"✅ Synced {days_synced} days of WHOOP data")

# Sync body weight
whoop_sync.sync_body_weight()

# Step 2: Check WHOOP data availability
print("\n[Step 2/3] Checking WHOOP data availability...")
print("-" * 70)
last_sync = whoop_sync.get_last_sync_date()

if last_sync:
    print(f"✅ WHOOP data available through {last_sync.date()}")

    # Get 30 days of data
    end_date = last_sync
    start_date = end_date - timedelta(days=29)

    whoop_data_range = whoop_sync.get_whoop_data_range(start_date, end_date)
    print(f"✅ Found {len(whoop_data_range)} days of WHOOP data")

    if len(whoop_data_range) < 7:
        print("⚠️  Warning: Less than 7 days of WHOOP data. Correlations may be weak.")
else:
    print("❌ No WHOOP data available. Please sync WHOOP data first.")
    exit(1)

# Step 3: Generate synthetic nutrition data
print("\n[Step 3/3] Generating synthetic nutrition data...")
print("-" * 70)

# Ask user for confirmation
print(f"\nThis will generate synthetic nutrition data for:")
print(f"  Date range: {start_date.date()} to {end_date.date()}")
print(f"  Duration: {len(whoop_data_range)} days")
print(f"  Meals per day: 2-4 (randomly selected)")
print(f"  Total meals: ~{len(whoop_data_range) * 3} meals")
print(f"\nMeals will be randomly generated from all meal categories.")
print(f"Analytics will discover any natural correlations with your WHOOP data.")

response = input("\nProceed with data generation? (yes/no): ").strip().lower()

if response != "yes":
    print("❌ Data generation cancelled")
    exit(0)

# Generate synthetic data
sessions_created = generator.generate_for_date_range(
    start_date, end_date, use_whoop_correlation=True
)

print(f"\n✅ Generated {sessions_created} synthetic meal sessions")

# Summary
print("\n" + "=" * 70)
print("✅ Demo data generation complete!")
print("=" * 70)
print(f"\nYou now have:")
print(f"  - {len(whoop_data_range)} days of real WHOOP data")
print(f"  - {sessions_created} random synthetic nutrition entries")
print(f"  - Ready to discover correlations between nutrition and physiology")

print(f"\nNext steps:")
print(f"  1. Run the Streamlit app: streamlit run app.py")
print(f"  2. Navigate to the WHOOP Analytics tab")
print(f"  3. View correlations and personalized suggestions")

print(f"\n💡 Note: This is synthetic data for academic demonstration only.")
print(f"   Real nutrition tracking will replace this data over time.")

print("\nTo clear synthetic data later, run:")
print("  python -c \"from integrations.synthetic_nutrition import SyntheticNutritionGenerator; SyntheticNutritionGenerator().clear_synthetic_data()\"")
