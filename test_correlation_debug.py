"""
Debug script to identify correlation issues.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from datetime import datetime, timedelta
from integrations.whoop_analytics import WhoopAnalytics
from integrations.nutrition_whoop_bridge import NutritionWhoopBridge

print("=" * 80)
print("CORRELATION DEBUG SCRIPT")
print("=" * 80)

# Initialize
analytics = WhoopAnalytics()
bridge = NutritionWhoopBridge()

# Test with 7 days
print("\n\n### TEST 1: 7-DAY ANALYSIS ###")
print("-" * 80)
end_date = datetime.now()
start_date = end_date - timedelta(days=6)

print(f"Date range: {start_date.date()} to {end_date.date()}")

# Check data availability
availability = bridge.get_data_availability(start_date, end_date)
print(f"\nData Availability:")
print(f"  Total days: {availability['total_days']}")
print(f"  WHOOP days: {availability['whoop_days']}")
print(f"  Nutrition days: {availability['nutrition_days']}")
print(f"  Both days: {availability['both_days']}")

# Get unified dataset to inspect
unified_df = bridge.create_unified_dataset(start_date, end_date, lag_days=0)
print(f"\nUnified Dataset:")
print(f"  Shape: {unified_df.shape}")
print(f"  Columns: {list(unified_df.columns)}")

if not unified_df.empty:
    print(f"\nFirst few rows:")
    print(unified_df.head())

    print(f"\nData types:")
    print(unified_df.dtypes)

    print(f"\nNaN counts:")
    print(unified_df.isna().sum())

    print(f"\nNutrition stats:")
    if 'total_protein' in unified_df.columns:
        print(f"  Protein: min={unified_df['total_protein'].min()}, max={unified_df['total_protein'].max()}, mean={unified_df['total_protein'].mean():.1f}")
    if 'total_carbs' in unified_df.columns:
        print(f"  Carbs: min={unified_df['total_carbs'].min()}, max={unified_df['total_carbs'].max()}, mean={unified_df['total_carbs'].mean():.1f}")

    print(f"\nWHOOP stats:")
    if 'recovery_score' in unified_df.columns:
        print(f"  Recovery: min={unified_df['recovery_score'].min()}, max={unified_df['recovery_score'].max()}, mean={unified_df['recovery_score'].mean():.1f}")
    if 'strain' in unified_df.columns:
        print(f"  Strain: min={unified_df['strain'].min()}, max={unified_df['strain'].max()}, mean={unified_df['strain'].mean():.1f}")

# Find correlations with DEBUG mode
print("\n\n### CORRELATION ANALYSIS (DEBUG MODE) ###")
print("-" * 80)

top_correlations = analytics.find_top_correlations(
    start_date, end_date,
    max_lag=2,
    top_n=10,
    min_significance=None,  # Auto-adjust
    debug=True  # Enable debug output
)

print("\n\n### RESULTS ###")
print("-" * 80)

if top_correlations.empty:
    print("[X] NO CORRELATIONS FOUND!")
else:
    print(f"[+] Found {len(top_correlations)} correlations:")
    print(top_correlations[['nutrition_metric', 'whoop_metric', 'correlation', 'p_value', 'n', 'lag_days', 'effect_size']].to_string())

# Test with 30 days
print("\n\n### TEST 2: 30-DAY ANALYSIS ###")
print("-" * 80)
end_date_30 = datetime.now()
start_date_30 = end_date_30 - timedelta(days=29)

print(f"Date range: {start_date_30.date()} to {end_date_30.date()}")

availability_30 = bridge.get_data_availability(start_date_30, end_date_30)
print(f"\nData Availability:")
print(f"  Total days: {availability_30['total_days']}")
print(f"  WHOOP days: {availability_30['whoop_days']}")
print(f"  Nutrition days: {availability_30['nutrition_days']}")
print(f"  Both days: {availability_30['both_days']}")

top_correlations_30 = analytics.find_top_correlations(
    start_date_30, end_date_30,
    max_lag=2,
    top_n=10,
    min_significance=None,
    debug=False  # Disable debug for cleaner output
)

print("\n### RESULTS ###")
if top_correlations_30.empty:
    print("[X] NO CORRELATIONS FOUND!")
else:
    print(f"[+] Found {len(top_correlations_30)} correlations:")
    print(top_correlations_30[['nutrition_metric', 'whoop_metric', 'correlation', 'p_value', 'n', 'lag_days', 'effect_size']].to_string())

print("\n" + "=" * 80)
print("DEBUG COMPLETE")
print("=" * 80)
