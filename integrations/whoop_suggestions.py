"""
WHOOP-Based Nutrition Suggestions

Generates personalized, data-driven nutrition recommendations based on
correlations between nutrition and WHOOP metrics.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd

from integrations.whoop_analytics import WhoopAnalytics
from integrations.nutrition_whoop_bridge import NutritionWhoopBridge


class WhoopSuggestionEngine:
    """Generates personalized nutrition suggestions based on WHOOP correlations."""

    def __init__(self):
        """Initialize suggestion engine with analytics and bridge."""
        self.analytics = WhoopAnalytics()
        self.bridge = NutritionWhoopBridge()

    def _format_metric_name(self, metric: str) -> str:
        """Convert metric name to human-readable format."""
        metric_names = {
            "total_kcal": "calories",
            "total_protein": "protein",
            "total_carbs": "carbohydrates",
            "total_fat": "fat",
            "total_fiber": "fiber",
            "recovery_score": "recovery",
            "hrv": "heart rate variability (HRV)",
            "rhr": "resting heart rate",
            "strain": "daily strain",
            "sleep_performance": "sleep quality",
            "sleep_duration_min": "sleep duration",
            "deep_sleep_min": "deep sleep",
            "rem_sleep_min": "REM sleep",
        }
        return metric_names.get(metric, metric.replace("_", " "))

    def _get_lag_description(self, lag_days: int) -> str:
        """Convert lag days to human-readable format."""
        if lag_days == 0:
            return "on the same day"
        elif lag_days == 1:
            return "the next day"
        elif lag_days == 2:
            return "two days later"
        else:
            return f"{lag_days} days later"

    def _generate_suggestion_text(self, nutrition_metric: str, whoop_metric: str,
                                   correlation: float, effect_size: str,
                                   lag_days: int, current_avg: float,
                                   recommended_change: str) -> str:
        """
        Generate natural language suggestion text.

        Args:
            nutrition_metric: Nutrition variable
            whoop_metric: WHOOP variable
            correlation: Correlation coefficient
            effect_size: Effect size category
            lag_days: Lag days
            current_avg: Current average intake
            recommended_change: "increase" or "decrease"

        Returns:
            Natural language suggestion string
        """
        nutrition_name = self._format_metric_name(nutrition_metric)
        whoop_name = self._format_metric_name(whoop_metric)
        lag_desc = self._get_lag_description(lag_days)

        # Determine strength word
        if effect_size == "strong":
            strength = "strongly"
        elif effect_size == "moderate":
            strength = "moderately"
        else:
            strength = "slightly"

        # Determine direction
        if correlation > 0:
            if recommended_change == "increase":
                direction = "higher"
                action = "increase"
            else:
                direction = "lower"
                action = "reduce"
        else:
            if recommended_change == "increase":
                direction = "higher"
                action = "reduce"
            else:
                direction = "lower"
                action = "increase"

        # Format current average
        if nutrition_metric == "total_kcal":
            current_str = f"{current_avg:.0f} kcal"
        elif nutrition_metric in ["total_protein", "total_carbs", "total_fat", "total_fiber"]:
            current_str = f"{current_avg:.0f}g"
        else:
            current_str = f"{current_avg:.1f}"

        # Construct suggestion
        suggestion = (
            f"Your {nutrition_name} intake is {strength} correlated with {whoop_name} {lag_desc}. "
            f"Your current average is {current_str}. "
            f"Consider {action}ing your {nutrition_name} to see if it improves your {whoop_name}."
        )

        return suggestion

    def generate_suggestions(self, start_date: datetime, end_date: datetime,
                            max_lag: int = 2, top_n: int = 5,
                            focus_whoop_metric: Optional[str] = None) -> List[Dict]:
        """
        Generate personalized nutrition suggestions based on correlations.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            max_lag: Maximum lag days to test
            top_n: Number of suggestions to generate
            focus_whoop_metric: Optional specific WHOOP metric to focus on
                               (e.g., "recovery_score")

        Returns:
            List of suggestion dicts with text, metrics, and stats
        """
        # Get top correlations
        top_correlations = self.analytics.find_top_correlations(
            start_date, end_date, max_lag, top_n=20, min_significance=0.05
        )

        if top_correlations.empty:
            return []

        # Filter by focus metric if specified
        if focus_whoop_metric:
            top_correlations = top_correlations[
                top_correlations["whoop_metric"] == focus_whoop_metric
            ]

        # Get macro summary for current averages
        macro_summary = self.bridge.get_macros_summary(start_date, end_date)

        suggestions = []

        for _, row in top_correlations.head(top_n).iterrows():
            nutrition_metric = row["nutrition_metric"]
            whoop_metric = row["whoop_metric"]
            correlation = row["correlation"]
            effect_size = row["effect_size"]
            lag_days = row["lag_days"]
            p_value = row["p_value"]

            # Get current average
            if nutrition_metric in macro_summary:
                current_avg = macro_summary[nutrition_metric]["mean"]
            else:
                current_avg = 0

            # Determine recommended change direction
            # Positive correlation: increase nutrition to increase WHOOP metric
            # Negative correlation: decrease nutrition to increase WHOOP metric
            if correlation > 0:
                recommended_change = "increase"
            else:
                recommended_change = "decrease"

            # Generate suggestion text
            suggestion_text = self._generate_suggestion_text(
                nutrition_metric, whoop_metric, correlation, effect_size,
                lag_days, current_avg, recommended_change
            )

            suggestions.append({
                "suggestion": suggestion_text,
                "nutrition_metric": nutrition_metric,
                "whoop_metric": whoop_metric,
                "correlation": correlation,
                "p_value": p_value,
                "effect_size": effect_size,
                "lag_days": lag_days,
                "current_avg": current_avg,
                "recommended_change": recommended_change,
            })

        return suggestions

    def get_recovery_focused_suggestions(self, start_date: datetime, end_date: datetime,
                                         max_lag: int = 2) -> List[Dict]:
        """
        Get suggestions specifically focused on improving recovery.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            max_lag: Maximum lag days to test

        Returns:
            List of recovery-focused suggestions
        """
        return self.generate_suggestions(
            start_date, end_date, max_lag, top_n=3, focus_whoop_metric="recovery_score"
        )

    def get_sleep_focused_suggestions(self, start_date: datetime, end_date: datetime,
                                      max_lag: int = 2) -> List[Dict]:
        """
        Get suggestions specifically focused on improving sleep.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            max_lag: Maximum lag days to test

        Returns:
            List of sleep-focused suggestions
        """
        return self.generate_suggestions(
            start_date, end_date, max_lag, top_n=3, focus_whoop_metric="sleep_performance"
        )

    def get_actionable_insights(self, start_date: datetime, end_date: datetime,
                               max_lag: int = 2) -> Dict:
        """
        Get actionable insights with specific numeric targets.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            max_lag: Maximum lag days to test

        Returns:
            Dict with actionable insights by category
        """
        # Get top correlations
        top_correlations = self.analytics.find_top_correlations(
            start_date, end_date, max_lag, top_n=10, min_significance=0.05
        )

        if top_correlations.empty:
            return {
                "recovery_insights": [],
                "sleep_insights": [],
                "performance_insights": [],
            }

        # Get macro summary
        macro_summary = self.bridge.get_macros_summary(start_date, end_date)

        # Categorize insights
        recovery_insights = []
        sleep_insights = []
        performance_insights = []

        for _, row in top_correlations.iterrows():
            nutrition_metric = row["nutrition_metric"]
            whoop_metric = row["whoop_metric"]
            correlation = row["correlation"]
            effect_size = row["effect_size"]

            # Get current average
            current_avg = macro_summary.get(nutrition_metric, {}).get("mean", 0)

            # Calculate suggested target (10% change for weak, 20% for moderate/strong)
            if effect_size in ["moderate", "strong"]:
                change_pct = 0.20
            else:
                change_pct = 0.10

            if correlation > 0:
                suggested_target = current_avg * (1 + change_pct)
                change_direction = "increase"
            else:
                suggested_target = current_avg * (1 - change_pct)
                change_direction = "decrease"

            insight = {
                "metric": self._format_metric_name(nutrition_metric),
                "current": current_avg,
                "suggested": suggested_target,
                "change_direction": change_direction,
                "correlation": correlation,
                "effect_size": effect_size,
            }

            # Categorize by WHOOP metric
            if whoop_metric == "recovery_score":
                recovery_insights.append(insight)
            elif whoop_metric in ["sleep_performance", "sleep_duration_min", "deep_sleep_min", "rem_sleep_min"]:
                sleep_insights.append(insight)
            elif whoop_metric in ["strain", "hrv", "rhr"]:
                performance_insights.append(insight)

        return {
            "recovery_insights": recovery_insights[:3],
            "sleep_insights": sleep_insights[:3],
            "performance_insights": performance_insights[:3],
        }

    def generate_context_aware_suggestions(self, start_date: datetime, end_date: datetime,
                                          current_strain: float = None,
                                          current_recovery: float = None,
                                          current_sleep_debt: float = None) -> List[Dict]:
        """
        Generate context-aware suggestions based on current physiological state.

        Considers:
        - Strain level (high/medium/low)
        - Recovery state (low/medium/high)
        - Sleep debt (present or not)
        - Interaction effects (when does nutrition matter MORE?)

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            current_strain: Current strain score (optional)
            current_recovery: Current recovery score (optional)
            current_sleep_debt: Current sleep debt in minutes (optional)

        Returns:
            List of context-aware suggestion dicts
        """
        suggestions = []

        # Get interaction effects
        interactions = self.analytics.analyze_interaction_effects(start_date, end_date, lag_days=0)

        # Get stratified analysis
        stratified = self.analytics.analyze_stratified_by_strain(start_date, end_date, lag_days=0)

        # Get strain-controlled correlations
        controlled = self.analytics.analyze_strain_controlled_correlations(start_date, end_date, lag_days=0)

        # Get macro summary
        macro_summary = self.bridge.get_macros_summary(start_date, end_date)

        # 1. Strain-based suggestions
        if current_strain is not None:
            if current_strain > 15:
                strain_level = "high"
                strain_group = "high"
            elif current_strain > 8:
                strain_level = "medium"
                strain_group = "medium"
            else:
                strain_level = "low"
                strain_group = "low"

            # Check if nutrition matters more on this strain level
            if stratified and strain_group in stratified and not stratified[strain_group].empty:
                df_temp = stratified[strain_group].copy()
                df_temp['abs_corr'] = df_temp['correlation'].abs()
                top_corr = df_temp.nlargest(1, 'abs_corr')

                if not top_corr.empty:
                    row = top_corr.iloc[0]
                    nutrition_metric = row['nutrition_metric']
                    current_avg = macro_summary.get(nutrition_metric, {}).get("mean", 0)

                    if nutrition_metric in ["total_protein", "total_carbs", "total_kcal"]:
                        unit = "g" if nutrition_metric != "total_kcal" else "kcal"
                        current_str = f"{current_avg:.0f}{unit}"

                        suggestion_text = (
                            f"🔥 **Strain Context**: You're experiencing {strain_level} strain today (strain={current_strain:.1f}). "
                            f"Based on your data, {self._format_metric_name(nutrition_metric)} matters MORE on {strain_level}-strain days. "
                            f"Your current average is {current_str}. "
                            f"Consider {'increasing' if row['correlation'] > 0 else 'decreasing'} intake to optimize {self._format_metric_name(row['whoop_metric'])}."
                        )

                        suggestions.append({
                            "type": "strain_context",
                            "suggestion": suggestion_text,
                            "strain_level": strain_level,
                            "nutrition_metric": nutrition_metric,
                            "whoop_metric": row['whoop_metric'],
                            "correlation": row['correlation']
                        })

        # 2. Recovery-based suggestions
        if current_recovery is not None:
            if current_recovery < 33:
                recovery_state = "low"
                recovery_msg = "low recovery"
            elif current_recovery < 66:
                recovery_state = "medium"
                recovery_msg = "moderate recovery"
            else:
                recovery_state = "high"
                recovery_msg = "high recovery"

            if current_recovery < 66:  # Only suggest on low/medium recovery
                # Find interactions involving recovery
                if not interactions.empty:
                    recovery_interactions = interactions[interactions['moderator'] == 'recovery_score']

                    if not recovery_interactions.empty:
                        significant = recovery_interactions[recovery_interactions['significant'] == True]

                        if not significant.empty:
                            row = significant.iloc[0]
                            nutrition_metric = row['nutrition_metric']
                            current_avg = macro_summary.get(nutrition_metric, {}).get("mean", 0)

                            if nutrition_metric in ["total_protein", "total_carbs", "total_kcal"]:
                                unit = "g" if nutrition_metric != "total_kcal" else "kcal"
                                current_str = f"{current_avg:.0f}{unit}"

                                suggestion_text = (
                                    f"⚡ **Recovery Context**: You're in {recovery_msg} state (recovery={current_recovery:.0f}%). "
                                    f"Your data shows nutrition matters MORE when recovery is low. "
                                    f"Focus on {self._format_metric_name(nutrition_metric)} today ({current_str} current average) "
                                    f"to help improve {self._format_metric_name(row['outcome_metric'])}."
                                )

                                suggestions.append({
                                    "type": "recovery_context",
                                    "suggestion": suggestion_text,
                                    "recovery_state": recovery_state,
                                    "nutrition_metric": nutrition_metric,
                                    "outcome_metric": row['outcome_metric']
                                })

        # 3. Sleep debt suggestions
        if current_sleep_debt is not None and current_sleep_debt > 60:  # More than 1 hour debt
            # Find interactions involving sleep debt
            if not interactions.empty:
                sleep_interactions = interactions[interactions['moderator'] == 'sleep_debt_min']

                if not sleep_interactions.empty:
                    significant = sleep_interactions[sleep_interactions['significant'] == True]

                    if not significant.empty:
                        row = significant.iloc[0]
                        nutrition_metric = row['nutrition_metric']
                        current_avg = macro_summary.get(nutrition_metric, {}).get("mean", 0)

                        if nutrition_metric in ["total_protein", "total_carbs", "total_kcal"]:
                            unit = "g" if nutrition_metric != "total_kcal" else "kcal"
                            current_str = f"{current_avg:.0f}{unit}"

                            suggestion_text = (
                                f"😴 **Sleep Debt Context**: You have {current_sleep_debt:.0f} minutes of sleep debt. "
                                f"Your data shows {self._format_metric_name(nutrition_metric)} helps more when sleep-deprived. "
                                f"Current average: {current_str}. "
                                f"Prioritize this today to support {self._format_metric_name(row['outcome_metric'])}."
                            )

                            suggestions.append({
                                "type": "sleep_debt_context",
                                "suggestion": suggestion_text,
                                "sleep_debt_minutes": current_sleep_debt,
                                "nutrition_metric": nutrition_metric,
                                "outcome_metric": row['outcome_metric']
                            })

        # 4. Strain-controlled insights
        if not controlled.empty:
            significant_controlled = controlled[controlled['significant'] == True]

            if not significant_controlled.empty:
                # Find biggest differences between raw and controlled
                significant_controlled['diff'] = abs(significant_controlled['raw_correlation'] - significant_controlled['controlled_correlation'])
                top_diff = significant_controlled.nlargest(1, 'diff')

                if not top_diff.empty:
                    row = top_diff.iloc[0]
                    nutrition_metric = row['nutrition_metric']
                    current_avg = macro_summary.get(nutrition_metric, {}).get("mean", 0)

                    if nutrition_metric in ["total_protein", "total_carbs", "total_kcal"]:
                        unit = "g" if nutrition_metric != "total_kcal" else "kcal"
                        current_str = f"{current_avg:.0f}{unit}"

                        suggestion_text = (
                            f"🎯 **Controlled Analysis**: After removing strain's effect, "
                            f"{self._format_metric_name(nutrition_metric)} has an independent correlation "
                            f"of {row['controlled_correlation']:.3f} with {self._format_metric_name(row['whoop_metric'])}. "
                            f"This is nutrition's TRUE effect. Current average: {current_str}."
                        )

                        suggestions.append({
                            "type": "strain_controlled",
                            "suggestion": suggestion_text,
                            "nutrition_metric": nutrition_metric,
                            "whoop_metric": row['whoop_metric'],
                            "raw_correlation": row['raw_correlation'],
                            "controlled_correlation": row['controlled_correlation']
                        })

        return suggestions
