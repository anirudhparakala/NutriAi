"""
WHOOP Analytics Engine

Discovers correlations between nutrition and WHOOP metrics.
Calculates Pearson correlations, p-values, and effect sizes.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np
from scipy import stats
from scipy.stats import pearsonr

from integrations.nutrition_whoop_bridge import NutritionWhoopBridge


# Human-readable names for metrics
METRIC_DISPLAY_NAMES = {
    # Base nutrition metrics
    "total_kcal": "Calories",
    "total_protein": "Protein",
    "total_carbs": "Carbs",
    "total_fat": "Fat",
    "total_fiber": "Fiber",

    # Derived nutrition metrics
    "combined_protein_and_carbs": "Protein + Carbs",
    "protein_times_carbs": "Protein × Carbs (interaction)",
    "protein_per_gram_of_carbs": "Protein-to-Carb Ratio",
    "protein_plus_carbs_per_fat": "(Protein + Carbs) / Fat",
    "total_calories_from_macros": "Calculated Calories",
    "protein_grams_per_100_calories": "Protein Density (g/100 kcal)",
    "percent_calories_from_protein": "Protein %",
    "percent_calories_from_carbs": "Carbs %",
    "percent_calories_from_fat": "Fat %",
    "how_far_from_ideal_macro_split": "Macro Balance Score",

    # WHOOP metrics
    "recovery_score": "Recovery",
    "hrv": "HRV",
    "rhr": "Resting Heart Rate",
    "strain": "Strain",
    "sleep_performance": "Sleep Quality",
    "sleep_duration_min": "Sleep Duration",
    "deep_sleep_min": "Deep Sleep",
    "rem_sleep_min": "REM Sleep",
    "sleep_debt_min": "Sleep Debt",
    "calories_burned": "Calories Burned"
}


def get_readable_name(metric: str) -> str:
    """Convert technical metric name to human-readable display name."""
    return METRIC_DISPLAY_NAMES.get(metric, metric.replace('_', ' ').title())


class WhoopAnalytics:
    """Analyzes correlations between nutrition and WHOOP physiological metrics."""

    def __init__(self):
        """Initialize analytics engine with data bridge."""
        self.bridge = NutritionWhoopBridge()

    def calculate_partial_correlation(self, x: pd.Series, y: pd.Series, z: pd.Series, debug: bool = False) -> Dict:
        """
        Calculate partial correlation between x and y, controlling for z.

        Uses the formula: r_xy.z = (r_xy - r_xz * r_yz) / sqrt((1 - r_xz^2) * (1 - r_yz^2))

        Args:
            x: First variable (e.g., protein intake)
            y: Second variable (e.g., recovery score)
            z: Control variable (e.g., strain)
            debug: If True, print debug information

        Returns:
            Dict with partial correlation coefficient, p-value, effect size, and n
        """
        # Remove NaN triplets
        mask = ~(x.isna() | y.isna() | z.isna())
        x_clean = x[mask]
        y_clean = y[mask]
        z_clean = z[mask]

        n = len(x_clean)

        if debug:
            print(f"\n[DEBUG] Partial Correlation Calculation:")
            print(f"  Valid triplets: {n}")

        if n < 3:
            if debug:
                print(f"  [!] Skipped: n={n} < 3")
            return {
                "r": None,
                "p_value": None,
                "n": n,
                "effect_size": None,
                "significant": False
            }

        # Calculate pairwise correlations
        try:
            r_xy, _ = pearsonr(x_clean, y_clean)
            r_xz, _ = pearsonr(x_clean, z_clean)
            r_yz, _ = pearsonr(y_clean, z_clean)

            # Calculate partial correlation
            numerator = r_xy - (r_xz * r_yz)
            denominator = np.sqrt((1 - r_xz**2) * (1 - r_yz**2))

            if denominator == 0:
                if debug:
                    print(f"  [!] Skipped: Zero denominator")
                return {
                    "r": None,
                    "p_value": None,
                    "n": n,
                    "effect_size": None,
                    "significant": False
                }

            r_partial = numerator / denominator

            # Calculate p-value using t-distribution
            # t = r * sqrt(n - 3) / sqrt(1 - r^2)
            t_stat = r_partial * np.sqrt(n - 3) / np.sqrt(1 - r_partial**2)
            p_value = 2 * (1 - stats.t.cdf(abs(t_stat), n - 3))

            # Determine effect size
            abs_r = abs(r_partial)
            if abs_r >= 0.5:
                effect_size = "strong"
            elif abs_r >= 0.3:
                effect_size = "moderate"
            elif abs_r >= 0.1:
                effect_size = "weak"
            else:
                effect_size = "negligible"

            # Adjust significance threshold based on sample size
            if n < 10:
                significant = p_value < 0.15
            elif n < 15:
                significant = p_value < 0.10
            else:
                significant = p_value < 0.05

            if debug:
                print(f"  r_xy={r_xy:.3f}, r_xz={r_xz:.3f}, r_yz={r_yz:.3f}")
                print(f"  [+] r_partial={r_partial:.3f}, p={p_value:.4f}, n={n}, effect={effect_size}, sig={significant}")

            return {
                "r": r_partial,
                "p_value": p_value,
                "n": n,
                "effect_size": effect_size,
                "significant": significant,
                "r_xy": r_xy,
                "r_xz": r_xz,
                "r_yz": r_yz
            }

        except Exception as e:
            if debug:
                print(f"  [!] Error: {e}")
            return {
                "r": None,
                "p_value": None,
                "n": n,
                "effect_size": None,
                "significant": False
            }

    def calculate_correlation(self, x: pd.Series, y: pd.Series, debug: bool = False) -> Dict:
        """
        Calculate Pearson correlation with p-value and effect size.

        Args:
            x: First variable (e.g., protein intake)
            y: Second variable (e.g., recovery score)
            debug: If True, print debug information

        Returns:
            Dict with correlation coefficient, p-value, effect size category, and n
        """
        # Remove NaN pairs
        mask = ~(x.isna() | y.isna())
        x_clean = x[mask]
        y_clean = y[mask]

        n = len(x_clean)

        if debug:
            print(f"\n[DEBUG] Correlation Calculation:")
            print(f"  Original length: {len(x)}")
            print(f"  X NaN count: {x.isna().sum()}")
            print(f"  Y NaN count: {y.isna().sum()}")
            print(f"  Valid pairs: {n}")
            if n > 0:
                print(f"  X range: {x_clean.min():.2f} - {x_clean.max():.2f} (mean: {x_clean.mean():.2f})")
                print(f"  Y range: {y_clean.min():.2f} - {y_clean.max():.2f} (mean: {y_clean.mean():.2f})")
                print(f"  X std: {x_clean.std():.2f}, Y std: {y_clean.std():.2f}")

        if n < 3:
            # Not enough data points for meaningful correlation
            if debug:
                print(f"  [!] Skipped: n={n} < 3")
            return {
                "r": None,
                "p_value": None,
                "n": n,
                "effect_size": None,
                "significant": False
            }

        # Check for zero variance
        if x_clean.std() == 0 or y_clean.std() == 0:
            if debug:
                print(f"  [!] Skipped: Zero variance (X std={x_clean.std():.3f}, Y std={y_clean.std():.3f})")
            return {
                "r": None,
                "p_value": None,
                "n": n,
                "effect_size": None,
                "significant": False
            }

        # Calculate Pearson correlation
        r, p_value = stats.pearsonr(x_clean, y_clean)

        # Determine effect size (Cohen's guidelines)
        abs_r = abs(r)
        if abs_r >= 0.5:
            effect_size = "strong"
        elif abs_r >= 0.3:
            effect_size = "moderate"
        elif abs_r >= 0.1:
            effect_size = "weak"
        else:
            effect_size = "negligible"

        # Adjust significance threshold based on sample size
        if n < 10:
            # Use more lenient threshold for small samples
            significant = p_value < 0.15
        elif n < 15:
            significant = p_value < 0.10
        else:
            significant = p_value < 0.05

        if debug:
            print(f"  [+] r={r:.3f}, p={p_value:.4f}, n={n}, effect={effect_size}, sig={significant}")

        return {
            "r": r,
            "p_value": p_value,
            "n": n,
            "effect_size": effect_size,
            "significant": significant
        }

    def analyze_macro_whoop_correlations(self, start_date: datetime, end_date: datetime,
                                         lag_days: int = 0, debug: bool = False) -> pd.DataFrame:
        """
        Analyze correlations between macros and WHOOP metrics.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            lag_days: Number of days to lag nutrition data (0=same day, 1=next day, etc.)
            debug: If True, print debug information

        Returns:
            DataFrame with correlation results for each macro-WHOOP pair
        """
        # Get unified dataset
        unified_df = self.bridge.create_unified_dataset(start_date, end_date, lag_days)

        if debug:
            print(f"\n[DEBUG] Analyze Macro-WHOOP Correlations:")
            print(f"  Date range: {start_date.date()} to {end_date.date()}")
            print(f"  Lag days: {lag_days}")
            print(f"  Unified dataset shape: {unified_df.shape}")
            print(f"  Columns: {list(unified_df.columns)}")
            if not unified_df.empty:
                print(f"  Date range in data: {unified_df['date'].min()} to {unified_df['date'].max()}")
                print(f"  Sample nutrition data:\n{unified_df[['date', 'total_protein', 'total_carbs']].head()}")
                print(f"  Sample WHOOP data:\n{unified_df[['date', 'recovery_score', 'strain']].head()}")

        if unified_df.empty:
            if debug:
                print("  [!] Empty unified dataset!")
            return pd.DataFrame()

        # Nutrition variables to test (ONLY nutrition-derived, no WHOOP metrics included)
        nutrition_vars = [
            # Base macros
            "total_kcal", "total_protein", "total_carbs", "total_fat", "total_fiber",
            # Multi-factor combinations
            "combined_protein_and_carbs", "protein_times_carbs", "protein_per_gram_of_carbs",
            "protein_plus_carbs_per_fat", "total_calories_from_macros",
            # Macro percentages and density
            "protein_grams_per_100_calories", "percent_calories_from_protein",
            "percent_calories_from_carbs", "percent_calories_from_fat",
            # Macro balance
            "how_far_from_ideal_macro_split"
        ]

        # WHOOP variables to test
        whoop_vars = ["recovery_score", "hrv", "rhr", "strain", "sleep_performance",
                      "sleep_duration_min", "deep_sleep_min", "rem_sleep_min"]

        results = []

        for nutrition_var in nutrition_vars:
            if nutrition_var not in unified_df.columns:
                if debug:
                    print(f"  [!] Nutrition variable '{nutrition_var}' not found in dataset")
                continue

            for whoop_var in whoop_vars:
                if whoop_var not in unified_df.columns:
                    if debug:
                        print(f"  [!] WHOOP variable '{whoop_var}' not found in dataset")
                    continue

                if debug:
                    print(f"\n  Testing: {nutrition_var} -> {whoop_var}")

                corr_result = self.calculate_correlation(
                    unified_df[nutrition_var],
                    unified_df[whoop_var],
                    debug=debug
                )

                results.append({
                    "nutrition_metric": nutrition_var,
                    "whoop_metric": whoop_var,
                    "lag_days": lag_days,
                    "correlation": corr_result["r"],
                    "p_value": corr_result["p_value"],
                    "n": corr_result["n"],
                    "effect_size": corr_result["effect_size"],
                    "significant": corr_result["significant"]
                })

        results_df = pd.DataFrame(results)
        return results_df

    def find_top_correlations(self, start_date: datetime, end_date: datetime,
                             max_lag: int = 2, top_n: int = 10,
                             min_significance: float = None, debug: bool = False) -> pd.DataFrame:
        """
        Find the top correlations across all lag periods.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            max_lag: Maximum lag days to test (default 2)
            top_n: Number of top correlations to return (default 10)
            min_significance: Maximum p-value to consider (None = auto-adjust based on sample size)
            debug: If True, print debug information

        Returns:
            DataFrame with top correlations sorted by absolute correlation strength
        """
        all_results = []

        # Test each lag period
        for lag in range(max_lag + 1):
            lag_results = self.analyze_macro_whoop_correlations(start_date, end_date, lag, debug=debug)
            if not lag_results.empty:
                all_results.append(lag_results)

        if not all_results:
            if debug:
                print("[DEBUG] No correlation results found across any lag period")
            return pd.DataFrame()

        # Combine all lag periods
        combined_df = pd.concat(all_results, ignore_index=True)

        if debug:
            print(f"\n[DEBUG] find_top_correlations:")
            print(f"  Total correlations tested: {len(combined_df)}")
            print(f"  Non-null correlations: {combined_df['correlation'].notna().sum()}")

        # Auto-adjust significance threshold based on sample size
        if min_significance is None:
            sample_sizes = combined_df['n'].dropna()
            if len(sample_sizes) > 0:
                avg_n = sample_sizes.mean()
                if avg_n < 10:
                    min_significance = 0.15  # Very lenient for small samples
                elif avg_n < 15:
                    min_significance = 0.10  # Moderate for medium samples
                else:
                    min_significance = 0.05  # Strict for large samples

                if debug:
                    print(f"  Average sample size: {avg_n:.1f}")
                    print(f"  Auto-adjusted significance threshold: {min_significance}")
            else:
                min_significance = 0.10  # Default fallback

        # Filter by significance (only keep those below threshold)
        significant_df = combined_df[combined_df["p_value"] <= min_significance].copy()

        if debug:
            print(f"  Significant correlations (p<={min_significance}): {len(significant_df)}")

        if significant_df.empty:
            if debug:
                print(f"  [!] No correlations met significance threshold p<={min_significance}")
                print(f"  Showing top correlations regardless of significance...")
            # If no significant correlations, return top ones anyway with warning
            combined_df_clean = combined_df[combined_df['correlation'].notna()].copy()
            if combined_df_clean.empty:
                return pd.DataFrame()
            combined_df_clean['abs_correlation'] = combined_df_clean['correlation'].abs()
            top_df = combined_df_clean.nlargest(top_n, 'abs_correlation')
            top_df = top_df.drop(columns=['abs_correlation'])
            return top_df

        # Sort by absolute correlation strength
        significant_df["abs_correlation"] = significant_df["correlation"].abs()
        top_df = significant_df.nlargest(top_n, "abs_correlation")

        # Drop helper column
        top_df = top_df.drop(columns=["abs_correlation"])

        return top_df

    def get_correlation_matrix(self, start_date: datetime, end_date: datetime,
                               lag_days: int = 0) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Create correlation and p-value matrices for heatmap visualization.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            lag_days: Number of days to lag nutrition data

        Returns:
            Tuple of (correlation_matrix, p_value_matrix)
        """
        # Get unified dataset
        unified_df = self.bridge.create_unified_dataset(start_date, end_date, lag_days)

        if unified_df.empty:
            return pd.DataFrame(), pd.DataFrame()

        # Nutrition variables (rows) - Use only base macros for heatmap to keep it readable
        nutrition_vars = ["total_kcal", "total_protein", "total_carbs", "total_fat", "total_fiber",
                         "combined_protein_and_carbs", "protein_per_gram_of_carbs",
                         "percent_calories_from_protein", "percent_calories_from_carbs"]

        # WHOOP variables (columns)
        whoop_vars = ["recovery_score", "hrv", "strain", "sleep_performance", "sleep_duration_min"]

        # Filter to only available columns
        nutrition_vars = [v for v in nutrition_vars if v in unified_df.columns]
        whoop_vars = [v for v in whoop_vars if v in unified_df.columns]

        # Initialize matrices
        corr_matrix = pd.DataFrame(index=nutrition_vars, columns=whoop_vars, dtype=float)
        p_value_matrix = pd.DataFrame(index=nutrition_vars, columns=whoop_vars, dtype=float)

        # Calculate correlations
        for nutrition_var in nutrition_vars:
            for whoop_var in whoop_vars:
                result = self.calculate_correlation(
                    unified_df[nutrition_var],
                    unified_df[whoop_var]
                )
                corr_matrix.loc[nutrition_var, whoop_var] = result["r"]
                p_value_matrix.loc[nutrition_var, whoop_var] = result["p_value"]

        return corr_matrix, p_value_matrix

    def analyze_individual_metric(self, nutrition_metric: str, whoop_metric: str,
                                   start_date: datetime, end_date: datetime,
                                   lag_days: int = 0) -> Dict:
        """
        Deep dive analysis of a specific nutrition-WHOOP metric pair.

        Args:
            nutrition_metric: Nutrition variable (e.g., "total_protein")
            whoop_metric: WHOOP variable (e.g., "recovery_score")
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            lag_days: Number of days to lag nutrition data

        Returns:
            Dict with correlation stats, data points, and insights
        """
        # Get unified dataset
        unified_df = self.bridge.create_unified_dataset(start_date, end_date, lag_days)

        if unified_df.empty or nutrition_metric not in unified_df.columns or whoop_metric not in unified_df.columns:
            return {}

        x = unified_df[nutrition_metric]
        y = unified_df[whoop_metric]

        # Calculate correlation
        corr_result = self.calculate_correlation(x, y)

        # Calculate quartile analysis
        # Divide nutrition into quartiles and see average WHOOP metric per quartile
        mask = ~(x.isna() | y.isna())
        x_clean = x[mask]
        y_clean = y[mask]

        if len(x_clean) < 4:
            quartile_analysis = None
        else:
            quartiles = pd.qcut(x_clean, q=4, labels=["Q1 (Low)", "Q2", "Q3", "Q4 (High)"], duplicates='drop')
            quartile_df = pd.DataFrame({"quartile": quartiles, "value": y_clean})
            quartile_means = quartile_df.groupby("quartile")["value"].mean()
            quartile_analysis = quartile_means.to_dict()

        return {
            "nutrition_metric": nutrition_metric,
            "whoop_metric": whoop_metric,
            "lag_days": lag_days,
            "correlation": corr_result["r"],
            "p_value": corr_result["p_value"],
            "n": corr_result["n"],
            "effect_size": corr_result["effect_size"],
            "significant": corr_result["significant"],
            "quartile_analysis": quartile_analysis,
            "nutrition_mean": x_clean.mean(),
            "nutrition_std": x_clean.std(),
            "whoop_mean": y_clean.mean(),
            "whoop_std": y_clean.std(),
        }

    def analyze_strain_controlled_correlations(self, start_date: datetime, end_date: datetime,
                                               lag_days: int = 0, debug: bool = False) -> pd.DataFrame:
        """
        Analyze correlations controlling for strain (partial correlations).

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            lag_days: Number of days to lag nutrition data
            debug: If True, print debug information

        Returns:
            DataFrame with both raw and strain-controlled correlations
        """
        unified_df = self.bridge.create_unified_dataset(start_date, end_date, lag_days)

        if unified_df.empty or 'strain' not in unified_df.columns:
            return pd.DataFrame()

        # Nutrition variables to test
        nutrition_vars = [
            "total_kcal", "total_protein", "total_carbs", "total_fat", "total_fiber",
            "combined_protein_and_carbs", "protein_times_carbs", "protein_per_gram_of_carbs",
            "protein_grams_per_100_calories", "percent_calories_from_protein"
        ]

        # WHOOP variables to test (excluding strain since it's the control variable)
        whoop_vars = ["recovery_score", "hrv", "rhr", "sleep_performance"]

        results = []

        for nutrition_var in nutrition_vars:
            if nutrition_var not in unified_df.columns:
                continue

            for whoop_var in whoop_vars:
                if whoop_var not in unified_df.columns:
                    continue

                # Calculate raw correlation
                raw_corr = self.calculate_correlation(
                    unified_df[nutrition_var],
                    unified_df[whoop_var],
                    debug=False
                )

                # Calculate strain-controlled partial correlation
                partial_corr = self.calculate_partial_correlation(
                    unified_df[nutrition_var],
                    unified_df[whoop_var],
                    unified_df['strain'],
                    debug=debug
                )

                results.append({
                    "nutrition_metric": nutrition_var,
                    "whoop_metric": whoop_var,
                    "lag_days": lag_days,
                    "raw_correlation": raw_corr["r"],
                    "raw_p_value": raw_corr["p_value"],
                    "controlled_correlation": partial_corr["r"],
                    "controlled_p_value": partial_corr["p_value"],
                    "n": partial_corr["n"],
                    "effect_size": partial_corr["effect_size"],
                    "significant": partial_corr["significant"],
                    "strain_effect": abs(raw_corr["r"] - partial_corr["r"]) if raw_corr["r"] is not None and partial_corr["r"] is not None else None
                })

        return pd.DataFrame(results)

    def analyze_stratified_by_strain(self, start_date: datetime, end_date: datetime,
                                     lag_days: int = 0, debug: bool = False) -> Dict:
        """
        Analyze correlations stratified by strain level (high/medium/low).

        Tests if nutrition matters more on high-strain days vs low-strain days.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            lag_days: Number of days to lag nutrition data
            debug: If True, print debug information

        Returns:
            Dict with correlations for each strain group
        """
        unified_df = self.bridge.create_unified_dataset(start_date, end_date, lag_days)

        if unified_df.empty or 'strain' not in unified_df.columns:
            return {}

        # Split into tertiles (low/medium/high strain)
        unified_df['strain_group'] = pd.qcut(unified_df['strain'], q=3, labels=['low', 'medium', 'high'], duplicates='drop')

        # Nutrition variables to test
        nutrition_vars = ["total_protein", "total_carbs", "total_kcal", "combined_protein_and_carbs"]

        # WHOOP variables to test
        whoop_vars = ["recovery_score", "hrv", "sleep_performance"]

        results = {
            'low': [],
            'medium': [],
            'high': []
        }

        for strain_group in ['low', 'medium', 'high']:
            group_df = unified_df[unified_df['strain_group'] == strain_group]

            if len(group_df) < 3:
                continue

            for nutrition_var in nutrition_vars:
                if nutrition_var not in group_df.columns:
                    continue

                for whoop_var in whoop_vars:
                    if whoop_var not in group_df.columns:
                        continue

                    corr_result = self.calculate_correlation(
                        group_df[nutrition_var],
                        group_df[whoop_var],
                        debug=False
                    )

                    if corr_result["r"] is not None:
                        results[strain_group].append({
                            "nutrition_metric": nutrition_var,
                            "whoop_metric": whoop_var,
                            "correlation": corr_result["r"],
                            "p_value": corr_result["p_value"],
                            "n": corr_result["n"],
                            "effect_size": corr_result["effect_size"],
                            "significant": corr_result["significant"]
                        })

        # Convert to DataFrames
        for group in results:
            results[group] = pd.DataFrame(results[group])

        return results

    def analyze_interaction_effects(self, start_date: datetime, end_date: datetime,
                                   lag_days: int = 0, debug: bool = False) -> pd.DataFrame:
        """
        Analyze interaction effects: when does nutrition matter MORE?

        Tests 5 interaction types:
        1. Strain x Nutrition -> Does protein help more on high-strain days?
        2. SleepDebt x Nutrition -> Does nutrition matter more when sleep-deprived?
        3. Recovery x Nutrition -> Does nutrition help more on low-recovery days?
        4. HRV x Nutrition -> Does nutrition impact vary with HRV?
        5. CaloriesBurned x Nutrition -> Does nutrition matter more on high-burn days?

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            lag_days: Number of days to lag nutrition data
            debug: If True, print debug information

        Returns:
            DataFrame with interaction effect results
        """
        unified_df = self.bridge.create_unified_dataset(start_date, end_date, lag_days)

        if unified_df.empty:
            return pd.DataFrame()

        results = []

        # Define interaction tests
        interactions = [
            {
                "moderator": "strain",
                "moderator_label": "Strain",
                "nutrition_vars": ["total_protein", "total_carbs", "combined_protein_and_carbs"],
                "outcome_vars": ["recovery_score", "hrv"],
                "interpretation": "Does nutrition help more on high-strain days?"
            },
            {
                "moderator": "sleep_debt_min",
                "moderator_label": "Sleep Debt",
                "nutrition_vars": ["total_protein", "total_carbs"],
                "outcome_vars": ["recovery_score", "sleep_performance"],
                "interpretation": "Does nutrition matter more when sleep-deprived?"
            },
            {
                "moderator": "recovery_score",
                "moderator_label": "Recovery",
                "nutrition_vars": ["total_protein", "total_kcal", "combined_protein_and_carbs"],
                "outcome_vars": ["hrv", "strain"],
                "interpretation": "Does nutrition help more on low-recovery days?"
            },
            {
                "moderator": "hrv",
                "moderator_label": "HRV",
                "nutrition_vars": ["total_protein", "total_carbs"],
                "outcome_vars": ["recovery_score", "strain"],
                "interpretation": "Does nutrition impact vary with HRV?"
            },
            {
                "moderator": "calories_burned",
                "moderator_label": "Calories Burned",
                "nutrition_vars": ["total_kcal", "total_protein", "total_carbs"],
                "outcome_vars": ["recovery_score", "hrv"],
                "interpretation": "Does nutrition matter more on high-burn days?"
            }
        ]

        for interaction in interactions:
            moderator = interaction["moderator"]

            if moderator not in unified_df.columns:
                continue

            for nutrition_var in interaction["nutrition_vars"]:
                if nutrition_var not in unified_df.columns:
                    continue

                for outcome_var in interaction["outcome_vars"]:
                    if outcome_var not in unified_df.columns or outcome_var == moderator:
                        continue

                    # Create interaction term (nutrition * moderator)
                    interaction_term = unified_df[nutrition_var] * unified_df[moderator]

                    # Test if interaction term correlates with outcome
                    # High correlation means the effect of nutrition depends on the moderator
                    corr_result = self.calculate_correlation(
                        interaction_term,
                        unified_df[outcome_var],
                        debug=False
                    )

                    # Also calculate partial correlation controlling for main effects
                    # This isolates the pure interaction effect
                    mask = ~(interaction_term.isna() | unified_df[outcome_var].isna() |
                            unified_df[nutrition_var].isna() | unified_df[moderator].isna())

                    if mask.sum() >= 3:
                        results.append({
                            "interaction_type": f"{interaction['moderator_label']} x Nutrition",
                            "moderator": moderator,
                            "nutrition_metric": nutrition_var,
                            "outcome_metric": outcome_var,
                            "interaction_correlation": corr_result["r"],
                            "p_value": corr_result["p_value"],
                            "n": corr_result["n"],
                            "effect_size": corr_result["effect_size"],
                            "significant": corr_result["significant"],
                            "interpretation": interaction["interpretation"]
                        })

        return pd.DataFrame(results)

    def get_insights_summary(self, start_date: datetime, end_date: datetime,
                            max_lag: int = 2) -> Dict:
        """
        Get high-level insights summary for display.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            max_lag: Maximum lag days to test

        Returns:
            Dict with summary insights
        """
        # Get data availability
        availability = self.bridge.get_data_availability(start_date, end_date)

        # Get top correlations
        top_correlations = self.find_top_correlations(start_date, end_date, max_lag, top_n=5)

        # Get macro and WHOOP summaries
        macro_summary = self.bridge.get_macros_summary(start_date, end_date)
        whoop_summary = self.bridge.get_whoop_summary(start_date, end_date)

        # Extract top 3 positive and negative correlations
        if not top_correlations.empty:
            positive_corr = top_correlations[top_correlations["correlation"] > 0].head(3)
            negative_corr = top_correlations[top_correlations["correlation"] < 0].head(3)
        else:
            positive_corr = pd.DataFrame()
            negative_corr = pd.DataFrame()

        return {
            "data_availability": availability,
            "macro_summary": macro_summary,
            "whoop_summary": whoop_summary,
            "top_positive_correlations": positive_corr.to_dict('records') if not positive_corr.empty else [],
            "top_negative_correlations": negative_corr.to_dict('records') if not negative_corr.empty else [],
            "total_correlations_tested": len(top_correlations),
        }
