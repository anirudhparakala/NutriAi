"""
Test script for advanced analytics features:
- Partial correlation (strain-controlled)
- Stratified analysis
- Interaction effects
- Context-aware suggestions
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from datetime import datetime, timedelta
from integrations.whoop_analytics import WhoopAnalytics
from integrations.whoop_suggestions import WhoopSuggestionEngine

print("=" * 80)
print("ADVANCED ANALYTICS TEST")
print("=" * 80)

analytics = WhoopAnalytics()
suggestions_engine = WhoopSuggestionEngine()

end_date = datetime.now()
start_date = end_date - timedelta(days=29)

print(f"\nDate range: {start_date.date()} to {end_date.date()}")

# Test 1: Strain-Controlled Correlations
print("\n\n### TEST 1: STRAIN-CONTROLLED CORRELATIONS ###")
print("-" * 80)

controlled = analytics.analyze_strain_controlled_correlations(start_date, end_date, lag_days=0)

if not controlled.empty:
    significant = controlled[controlled['significant'] == True]
    print(f"Found {len(significant)} significant strain-controlled correlations:")

    if not significant.empty:
        print("\nTop 5:")
        significant['abs_controlled'] = significant['controlled_correlation'].abs()
        top5 = significant.nlargest(5, 'abs_controlled')
        for _, row in top5.iterrows():
            print(f"  {row['nutrition_metric']} -> {row['whoop_metric']}")
            print(f"    Raw r: {row['raw_correlation']:.3f}")
            print(f"    Controlled r: {row['controlled_correlation']:.3f}")
            print(f"    Strain effect: {row['strain_effect']:.3f}")
else:
    print("No strain-controlled correlations found")

# Test 2: Stratified Analysis
print("\n\n### TEST 2: STRATIFIED ANALYSIS (BY STRAIN LEVEL) ###")
print("-" * 80)

stratified = analytics.analyze_stratified_by_strain(start_date, end_date, lag_days=0)

for strain_level in ['low', 'medium', 'high']:
    print(f"\n{strain_level.upper()} STRAIN:")
    if strain_level in stratified and not stratified[strain_level].empty:
        df = stratified[strain_level]
        print(f"  {len(df)} correlations found")

        if not df.empty:
            df['abs_corr'] = df['correlation'].abs()
            top3 = df.nlargest(3, 'abs_corr')
            for _, row in top3.iterrows():
                print(f"    {row['nutrition_metric']} -> {row['whoop_metric']}: r={row['correlation']:.3f}")
    else:
        print("  No data")

# Test 3: Interaction Effects
print("\n\n### TEST 3: INTERACTION EFFECTS ###")
print("-" * 80)

interactions = analytics.analyze_interaction_effects(start_date, end_date, lag_days=0)

if not interactions.empty:
    significant = interactions[interactions['significant'] == True]
    print(f"Found {len(significant)} significant interaction effects:")

    if not significant.empty:
        print("\nTop 5:")
        significant['abs_interaction'] = significant['interaction_correlation'].abs()
        top5 = significant.nlargest(5, 'abs_interaction')
        for _, row in top5.iterrows():
            print(f"  {row['interaction_type']}: {row['nutrition_metric']} -> {row['outcome_metric']}")
            print(f"    Interaction r: {row['interaction_correlation']:.3f}, p={row['p_value']:.4f}")
            print(f"    {row['interpretation']}")
else:
    print("No interaction effects found")

# Test 4: Context-Aware Suggestions
print("\n\n### TEST 4: CONTEXT-AWARE SUGGESTIONS ###")
print("-" * 80)

# Simulate high strain scenario
context_suggestions = suggestions_engine.generate_context_aware_suggestions(
    start_date, end_date,
    current_strain=16.5,  # High strain
    current_recovery=45.0,  # Low recovery
    current_sleep_debt=120.0  # 2 hours sleep debt
)

if context_suggestions:
    print(f"Generated {len(context_suggestions)} context-aware suggestions:")
    for i, sugg in enumerate(context_suggestions, 1):
        print(f"\n{i}. Type: {sugg['type']}")
        print(f"   {sugg['suggestion']}")
else:
    print("No context-aware suggestions generated")

print("\n" + "=" * 80)
print("TESTING COMPLETE")
print("=" * 80)
