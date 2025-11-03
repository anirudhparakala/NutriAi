"""
WHOOP Metrics Functions for LLM Chatbot

Provides WHOOP correlation and analytics data as callable functions
for the AI nutrition coach chatbot.
"""

from datetime import datetime, timedelta
from typing import Dict, List
import json

from integrations.whoop_analytics import WhoopAnalytics
from integrations.whoop_suggestions import WhoopSuggestionEngine
from integrations.nutrition_whoop_bridge import NutritionWhoopBridge


# Initialize analytics engines
analytics = WhoopAnalytics()
suggestions_engine = WhoopSuggestionEngine()
bridge = NutritionWhoopBridge()


def get_whoop_correlations(days_back: int = 30, min_significance: float = 0.05) -> Dict:
    """
    Get top correlations between nutrition and WHOOP metrics.

    Args:
        days_back: Number of days to analyze (default 30)
        min_significance: Minimum p-value for significance (default 0.05)

    Returns:
        Dict with top correlations and their statistics
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back-1)

    top_corr = analytics.find_top_correlations(
        start_date, end_date, max_lag=2, top_n=10, min_significance=min_significance
    )

    if top_corr.empty:
        return {
            "found_correlations": False,
            "message": "No significant correlations found in the specified period"
        }

    correlations = []
    for _, row in top_corr.iterrows():
        correlations.append({
            "nutrition_metric": row["nutrition_metric"],
            "whoop_metric": row["whoop_metric"],
            "correlation": round(row["correlation"], 3),
            "p_value": round(row["p_value"], 4),
            "effect_size": row["effect_size"],
            "lag_days": int(row["lag_days"]),
            "sample_size": int(row["n"])
        })

    return {
        "found_correlations": True,
        "days_analyzed": days_back,
        "correlations": correlations
    }


def get_whoop_suggestions(days_back: int = 30, focus_metric: str = None) -> Dict:
    """
    Get personalized nutrition suggestions based on WHOOP correlations.

    Args:
        days_back: Number of days to analyze (default 30)
        focus_metric: Optional WHOOP metric to focus on (recovery_score, sleep_performance, strain, hrv)

    Returns:
        Dict with personalized suggestions
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back-1)

    if focus_metric:
        suggestions = suggestions_engine.generate_suggestions(
            start_date, end_date, max_lag=2, top_n=3, focus_whoop_metric=focus_metric
        )
    else:
        suggestions = suggestions_engine.generate_suggestions(
            start_date, end_date, max_lag=2, top_n=5
        )

    if not suggestions:
        return {
            "found_suggestions": False,
            "message": "Not enough data to generate personalized suggestions"
        }

    formatted_suggestions = []
    for sugg in suggestions:
        formatted_suggestions.append({
            "suggestion": sugg["suggestion"],
            "nutrition_metric": sugg["nutrition_metric"],
            "whoop_metric": sugg["whoop_metric"],
            "correlation": round(sugg["correlation"], 3),
            "p_value": round(sugg["p_value"], 4),
            "effect_size": sugg["effect_size"],
            "current_average": round(sugg["current_avg"], 1),
            "recommended_change": sugg["recommended_change"]
        })

    return {
        "found_suggestions": True,
        "days_analyzed": days_back,
        "focus_metric": focus_metric,
        "suggestions": formatted_suggestions
    }


def get_whoop_recovery_suggestions(days_back: int = 30) -> Dict:
    """
    Get suggestions specifically for improving recovery score.

    Args:
        days_back: Number of days to analyze (default 30)

    Returns:
        Dict with recovery-focused suggestions
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back-1)

    suggestions = suggestions_engine.get_recovery_focused_suggestions(start_date, end_date, max_lag=2)

    if not suggestions:
        return {
            "found_suggestions": False,
            "message": "Not enough data to generate recovery suggestions"
        }

    formatted_suggestions = []
    for sugg in suggestions:
        formatted_suggestions.append({
            "suggestion": sugg["suggestion"],
            "nutrition_metric": sugg["nutrition_metric"],
            "correlation": round(sugg["correlation"], 3),
            "p_value": round(sugg["p_value"], 4),
            "effect_size": sugg["effect_size"],
            "current_average": round(sugg["current_avg"], 1),
            "recommended_change": sugg["recommended_change"]
        })

    return {
        "found_suggestions": True,
        "focus": "recovery_score",
        "days_analyzed": days_back,
        "suggestions": formatted_suggestions
    }


def get_whoop_sleep_suggestions(days_back: int = 30) -> Dict:
    """
    Get suggestions specifically for improving sleep performance.

    Args:
        days_back: Number of days to analyze (default 30)

    Returns:
        Dict with sleep-focused suggestions
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back-1)

    suggestions = suggestions_engine.get_sleep_focused_suggestions(start_date, end_date, max_lag=2)

    if not suggestions:
        return {
            "found_suggestions": False,
            "message": "Not enough data to generate sleep suggestions"
        }

    formatted_suggestions = []
    for sugg in suggestions:
        formatted_suggestions.append({
            "suggestion": sugg["suggestion"],
            "nutrition_metric": sugg["nutrition_metric"],
            "correlation": round(sugg["correlation"], 3),
            "p_value": round(sugg["p_value"], 4),
            "effect_size": sugg["effect_size"],
            "current_average": round(sugg["current_avg"], 1),
            "recommended_change": sugg["recommended_change"]
        })

    return {
        "found_suggestions": True,
        "focus": "sleep_performance",
        "days_analyzed": days_back,
        "suggestions": formatted_suggestions
    }


def get_whoop_data_availability(days_back: int = 30) -> Dict:
    """
    Check availability of WHOOP and nutrition data.

    Args:
        days_back: Number of days to check (default 30)

    Returns:
        Dict with data availability stats
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back-1)

    availability = bridge.get_data_availability(start_date, end_date)

    return {
        "total_days": availability["total_days"],
        "whoop_days": availability["whoop_days"],
        "nutrition_days": availability["nutrition_days"],
        "both_days": availability["both_days"],
        "whoop_coverage_pct": round(availability["whoop_coverage"] * 100, 1),
        "nutrition_coverage_pct": round(availability["nutrition_coverage"] * 100, 1),
        "both_coverage_pct": round(availability["both_coverage"] * 100, 1),
        "sufficient_for_analysis": availability["both_days"] >= 5
    }


def get_whoop_summary(days_back: int = 30) -> Dict:
    """
    Get summary statistics for WHOOP metrics.

    Args:
        days_back: Number of days to summarize (default 30)

    Returns:
        Dict with WHOOP metric averages and ranges
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back-1)

    whoop_summary = bridge.get_whoop_summary(start_date, end_date)

    if not whoop_summary:
        return {
            "found_data": False,
            "message": "No WHOOP data available for this period"
        }

    formatted_summary = {}
    for metric, stats in whoop_summary.items():
        formatted_summary[metric] = {
            "average": round(stats["mean"], 1),
            "min": round(stats["min"], 1),
            "max": round(stats["max"], 1),
            "median": round(stats["median"], 1)
        }

    return {
        "found_data": True,
        "days_analyzed": days_back,
        "metrics": formatted_summary
    }


def get_strain_controlled_correlations(days_back: int = 30) -> Dict:
    """
    Get correlations between nutrition and WHOOP metrics with strain's effect removed.

    Shows nutrition's TRUE independent effect after controlling for confounding strain influence.

    Args:
        days_back: Number of days to analyze (default 30)

    Returns:
        Dict with raw vs strain-controlled correlations
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back-1)

    controlled = analytics.analyze_strain_controlled_correlations(start_date, end_date, lag_days=0)

    if controlled.empty:
        return {
            "found_correlations": False,
            "message": "Not enough data for strain-controlled analysis"
        }

    significant = controlled[controlled['significant'] == True]

    if significant.empty:
        return {
            "found_correlations": False,
            "message": "No significant strain-controlled correlations found"
        }

    correlations = []
    for _, row in significant.iterrows():
        correlations.append({
            "nutrition_metric": row["nutrition_metric"],
            "whoop_metric": row["whoop_metric"],
            "raw_correlation": round(row["raw_correlation"], 3),
            "controlled_correlation": round(row["controlled_correlation"], 3),
            "strain_effect": round(row["strain_effect"], 3),
            "sample_size": int(row["n"])
        })

    return {
        "found_correlations": True,
        "days_analyzed": days_back,
        "explanation": "Controlled correlations show nutrition's independent effect after removing strain's confounding influence",
        "correlations": correlations
    }


def get_stratified_analysis(days_back: int = 30) -> Dict:
    """
    Analyze if nutrition matters MORE on high-strain days vs low-strain days.

    Splits data into low/medium/high strain groups and tests correlations within each.

    Args:
        days_back: Number of days to analyze (default 30)

    Returns:
        Dict with correlations for each strain level
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back-1)

    stratified = analytics.analyze_stratified_by_strain(start_date, end_date, lag_days=0)

    if not stratified or all(df.empty for df in stratified.values()):
        return {
            "found_analysis": False,
            "message": "Not enough data for stratified analysis"
        }

    results = {}
    for strain_level in ['low', 'medium', 'high']:
        if strain_level in stratified and not stratified[strain_level].empty:
            df = stratified[strain_level].copy()
            df['abs_corr'] = df['correlation'].abs()
            top3 = df.nlargest(3, 'abs_corr')

            correlations = []
            for _, row in top3.iterrows():
                correlations.append({
                    "nutrition_metric": row["nutrition_metric"],
                    "whoop_metric": row["whoop_metric"],
                    "correlation": round(row["correlation"], 3),
                    "p_value": round(row["p_value"], 4),
                    "effect_size": row["effect_size"],
                    "sample_size": int(row["n"])
                })

            results[strain_level] = {
                "found_correlations": True,
                "top_correlations": correlations
            }
        else:
            results[strain_level] = {
                "found_correlations": False,
                "message": "Not enough data for this strain level"
            }

    return {
        "found_analysis": True,
        "days_analyzed": days_back,
        "explanation": "Shows how nutrition's effect varies by strain level. If correlations differ, nutrition matters more on certain days.",
        "strain_groups": results
    }


def get_interaction_effects(days_back: int = 30) -> Dict:
    """
    Discover when nutrition matters MORE based on context.

    Tests 5 interaction types: Strain×Nutrition, SleepDebt×Nutrition, Recovery×Nutrition,
    HRV×Nutrition, CaloriesBurned×Nutrition.

    Args:
        days_back: Number of days to analyze (default 30)

    Returns:
        Dict with significant interaction effects
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back-1)

    interactions = analytics.analyze_interaction_effects(start_date, end_date, lag_days=0)

    if interactions.empty:
        return {
            "found_interactions": False,
            "message": "Not enough data for interaction analysis"
        }

    significant = interactions[interactions['significant'] == True]

    if significant.empty:
        return {
            "found_interactions": False,
            "message": "No significant interaction effects found"
        }

    effects = []
    for _, row in significant.iterrows():
        effects.append({
            "interaction_type": row["interaction_type"],
            "nutrition_metric": row["nutrition_metric"],
            "outcome_metric": row["outcome_metric"],
            "interaction_correlation": round(row["interaction_correlation"], 3),
            "p_value": round(row["p_value"], 4),
            "effect_size": row["effect_size"],
            "interpretation": row["interpretation"]
        })

    return {
        "found_interactions": True,
        "days_analyzed": days_back,
        "explanation": "Interaction effects show when nutrition's impact depends on context (e.g., protein helps MORE on high-strain days)",
        "interactions": effects
    }


def get_context_aware_suggestions(days_back: int = 30, current_strain: float = None,
                                  current_recovery: float = None, current_sleep_debt: float = None) -> Dict:
    """
    Get personalized suggestions based on current physiological state.

    Provides context-aware recommendations considering strain level, recovery state, and sleep debt.

    Args:
        days_back: Number of days to analyze (default 30)
        current_strain: Current strain score (optional)
        current_recovery: Current recovery score % (optional)
        current_sleep_debt: Current sleep debt in minutes (optional)

    Returns:
        Dict with context-aware suggestions
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back-1)

    suggestions = suggestions_engine.generate_context_aware_suggestions(
        start_date, end_date,
        current_strain=current_strain,
        current_recovery=current_recovery,
        current_sleep_debt=current_sleep_debt
    )

    if not suggestions:
        return {
            "found_suggestions": False,
            "message": "Not enough data to generate context-aware suggestions"
        }

    formatted_suggestions = []
    for sugg in suggestions:
        formatted_suggestions.append({
            "type": sugg["type"],
            "suggestion": sugg["suggestion"],
            "nutrition_metric": sugg.get("nutrition_metric"),
            "context": {
                "strain_level": sugg.get("strain_level"),
                "recovery_state": sugg.get("recovery_state"),
                "sleep_debt_minutes": sugg.get("sleep_debt_minutes")
            }
        })

    return {
        "found_suggestions": True,
        "days_analyzed": days_back,
        "current_context": {
            "strain": current_strain,
            "recovery": current_recovery,
            "sleep_debt": current_sleep_debt
        },
        "suggestions": formatted_suggestions
    }
