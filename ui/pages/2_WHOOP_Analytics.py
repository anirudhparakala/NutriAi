"""
WHOOP Analytics Dashboard

Displays correlations between nutrition and WHOOP physiological metrics,
with personalized suggestions based on discovered patterns.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from integrations.whoop_analytics import WhoopAnalytics, get_readable_name
from integrations.whoop_suggestions import WhoopSuggestionEngine
from integrations.nutrition_whoop_bridge import NutritionWhoopBridge

st.set_page_config(
    page_title="WHOOP Analytics",
    page_icon="📊",
    layout="wide"
)

# Initialize
analytics = WhoopAnalytics()
suggestions_engine = WhoopSuggestionEngine()
bridge = NutritionWhoopBridge()

# Title
st.title("📊 WHOOP Analytics Dashboard")
st.markdown("Discover correlations between your nutrition and physiological metrics")

# Date range selector
col1, col2 = st.columns(2)
with col1:
    days_back = st.selectbox("Analysis Period", [7, 14, 30], index=2)

end_date = datetime.now()
start_date = end_date - timedelta(days=days_back-1)

# Check data availability
availability = bridge.get_data_availability(start_date, end_date)

st.markdown("---")

# Data availability summary
st.subheader("📅 Data Availability")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Days", availability["total_days"])

with col2:
    st.metric("WHOOP Data", f"{availability['whoop_days']} days",
              delta=f"{availability['whoop_coverage']*100:.0f}% coverage")

with col3:
    st.metric("Nutrition Data", f"{availability['nutrition_days']} days",
              delta=f"{availability['nutrition_coverage']*100:.0f}% coverage")

with col4:
    st.metric("Both Available", f"{availability['both_days']} days",
              delta=f"{availability['both_coverage']*100:.0f}% coverage")

if availability["both_days"] < 5:
    st.warning("⚠️ Not enough overlapping data for meaningful correlations. Need at least 5 days.")
    st.stop()

st.markdown("---")

# Personalized Suggestions
st.subheader("💡 Personalized Suggestions")

with st.spinner("Discovering correlations and generating suggestions..."):
    suggestions = suggestions_engine.generate_suggestions(
        start_date, end_date, max_lag=2, top_n=5
    )

if suggestions:
    for i, suggestion in enumerate(suggestions):
        nutrition_name = get_readable_name(suggestion['nutrition_metric'])
        whoop_name = get_readable_name(suggestion['whoop_metric'])
        with st.expander(f"Suggestion {i+1}: {nutrition_name} → {whoop_name}", expanded=(i==0)):
            # Suggestion text
            st.markdown(f"**{suggestion['suggestion']}**")

            # Stats
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Correlation", f"{suggestion['correlation']:.3f}")
            with col2:
                st.metric("Significance", f"p={suggestion['p_value']:.4f}")
            with col3:
                st.metric("Effect Size", suggestion['effect_size'].title())

            # Lag info
            if suggestion['lag_days'] > 0:
                st.info(f"📆 Effect observed {suggestion['lag_days']} day(s) after consumption")
else:
    st.info("No significant correlations found. This could mean:\n- Your nutrition is already well-optimized\n- More data is needed\n- Correlations are too weak to detect")

st.markdown("---")

# Top Correlations Table
st.subheader("📈 Top Correlations Discovered")

top_correlations = analytics.find_top_correlations(
    start_date, end_date, max_lag=2, top_n=10, min_significance=0.10
)

if not top_correlations.empty:
    # Format for display with human-readable names
    display_df = top_correlations.copy()
    display_df['nutrition_metric'] = display_df['nutrition_metric'].apply(get_readable_name)
    display_df['whoop_metric'] = display_df['whoop_metric'].apply(get_readable_name)
    display_df['correlation'] = display_df['correlation'].round(3)
    display_df['p_value'] = display_df['p_value'].round(4)

    st.dataframe(
        display_df[['nutrition_metric', 'whoop_metric', 'correlation', 'p_value', 'effect_size', 'lag_days', 'n']],
        use_container_width=True,
        column_config={
            "nutrition_metric": "Nutrition Metric",
            "whoop_metric": "WHOOP Metric",
            "correlation": st.column_config.NumberColumn("Correlation (r)", format="%.3f"),
            "p_value": st.column_config.NumberColumn("p-value", format="%.4f"),
            "effect_size": "Effect Size",
            "lag_days": "Lag (days)",
            "n": "Sample Size"
        }
    )
else:
    st.info("No statistically significant correlations found (p < 0.10)")

st.markdown("---")

# Strain-Controlled Correlations
st.subheader("🎯 Strain-Controlled Correlations")
st.markdown("Shows nutrition's **independent effect** after removing strain's influence (nutrition today → WHOOP metrics tomorrow)")

with st.spinner("Calculating partial correlations..."):
    strain_controlled = analytics.analyze_strain_controlled_correlations(start_date, end_date, lag_days=1)

if not strain_controlled.empty:
    # Filter to significant results and sort by controlled correlation
    significant_controlled = strain_controlled[strain_controlled['significant'] == True].copy()

    if not significant_controlled.empty:
        # Format for display with human-readable names
        display_controlled = significant_controlled.copy()
        display_controlled['nutrition_metric'] = display_controlled['nutrition_metric'].apply(get_readable_name)
        display_controlled['whoop_metric'] = display_controlled['whoop_metric'].apply(get_readable_name)
        display_controlled['raw_correlation'] = display_controlled['raw_correlation'].round(3)
        display_controlled['controlled_correlation'] = display_controlled['controlled_correlation'].round(3)
        display_controlled['strain_effect'] = display_controlled['strain_effect'].round(3)

        st.dataframe(
            display_controlled[['nutrition_metric', 'whoop_metric', 'raw_correlation', 'controlled_correlation', 'strain_effect', 'n']],
            use_container_width=True,
            column_config={
                "nutrition_metric": "Nutrition",
                "whoop_metric": "WHOOP Metric",
                "raw_correlation": st.column_config.NumberColumn("Raw r", format="%.3f", help="Correlation without controlling for strain"),
                "controlled_correlation": st.column_config.NumberColumn("Controlled r", format="%.3f", help="Correlation after removing strain's effect"),
                "strain_effect": st.column_config.NumberColumn("Strain Effect", format="%.3f", help="How much strain was confounding the relationship"),
                "n": "Sample Size"
            }
        )

        st.info("💡 **Interpretation**: If 'Controlled r' differs from 'Raw r', strain was confounding the relationship. The controlled value shows nutrition's true independent effect.")
    else:
        st.info("No significant strain-controlled correlations found")
else:
    st.info("Not enough data for strain-controlled analysis")

st.markdown("---")

# Stratified Analysis
st.subheader("📊 Stratified Analysis: Does Nutrition Matter More on High-Strain Days?")

with st.spinner("Analyzing strain groups..."):
    stratified = analytics.analyze_stratified_by_strain(start_date, end_date, lag_days=0)

if stratified and any(not df.empty for df in stratified.values()):
    tabs = st.tabs(["Low Strain", "Medium Strain", "High Strain"])

    for idx, (strain_level, tab) in enumerate(zip(['low', 'medium', 'high'], tabs)):
        with tab:
            if strain_level in stratified and not stratified[strain_level].empty:
                df = stratified[strain_level].copy()

                # Sort by correlation strength
                df['abs_corr'] = df['correlation'].abs()
                df = df.nlargest(10, 'abs_corr').drop(columns=['abs_corr'])

                # Format for display with human-readable names
                df['nutrition_metric'] = df['nutrition_metric'].apply(get_readable_name)
                df['whoop_metric'] = df['whoop_metric'].apply(get_readable_name)
                df['correlation'] = df['correlation'].round(3)
                df['p_value'] = df['p_value'].round(4)

                st.dataframe(
                    df[['nutrition_metric', 'whoop_metric', 'correlation', 'p_value', 'effect_size', 'n']],
                    use_container_width=True
                )
            else:
                st.info(f"Not enough data for {strain_level} strain analysis")
else:
    st.info("Not enough data for stratified analysis")

st.markdown("---")

# Interaction Effects
st.subheader("⚡ Interaction Effects: When Does Nutrition Matter MORE?")
st.markdown("Discover if nutrition's impact depends on context (strain, sleep debt, recovery state, etc.)")

with st.spinner("Analyzing interaction effects..."):
    interactions = analytics.analyze_interaction_effects(start_date, end_date, lag_days=0)

if not interactions.empty:
    # Filter to significant interactions
    significant_interactions = interactions[interactions['significant'] == True].copy()

    if not significant_interactions.empty:
        # Sort by absolute correlation
        significant_interactions['abs_corr'] = significant_interactions['interaction_correlation'].abs()
        significant_interactions = significant_interactions.nlargest(10, 'abs_corr').drop(columns=['abs_corr'])

        # Format for display with human-readable names
        display_interactions = significant_interactions.copy()
        display_interactions['nutrition_metric'] = display_interactions['nutrition_metric'].apply(get_readable_name)
        display_interactions['outcome_metric'] = display_interactions['outcome_metric'].apply(get_readable_name)
        display_interactions['interaction_correlation'] = display_interactions['interaction_correlation'].round(3)
        display_interactions['p_value'] = display_interactions['p_value'].round(4)

        st.dataframe(
            display_interactions[['interaction_type', 'nutrition_metric', 'outcome_metric', 'interaction_correlation', 'p_value', 'effect_size']],
            use_container_width=True,
            column_config={
                "interaction_type": "Interaction Type",
                "nutrition_metric": "Nutrition",
                "outcome_metric": "Outcome",
                "interaction_correlation": st.column_config.NumberColumn("Interaction r", format="%.3f"),
                "p_value": st.column_config.NumberColumn("p-value", format="%.4f"),
                "effect_size": "Effect Size"
            }
        )

        st.info("💡 **Interpretation**: Strong interactions mean nutrition's effect varies based on the moderator. Example: High protein matters MORE on high-strain days.")
    else:
        st.info("No significant interaction effects found")
else:
    st.info("Not enough data for interaction analysis")

st.markdown("---")

# Correlation Heatmap
st.subheader("🔥 Correlation Heatmap")

lag_choice = st.selectbox("Lag Period", [0, 1, 2], format_func=lambda x: f"Same day" if x == 0 else f"{x} day(s) later")

corr_matrix, p_value_matrix = analytics.get_correlation_matrix(start_date, end_date, lag_days=lag_choice)

if not corr_matrix.empty:
    # Create heatmap
    fig = go.Figure(data=go.Heatmap(
        z=corr_matrix.values,
        x=[col.replace('_', ' ').title() for col in corr_matrix.columns],
        y=[row.replace('total_', '').title() for row in corr_matrix.index],
        colorscale='RdBu_r',
        zmid=0,
        zmin=-1,
        zmax=1,
        text=corr_matrix.values.round(2),
        texttemplate='%{text}',
        textfont={"size": 10},
        colorbar=dict(title="Correlation")
    ))

    fig.update_layout(
        title=f"Nutrition vs WHOOP Metrics (Lag: {lag_choice} days)",
        xaxis_title="WHOOP Metrics",
        yaxis_title="Nutrition Metrics",
        height=500
    )

    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Not enough data to generate heatmap")

st.markdown("---")

# Macro and WHOOP Summaries
col1, col2 = st.columns(2)

with col1:
    st.subheader("🍽️ Nutrition Summary")
    macro_summary = bridge.get_macros_summary(start_date, end_date)

    if macro_summary:
        for metric, stats in macro_summary.items():
            metric_name = metric.replace('total_', '').replace('_', ' ').title()
            st.metric(
                metric_name,
                f"{stats['mean']:.0f}",
                delta=f"Range: {stats['min']:.0f}-{stats['max']:.0f}"
            )

with col2:
    st.subheader("💪 WHOOP Summary")
    whoop_summary = bridge.get_whoop_summary(start_date, end_date)

    if whoop_summary:
        # Show key metrics
        for metric in ["recovery_score", "strain", "sleep_performance", "hrv"]:
            if metric in whoop_summary:
                stats = whoop_summary[metric]
                metric_name = metric.replace('_', ' ').title()
                st.metric(
                    metric_name,
                    f"{stats['mean']:.1f}",
                    delta=f"Range: {stats['min']:.1f}-{stats['max']:.1f}"
                )

st.markdown("---")

# Footer
st.caption("💡 **How to interpret:**")
st.caption("- **Positive correlation**: Higher intake → Higher WHOOP metric")
st.caption("- **Negative correlation**: Higher intake → Lower WHOOP metric")
st.caption("- **p-value < 0.05**: High confidence in correlation")
st.caption("- **Effect size**: Weak (<0.3), Moderate (0.3-0.5), Strong (>0.5)")
st.caption("- **Lag days**: How many days after consumption the effect appears")
