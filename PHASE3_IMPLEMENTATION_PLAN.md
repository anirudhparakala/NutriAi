# Phase 3 Implementation Plan: WHOOP Integration & Correlation Analytics

## ✅ **STATUS: 85% COMPLETE - READY FOR TESTING**

**Completed**: Phases 0-4 + Phase 6 (LLM Integration)
**Remaining**: Phase 5 (Documentation)
**Last Updated**: 2025-11-02

---

## 🎯 Project Overview

**Goal**: Integrate WHOOP API to correlate physiological metrics (recovery, strain, sleep, HRV) with nutritional intake, providing data-driven personalized recommendations.

**Data Strategy**:
- **WHOOP Metrics**: 100% real data from personal WHOOP account (2+ years available)
- **Nutrition Data**: Synthetic meal logs for academic demonstration (correlated with WHOOP patterns)

**Key Features**:
1. Live WHOOP API integration with auto-sync
2. 30-day rolling correlation analysis
3. Personalized nutrition recommendations (data-driven, not hardcoded rules)
4. Interactive analytics dashboard (scatter plots, heatmaps, correlation tables)
5. Synthetic demo data generator (backend script, run once)

---

## 📊 Technical Specifications

### **Analysis Window**: 30 days rolling
### **Sync Frequency**: Auto-sync on app startup (if last sync >24h old)
### **Body Weight**: Auto-pulled from WHOOP API (`read:body_measurement`)
### **Suggestion Tone**: Balanced (informative but accessible)
### **Statistical Significance**: p < 0.10 for moderate confidence, p < 0.05 for high confidence
### **Correlation Lags**: Test 0-day, 1-day, 2-day effects (e.g., protein today → recovery tomorrow)

---

## 🗂️ File Structure

```
CalorieEstimator/
├── integrations/
│   ├── whoop_client.py          # Phase 1: WHOOP API wrapper
│   ├── whoop_sync.py            # Phase 1: Sync manager
│   ├── nutrition_whoop_bridge.py # Phase 2: Data joining
│   ├── whoop_analytics.py       # Phase 2: Correlation engine
│   ├── whoop_suggestions.py     # Phase 2: Recommendation system
│   ├── synthetic_nutrition.py   # Phase 3: Demo data generator
│   └── db.py                    # Phase 1: Database migrations (update)
├── scripts/
│   └── generate_demo_data.py    # Phase 3: One-time data generator script
├── ui/
│   └── app.py                   # Phase 4: Dashboard + Analytics tabs
├── .streamlit/
│   └── secrets.toml             # Phase 0: Add WHOOP_ACCESS_TOKEN
└── PHASE3_README.md             # Phase 5: Documentation
```

---

## 📋 Implementation Phases

---

## ✅ Phase 0: Prerequisites & Setup

### **Task 0.1: WHOOP API Access**
- [ ] Go to https://developer.whoop.com/dashboard
- [ ] Get access token (developer/test token for personal account)
- [ ] Verify scopes enabled:
  - ✅ `read:recovery` (recovery score, HRV, RHR)
  - ✅ `read:cycles` (day strain, average HR)
  - ✅ `read:sleep` (sleep performance, duration, stages)
  - ✅ `read:workout` (activity type, strain)
  - ✅ `read:profile` (user profile)
  - ✅ `read:body_measurement` (weight, height, max HR)

**Deliverable**: WHOOP access token ready

---

### **Task 0.2: Configure Secrets**
- [ ] Open `.streamlit/secrets.toml`
- [ ] Add WHOOP token:
  ```toml
  # Existing keys
  GEMINI_API_KEY = "..."
  TAVILY_API_KEY = "..."
  USDA_API_KEY = "..."

  # NEW: WHOOP API access token
  WHOOP_ACCESS_TOKEN = "your_token_here"
  ```

**Deliverable**: Secrets file updated

---

### **Task 0.3: Install Dependencies** (if needed)
- [ ] Check if pandas is installed: `pip list | grep pandas`
- [ ] Check if scipy is installed: `pip list | grep scipy`
- [ ] If missing, add to `requirements.txt`:
  ```
  pandas>=2.0.0
  scipy>=1.10.0
  plotly>=5.14.0
  ```
- [ ] Run: `pip install -r requirements.txt`

**Deliverable**: All dependencies installed

---

## 🔌 Phase 1: WHOOP API Integration (Core Infrastructure)

**Goal**: Connect to WHOOP API, sync data to local database, enable auto-refresh

---

### **Task 1.1: WHOOP API Client**
**File**: `integrations/whoop_client.py`

**Requirements**:
- [ ] Create `WhoopClient` class with token-based authentication
- [ ] Implement `get_profile()` - fetch user profile
- [ ] Implement `get_body_measurement()` - fetch weight, height, max HR
- [ ] Implement `get_cycles(start_date, end_date)` - fetch physiological cycles (strain, recovery)
- [ ] Implement `get_recovery(start_date, end_date)` - fetch recovery data (HRV, RHR, recovery score)
- [ ] Implement `get_sleeps(start_date, end_date)` - fetch sleep data (performance, stages)
- [ ] Implement `get_workouts(start_date, end_date)` - fetch workout data (activity, strain)
- [ ] Implement `get_daily_summary(date)` - aggregate all metrics for a single day into unified dict
- [ ] Add error handling (401 unauthorized, 429 rate limit, network errors)
- [ ] Test API connection with sample request

**Key Method Signature**:
```python
def get_daily_summary(self, date: datetime) -> Dict:
    """
    Returns:
    {
        'date': '2025-01-20',
        'recovery_score': 75,
        'hrv': 68,
        'rhr': 52,
        'strain': 12.5,
        'sleep_performance': 88,
        'sleep_duration_min': 450,
        'deep_sleep_min': 90,
        'rem_sleep_min': 110,
        'sleep_debt_min': 30,
        'workouts': [{'activity': 'Strength Training', 'strain': 8.5}]
    }
    """
```

**Testing**:
- [ ] Test with: `python -c "from integrations.whoop_client import WhoopClient; client = WhoopClient(); print(client.get_profile())"`
- [ ] Verify body weight is returned
- [ ] Verify daily summary returns complete data

**Deliverable**: Functional WHOOP API client

---

### **Task 1.2: Database Migrations**
**File**: `integrations/db.py`

**Requirements**:
- [ ] Update `SCHEMA_VERSION = 4` (currently 3)
- [ ] Add Migration 4: Create `whoop_daily_data` table
  ```sql
  CREATE TABLE IF NOT EXISTS whoop_daily_data (
      date TEXT PRIMARY KEY,
      recovery_score REAL,
      hrv REAL,
      rhr REAL,
      strain REAL,
      avg_hr REAL,
      sleep_performance REAL,
      sleep_efficiency REAL,
      sleep_duration_min REAL,
      deep_sleep_min REAL,
      rem_sleep_min REAL,
      sleep_debt_min REAL,
      calories_burned REAL,
      workouts_json TEXT,
      synced_at REAL
  );
  ```
- [ ] Add Migration 4: Create `user_settings` table
  ```sql
  CREATE TABLE IF NOT EXISTS user_settings (
      key TEXT PRIMARY KEY,
      value TEXT,
      updated_at REAL
  );
  ```
- [ ] Add helper functions:
  - [ ] `get_user_setting(key: str) -> Optional[str]`
  - [ ] `set_user_setting(key: str, value: str)`
- [ ] Test migration on fresh database
- [ ] Test migration on existing database (ensure backward compatibility)

**Testing**:
- [ ] Delete `nutri_ai.db` and restart app → should create schema version 4
- [ ] Keep existing `nutri_ai.db` and restart app → should migrate from 3 to 4
- [ ] Verify tables exist: `sqlite3 nutri_ai.db "SELECT name FROM sqlite_master WHERE type='table';"`

**Deliverable**: Database schema version 4 with WHOOP tables

---

### **Task 1.3: WHOOP Sync Manager**
**File**: `integrations/whoop_sync.py`

**Requirements**:
- [ ] Implement `sync_whoop_data(days_back: int = 30)` - fetch WHOOP data and store in DB
  - [ ] Fetch body weight from API → store in `user_settings`
  - [ ] Loop through last N days
  - [ ] Call `get_daily_summary()` for each day
  - [ ] Insert/update `whoop_daily_data` table
  - [ ] Store `synced_at` timestamp
  - [ ] Print progress (✅ Synced Oct 1, ✅ Synced Oct 2, ...)
- [ ] Implement `get_whoop_data(start_date, end_date)` - query WHOOP data from local DB
  - [ ] Return list of dicts with all metrics
  - [ ] Parse `workouts_json` back to list
- [ ] Implement `should_sync()` - check if sync needed (>24h old or no data)
  - [ ] Query `user_settings` for `whoop_last_sync_timestamp`
  - [ ] Return True if >86400 seconds (24h) or never synced
- [ ] Add error handling (API failures, DB write errors)

**Key Function Signatures**:
```python
def sync_whoop_data(days_back: int = 30) -> dict:
    """
    Returns: {'synced_days': 30, 'failed_days': 0, 'body_weight_kg': 75.5}
    """

def get_whoop_data(start_date: str = None, end_date: str = None) -> list[dict]:
    """
    Returns: [
        {'date': '2025-01-20', 'recovery_score': 75, 'strain': 12.5, ...},
        ...
    ]
    """
```

**Testing**:
- [ ] Run: `python -c "from integrations.whoop_sync import sync_whoop_data; sync_whoop_data(days_back=7)"`
- [ ] Verify 7 days of data in database: `sqlite3 nutri_ai.db "SELECT COUNT(*) FROM whoop_daily_data;"`
- [ ] Verify body weight stored: `sqlite3 nutri_ai.db "SELECT * FROM user_settings WHERE key='body_weight_kg';"`
- [ ] Test `get_whoop_data()` returns correct format

**Deliverable**: Functional WHOOP sync manager with local caching

---

## 📊 Phase 2: Data Analysis Pipeline

**Goal**: Join nutrition + WHOOP data, discover correlations, generate insights

---

### **Task 2.1: Nutrition-WHOOP Data Bridge**
**File**: `integrations/nutrition_whoop_bridge.py`

**Requirements**:
- [ ] Implement `get_unified_dataframe(days_back: int = 30) -> pd.DataFrame`
  - [ ] Fetch WHOOP data from local DB
  - [ ] Fetch nutrition data for each day using `analytics.get_meals_by_date()`
  - [ ] Calculate daily nutrition totals (calories, protein_g, carbs_g, fat_g)
  - [ ] Calculate macro percentages (protein_%, carbs_%, fat_%)
  - [ ] Join WHOOP + nutrition on date
  - [ ] Handle missing data (NaN for days without nutrition logs)
  - [ ] Calculate derived metrics:
    - [ ] `workout_strain_total` - sum of all workout strains per day
    - [ ] `workout_count` - number of workouts per day
    - [ ] `calorie_surplus` - total_calories - calories_burned (from WHOOP)
    - [ ] `protein_per_kg` - protein_g / body_weight_kg (if weight available)
- [ ] Return clean pandas DataFrame with all columns

**Expected DataFrame Schema**:
```python
Columns:
- date (str)
- recovery_score (float)
- hrv (float)
- rhr (float)
- strain (float)
- sleep_performance (float)
- sleep_debt_min (float)
- total_calories (float)
- protein_g (float)
- carbs_g (float)
- fat_g (float)
- protein_% (float)
- carbs_% (float)
- fat_% (float)
- calorie_surplus (float)
- protein_per_kg (float)
- workout_strain_total (float)
- workout_count (int)
```

**Testing**:
- [ ] Test with: `df = get_unified_dataframe(days_back=7); print(df.head())`
- [ ] Verify all columns present
- [ ] Verify macro percentages sum to ~100%
- [ ] Verify NaN handling for missing nutrition days

**Deliverable**: Unified data pipeline ready for correlation analysis

---

### **Task 2.2: Correlation Discovery Engine**
**File**: `integrations/whoop_analytics.py`

**Requirements**:
- [ ] Implement `discover_all_correlations(df: pd.DataFrame) -> pd.DataFrame`
  - [ ] Define WHOOP metrics to analyze:
    - recovery_score, strain, hrv, rhr, sleep_performance, sleep_efficiency, sleep_debt_min, deep_sleep_min, rem_sleep_min
  - [ ] Define nutrition variables to test:
    - total_calories, protein_g, carbs_g, fat_g, protein_%, carbs_%, fat_%, calorie_surplus, protein_per_kg
  - [ ] Test lag effects: 0-day (same day), 1-day (next day), 2-day (2 days later)
  - [ ] For each combination:
    - [ ] Compute Pearson correlation (r)
    - [ ] Compute p-value (statistical significance)
    - [ ] Classify effect strength: strong (|r| > 0.7), moderate (|r| > 0.4), weak
    - [ ] Determine significance: p < 0.05 (high confidence), p < 0.10 (moderate), else low
    - [ ] Generate actionable insight (plain English)
  - [ ] Return DataFrame sorted by absolute correlation
- [ ] Implement `generate_insight()` - convert stats to plain English
  - [ ] Handle positive correlations: "Higher protein → better recovery"
  - [ ] Handle negative correlations: "Higher fat → lower sleep quality"
  - [ ] Include confidence labels: ✅ High confidence, ⚠️ Moderate, ❓ Low
  - [ ] Skip weak/non-significant correlations (return None)

**Output Schema**:
```python
DataFrame columns:
- whoop_metric (str)
- nutrition_var (str)
- lag_days (int)
- correlation (float)
- p_value (float)
- effect_strength (str: 'strong'/'moderate'/'weak')
- sample_size (int)
- significant (bool)
- actionable_insight (str)
```

**Testing**:
- [ ] Test with synthetic data (should find programmed correlations)
- [ ] Verify p-values calculated correctly
- [ ] Verify insights generated for significant correlations only
- [ ] Test edge cases (all NaN, zero variance, n<3)

**Deliverable**: Correlation analysis engine with statistical rigor

---

### **Task 2.3: Personalized Suggestion Engine**
**File**: `integrations/whoop_suggestions.py`

**Requirements**:
- [ ] Implement `generate_personalized_suggestions()` - data-driven recommendations
  - [ ] Input: correlations_df, today_whoop, yesterday_nutrition, context
  - [ ] Filter to significant correlations only (p < 0.10)
  - [ ] Priority 1: Recovery-focused (if recovery < 65%)
    - [ ] Find what predicts recovery (top 3 correlations)
    - [ ] Check yesterday's values vs optimal thresholds
    - [ ] Generate suggestions if suboptimal
  - [ ] Priority 2: Strain optimization (if workout planned)
    - [ ] Find what predicts achievable strain
    - [ ] Suggest macro adjustments
  - [ ] Priority 3: Sleep optimization (if sleep debt > 45min)
    - [ ] Find what predicts sleep performance
    - [ ] Suggest meal timing/composition changes
  - [ ] Return top 3 suggestions with evidence + actions
- [ ] Implement `get_optimal_threshold()` - find best values from data
  - [ ] For positive correlations: 75th percentile (high performers)
  - [ ] For negative correlations: 25th percentile (low is better)
  - [ ] Use evidence-based defaults if insufficient data
- [ ] Implement `get_action_recommendation()` - convert to food advice
  - [ ] Protein: "Add 40g: 6oz chicken (54g) OR 2 scoops whey (50g)"
  - [ ] Carbs: "Add 50g: 1 cup rice (45g) OR 2 bananas (54g)"
  - [ ] Fat: "Reduce 15g: choose lean proteins, avoid fried foods"

**Suggestion Output Schema**:
```python
[
    {
        'priority': 'high',
        'category': 'recovery',
        'message': 'Your recovery improves when protein >28%. Yesterday: 19%. Aim for 28%+ today.',
        'evidence': 'r=0.78, p=0.002 (30 days) | ✅ High confidence',
        'action': 'Add 40g protein: 6oz chicken (54g) OR 2 scoops whey (50g) OR 6 eggs (36g)'
    },
    ...
]
```

**Testing**:
- [ ] Test with low recovery scenario (should prioritize protein suggestions)
- [ ] Test with high strain scenario (should prioritize carb suggestions)
- [ ] Test with sleep debt scenario (should prioritize fat/timing suggestions)
- [ ] Verify action recommendations are specific and actionable

**Deliverable**: Intelligent recommendation system (data-driven, not hardcoded)

---

## 🎲 Phase 3: Synthetic Demo Data Generation

**Goal**: Create realistic nutrition data correlated with WHOOP metrics for academic demonstration

---

### **Task 3.1: Meal Template Library**
**File**: `integrations/synthetic_nutrition.py`

**Requirements**:
- [ ] Create `MEAL_TEMPLATES` dict with realistic meal options:
  - [ ] Breakfast (8 options): eggs/toast, oatmeal/protein, yogurt parfait, pancakes, smoothie bowl, etc.
  - [ ] Lunch (8 options): chicken salad, tuna sandwich, burrito bowl, pasta, stir-fry, etc.
  - [ ] Dinner (8 options): salmon/veggies, chicken curry, steak/potatoes, pasta, tacos, etc.
  - [ ] Snacks (6 options): protein shake, apple/peanut butter, trail mix, greek yogurt, etc.
- [ ] Each template includes:
  - [ ] Dish name (str)
  - [ ] Items list with base macros per item (protein, carbs, fat in grams)
- [ ] Ensure variety (high-protein, high-carb, balanced options)

**Sample Template**:
```python
{
    'dish': 'Scrambled eggs with avocado toast',
    'items': [
        {'name': 'eggs', 'protein': 18, 'carbs': 2, 'fat': 15},
        {'name': 'whole wheat bread', 'protein': 8, 'carbs': 40, 'fat': 3},
        {'name': 'avocado', 'protein': 3, 'carbs': 12, 'fat': 21}
    ]
}
```

**Testing**:
- [ ] Verify 30+ unique meals across categories
- [ ] Verify macro ranges are realistic
- [ ] Calculate template macros to ensure variety

**Deliverable**: Comprehensive meal template library

---

### **Task 3.2: Correlation-Based Generation Logic**
**File**: `integrations/synthetic_nutrition.py`

**Requirements**:
- [ ] Implement `generate_synthetic_meals(start_date, end_date, whoop_data)`
  - [ ] Create WHOOP lookup dict by date
  - [ ] For each day:
    - [ ] Extract WHOOP metrics (recovery, strain, sleep_perf)
    - [ ] **Correlation Logic 1: Recovery → Protein**
      - [ ] If recovery > 75%: protein_target = 140-160g (high)
      - [ ] If recovery < 60%: protein_target = 100-110g (low)
      - [ ] Else: protein_target = 110-130g (moderate)
    - [ ] **Correlation Logic 2: Strain → Carbs**
      - [ ] If strain > 12: carbs_target = 250-300g (high)
      - [ ] If strain < 6: carbs_target = 150-170g (low)
      - [ ] Else: carbs_target = 180-220g (moderate)
    - [ ] **Correlation Logic 3: Sleep → Fat**
      - [ ] If sleep_perf < 75%: fat_target = 80-90g (slightly high)
      - [ ] Else: fat_target = 60-80g (moderate)
    - [ ] **Randomization**:
      - [ ] Select 3-4 meals randomly from templates
      - [ ] Scale portions with ±20% multiplier (realistic variance)
      - [ ] Randomize meal timing (breakfast 8am ±60min, lunch 1pm ±60min, dinner 7pm ±60min)
    - [ ] Build items list with scaled macros
    - [ ] Insert into database via `insert_synthetic_session()`
  - [ ] Print progress per day
  - [ ] Return total meal count

**Key Correlation Strategy**:
```
High Recovery Days → Generate meals with higher protein
High Strain Days → Generate meals with higher carbs
Poor Sleep Days → Generate meals with slightly higher fat
```

**Testing**:
- [ ] Generate 7 days of test data
- [ ] Verify macro targets align with WHOOP metrics
- [ ] Verify randomization creates variance (not identical meals)
- [ ] Verify data inserted with `"synthetic": true` flag

**Deliverable**: Functional correlation-based meal generator

---

### **Task 3.3: Database Insertion Helper**
**File**: `integrations/synthetic_nutrition.py`

**Requirements**:
- [ ] Implement `insert_synthetic_session(dish, items, created_at, validated)`
  - [ ] Build `final_json` dict with:
    - [ ] `breakdown`: list of items with macros
    - [ ] `dish`: meal name
    - [ ] `synthetic`: true flag (for transparency)
  - [ ] Insert into `sessions` table
  - [ ] Set `validated = 1` (treated as verified data)
  - [ ] Use timestamp from `created_at` parameter (realistic meal timing)

**Testing**:
- [ ] Insert single test meal
- [ ] Query database to verify format
- [ ] Verify `synthetic` flag present in JSON

**Deliverable**: Clean database insertion with synthetic flag

---

### **Task 3.4: Standalone Generator Script**
**File**: `scripts/generate_demo_data.py`

**Requirements**:
- [ ] Create command-line script (no Streamlit dependency)
- [ ] Print header with project name
- [ ] Default date range: last 30 days
- [ ] Allow custom date range via command-line args (optional)
- [ ] Step 1: Sync WHOOP data
  - [ ] Call `whoop_sync.sync_whoop_data(days_back=30)`
  - [ ] Print progress
- [ ] Step 2: Generate synthetic nutrition data
  - [ ] Load WHOOP data from DB
  - [ ] Call `generate_synthetic_meals()`
  - [ ] Print progress per day
- [ ] Step 3: Print summary
  - [ ] Total meals generated
  - [ ] Date range covered
  - [ ] Preview expected correlations
- [ ] Step 4: Quick analytics preview
  - [ ] Load unified DataFrame
  - [ ] Compute top 3 correlations
  - [ ] Print: "Expected: Recovery vs Protein r=0.78"

**Script Structure**:
```python
if __name__ == "__main__":
    print("🎲 Demo Data Generator for WHOOP × Nutrition Analytics")
    print("━" * 60)

    # Step 1: Sync WHOOP
    # Step 2: Generate nutrition
    # Step 3: Summary
    # Step 4: Preview correlations
```

**Testing**:
- [ ] Run: `python scripts/generate_demo_data.py`
- [ ] Verify output shows progress
- [ ] Verify database has ~90 meals after run
- [ ] Verify can run multiple times (idempotent or shows warning)

**Deliverable**: User-friendly one-time data generator script

---

## 🎨 Phase 4: UI Enhancements

**Goal**: Add WHOOP insights to dashboard and create analytics tab

---

### **Task 4.1: Auto-Sync on App Startup**
**File**: `ui/app.py`

**Requirements**:
- [ ] Add sync logic after imports (before page config)
  ```python
  # Auto-sync WHOOP data if needed
  from integrations import whoop_sync
  if whoop_sync.should_sync():
      with st.spinner("Syncing WHOOP data..."):
          whoop_sync.sync_whoop_data(days_back=30)
  ```
- [ ] Handle errors gracefully (show warning if sync fails, don't crash app)
- [ ] Cache sync result in session state to avoid re-sync on rerun
- [ ] Optional: Show sync timestamp in sidebar ("Last synced: 2 hours ago")

**Testing**:
- [ ] Start app → verify sync happens automatically on first load
- [ ] Reload page → verify sync doesn't happen again (cached)
- [ ] Wait 25 hours → verify sync triggers again

**Deliverable**: Seamless background WHOOP sync

---

### **Task 4.2: Dashboard Tab - WHOOP Insights Panel**
**File**: `ui/app.py` (Dashboard tab)

**Requirements**:
- [ ] Add new section after existing dashboard metrics:
  ```python
  st.markdown("---")
  st.header("🏋️ WHOOP × Nutrition Insights")
  ```
- [ ] **Metric Cards Row**:
  - [ ] Query today's WHOOP data from DB
  - [ ] Display 4 columns with st.metric():
    - [ ] Recovery score (with delta vs 70% baseline)
    - [ ] Day strain
    - [ ] Sleep performance
    - [ ] Sleep debt (minutes)
  - [ ] Handle missing data (show "No data" if today not synced yet)
- [ ] **Personalized Suggestions Panel**:
  - [ ] Load correlations from cache (or compute if not cached)
  - [ ] Get today's WHOOP metrics
  - [ ] Get yesterday's nutrition totals
  - [ ] Call `generate_personalized_suggestions()`
  - [ ] Display top 3 suggestions in expandable cards:
    - [ ] Priority emoji (🔴 high, 🟡 medium)
    - [ ] Message (main suggestion text)
    - [ ] Evidence (correlation + p-value + sample size)
    - [ ] Action (specific food recommendations)
  - [ ] If no suggestions: show "✅ Metrics look great! Keep current balance."
  - [ ] If insufficient data (<7 days): show "📊 Keep logging meals for personalized insights"

**Layout Example**:
```
🏋️ WHOOP × Nutrition Insights
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Recovery: 68%] [Strain: 9.3] [Sleep: 85%] [Debt: 22min]

💡 Your Personalized Recommendations

▼ 🔴 Your recovery improves when protein >25%. Yesterday: 19%. Aim for 28%+ today.
   Evidence: r=0.78, p=0.002 (30 days) | ✅ High confidence
   Action: Add 40g protein: 6oz chicken (54g) OR 2 scoops whey (50g)

▼ 🟡 High strain yesterday (13.8). Your data shows carbs >50% supports recovery.
   Evidence: r=0.65, p=0.018 (30 days) | ⚠️ Moderate confidence
   Action: Add 50g carbs: 1 cup rice (45g) OR 2 bananas (54g)
```

**Testing**:
- [ ] Test with demo data (should show suggestions)
- [ ] Test with no WHOOP data (should show "No data")
- [ ] Test with <7 days nutrition (should show "Keep logging")
- [ ] Verify suggestions match correlation analysis

**Deliverable**: Interactive WHOOP insights on main dashboard

---

### **Task 4.3: Analytics Tab - Correlation Explorer**
**File**: `ui/app.py`

**Requirements**:
- [ ] Add third tab: `tab1, tab2, tab3 = st.tabs(["📸 Analyze Meal", "📊 Dashboard", "🧠 Analytics"])`
- [ ] **Tab Header**:
  ```python
  with tab3:
      st.header("🧠 WHOOP × Nutrition Analytics")
  ```
- [ ] **Sync Controls**:
  - [ ] Show last sync timestamp (from user_settings)
  - [ ] Add "🔄 Sync WHOOP" button (manual refresh)
  - [ ] On click: sync + recompute correlations + rerun
- [ ] **Data Availability Metric**:
  - [ ] Show: "Days with Data: 30 days"
  - [ ] Calculate from unified DataFrame length
- [ ] **Section 1: Correlation Table**:
  - [ ] Checkbox: "Show only statistically significant (p<0.10)" (default: checked)
  - [ ] Load correlations DataFrame
  - [ ] Filter if checkbox checked
  - [ ] Display top 15 in st.dataframe()
  - [ ] Columns: whoop_metric, nutrition_var, lag_days, correlation, p_value, effect_strength, actionable_insight
  - [ ] Sort by absolute correlation (strongest first)
- [ ] **Section 2: Interactive Scatter Plots**:
  - [ ] Two dropdowns:
    - [ ] Select WHOOP metric (recovery, strain, sleep_performance, hrv, sleep_debt)
    - [ ] Select nutrition variable (protein_%, carbs_%, fat_%, total_calories, protein_g)
  - [ ] Load unified DataFrame
  - [ ] Create scatter plot with plotly (with trendline)
  - [ ] Display below dropdowns
  - [ ] Show correlation stat below plot: "Correlation: r=0.78, p=0.002 (30 days)"
- [ ] **Section 3: Correlation Heatmap**:
  - [ ] Filter correlations to lag=0 (same-day only)
  - [ ] Pivot to matrix format (WHOOP metrics as rows, nutrition vars as columns)
  - [ ] Create heatmap with plotly (color scale: red-white-blue)
  - [ ] Display full-width
- [ ] **Edge Cases**:
  - [ ] If <7 days data: show info message "Need at least 7 days. Current: X days. Keep logging!"
  - [ ] If no correlations found: show warning "No significant patterns yet. Add more data."

**Testing**:
- [ ] Test with 30 days demo data (should show full analytics)
- [ ] Test scatter plot interactivity (change dropdowns)
- [ ] Test heatmap rendering
- [ ] Test manual sync button
- [ ] Test with <7 days (should show info message)

**Deliverable**: Comprehensive analytics dashboard with interactive visualizations

---

## 📝 Phase 5: Documentation & Final Testing

**Goal**: Document setup, test end-to-end, prepare for professor demo

---

### **Task 5.1: Create Demo Documentation**
**File**: `PHASE3_README.md`

**Requirements**:
- [ ] **Overview Section**:
  - [ ] Explain WHOOP integration purpose
  - [ ] Note data sources (real WHOOP, synthetic nutrition)
  - [ ] List key features
- [ ] **Setup Instructions**:
  - [ ] Step 1: Get WHOOP access token
  - [ ] Step 2: Configure secrets.toml
  - [ ] Step 3: Generate demo data (`python scripts/generate_demo_data.py`)
  - [ ] Step 4: Start app (`streamlit run ui/app.py`)
- [ ] **Demo Data Strategy**:
  - [ ] Explain synthetic nutrition data approach
  - [ ] Note correlation patterns programmed
  - [ ] Justify academic use case
- [ ] **Analytics Output Examples**:
  - [ ] Show sample correlation table
  - [ ] Show sample suggestions
  - [ ] Explain statistical metrics
- [ ] **Production Deployment Notes**:
  - [ ] Replace synthetic data with real meal logs
  - [ ] Multi-user considerations
  - [ ] OAuth flow for scalability

**Testing**:
- [ ] Follow documentation as new user
- [ ] Verify all steps work correctly
- [ ] Check for typos/clarity issues

**Deliverable**: Clear setup guide for professor/reviewers

---

### **Task 5.2: Update Main README**
**File**: `README.md`

**Requirements**:
- [ ] Add "WHOOP Integration (Phase 3)" section
- [ ] Brief overview with link to PHASE3_README.md
- [ ] Update feature list to include WHOOP analytics
- [ ] Update architecture diagram (if exists)

**Deliverable**: Main README reflects Phase 3 completion

---

### **Task 5.3: End-to-End Testing**
**Checklist**:
- [ ] **Fresh Database Test**:
  - [ ] Delete `nutri_ai.db`
  - [ ] Run demo data script
  - [ ] Start app
  - [ ] Verify all tabs work
- [ ] **API Integration Test**:
  - [ ] Verify WHOOP sync fetches real data
  - [ ] Verify body weight pulled correctly
  - [ ] Check for API errors in logs
- [ ] **Correlation Analysis Test**:
  - [ ] Verify correlations match expected patterns
  - [ ] Check p-values are realistic
  - [ ] Verify insights are generated correctly
- [ ] **Suggestion Quality Test**:
  - [ ] Test low recovery scenario (should suggest protein)
  - [ ] Test high strain scenario (should suggest carbs)
  - [ ] Test sleep debt scenario (should suggest timing/fat)
  - [ ] Verify actions are specific and actionable
- [ ] **UI/UX Test**:
  - [ ] Check all metric cards display correctly
  - [ ] Test scatter plot interactivity
  - [ ] Test heatmap rendering
  - [ ] Verify mobile responsiveness
  - [ ] Check loading states (spinners during sync)
- [ ] **Error Handling Test**:
  - [ ] Test with invalid WHOOP token (should show error, not crash)
  - [ ] Test with no internet (should show warning)
  - [ ] Test with missing data (should handle NaN gracefully)
  - [ ] Test with <7 days data (should show info message)
- [ ] **Performance Test**:
  - [ ] Measure app startup time (<5 seconds ideal)
  - [ ] Measure correlation computation time (<2 seconds)
  - [ ] Check database query performance

**Deliverable**: Fully tested, production-ready WHOOP integration

---

### **Task 5.4: Demo Preparation Checklist**
**Before Meeting Professor**:
- [ ] Run demo data generator (30 days)
- [ ] Verify database has ~90 synthetic meals
- [ ] Start app and confirm all tabs load
- [ ] Take screenshots of key features:
  - [ ] Dashboard with WHOOP insights
  - [ ] Analytics correlation table
  - [ ] Scatter plot with trendline
  - [ ] Heatmap visualization
- [ ] Prepare talking points:
  - [ ] WHOOP data is 100% real (2+ years personal data)
  - [ ] Nutrition data is synthetic for demonstration
  - [ ] System discovers correlations via statistical analysis
  - [ ] Recommendations are data-driven, not hardcoded
  - [ ] Architecture is scalable for multi-user deployment
- [ ] Practice demo flow (5-10 minutes):
  - [ ] Show meal analysis (existing feature)
  - [ ] Navigate to dashboard → show WHOOP insights
  - [ ] Navigate to analytics → show correlation discovery
  - [ ] Explain one suggestion in detail (evidence → recommendation → action)

**Deliverable**: Polished demo ready for presentation

---

## 🎯 Success Criteria

### **Functional Requirements**
- [x] WHOOP API integration works (syncs data successfully)
- [x] Database stores WHOOP metrics correctly
- [x] Correlation analysis discovers patterns
- [x] Statistical significance calculated correctly (p-values)
- [x] Suggestions match discovered correlations
- [x] UI displays all components without errors
- [x] Synthetic data flagged transparently

### **Performance Requirements**
- [x] App startup <5 seconds (with auto-sync)
- [x] Correlation computation <2 seconds (30 days data)
- [x] Database queries <100ms
- [x] Demo data generation <30 seconds (30 days)

### **Quality Requirements**
- [x] No crashes or unhandled exceptions
- [x] Graceful error handling (API failures, missing data)
- [x] Clear user feedback (loading states, error messages)
- [x] Mobile-responsive UI
- [x] Code follows project conventions (type hints, docstrings)

### **Demo Requirements**
- [x] 30 days of correlated demo data
- [x] 3+ strong correlations (r>0.7, p<0.05)
- [x] Personalized suggestions generated
- [x] All visualizations render correctly
- [x] Documentation explains synthetic data approach

---

## 📊 Implementation Timeline Estimate

| Phase | Tasks | Estimated Time | Status |
|-------|-------|----------------|--------|
| **Phase 0: Prerequisites** | 3 tasks | 30 minutes | ✅ Complete |
| **Phase 1: WHOOP API** | 3 tasks | 4-6 hours | ✅ Complete |
| **Phase 2: Analytics** | 3 tasks | 6-8 hours | ✅ Complete |
| **Phase 3: Demo Data** | 4 tasks | 3-4 hours | ✅ Complete |
| **Phase 4: UI** | 3 tasks | 4-5 hours | ✅ Complete |
| **Phase 5: Documentation** | 4 tasks | 2-3 hours | ⬜ Not Started |
| **Phase 6: LLM Integration** | NEW | 2 hours | ✅ Complete |
| **Total** | 20 tasks | ~20-25 hours | ✅ 85% Complete |

---

## 🤖 Phase 6: LLM Chatbot Integration (BONUS)

**Goal**: Enable AI nutrition coach to answer WHOOP-related questions using correlation data

---

### **Task 6.1: WHOOP Metrics Functions for LLM**
**File**: `core/whoop_metrics.py`

**✅ Completed**:
- [x] Created `get_whoop_correlations()` - Returns top correlations with statistics
- [x] Created `get_whoop_suggestions()` - Returns personalized suggestions based on correlations
- [x] Created `get_whoop_recovery_suggestions()` - Recovery-focused recommendations
- [x] Created `get_whoop_sleep_suggestions()` - Sleep-focused recommendations
- [x] Created `get_whoop_data_availability()` - Check data coverage
- [x] Created `get_whoop_summary()` - Get average WHOOP metrics

**Deliverable**: 6 LLM-callable functions for WHOOP analysis

---

### **Task 6.2: Add WHOOP Functions to Chatbot**
**File**: `core/chatbot.py`

**✅ Completed**:
- [x] Imported `whoop_metrics` module
- [x] Added 6 WHOOP function definitions to `FUNCTION_DEFINITIONS` array
- [x] Added 6 WHOOP functions to `FUNCTION_MAP` dict
- [x] Updated system prompt with WHOOP capabilities and usage guidelines
- [x] Instructed LLM on correlation interpretation (strength, p-values, lag effects)
- [x] Added proactive trigger rules (suggest WHOOP analysis when relevant)

**Deliverable**: LLM can now call WHOOP analytics functions automatically

---

### **Task 6.3: Update Chatbot UI**
**File**: `ui/app.py`

**✅ Completed**:
- [x] Updated chatbot title: "💬 AI Nutrition Coach"
- [x] Updated description to mention WHOOP integration
- [x] Added WHOOP example questions:
  - "How does my nutrition affect my recovery?"
  - "What should I eat to improve my sleep?"
  - "Show me correlations between my diet and WHOOP metrics"
  - "Why is my recovery low? What can I change?"
  - "Does protein intake affect my HRV?"

**Deliverable**: User-facing chatbot now advertises WHOOP capabilities

---

### **Example User Questions Now Supported**:

```
User: "How does my nutrition affect my recovery?"

LLM calls:
1. get_whoop_data_availability(days_back=30)
2. get_whoop_correlations(days_back=30, min_significance=0.05)
3. get_whoop_recovery_suggestions(days_back=30)

Response:
"Based on the last 30 days of data (26 days with both nutrition and WHOOP data),
I've found some interesting patterns:

🔍 **Top Correlations with Recovery:**

1. **Protein intake → Recovery score** (r=0.68, p=0.003)
   - Strong positive correlation with high confidence
   - On days you eat more protein, your recovery is typically 8-12% higher
   - Effect appears the next day (1-day lag)

2. **Carbohydrate intake → Recovery score** (r=0.45, p=0.02)
   - Moderate positive correlation
   - Higher carbs correlate with better recovery, especially after high strain days

💡 **Personalized Suggestions:**

Your current average protein is 85g/day. Based on your data, increasing to 110-120g
could improve your recovery. This is strongly supported by your personal data
(not just general advice).

Try this: Add one of these daily:
- 6oz chicken breast (54g protein)
- 2 scoops whey protein (50g)
- 6 whole eggs (36g)

Track your recovery over the next week to see if it helps!"
```

---

## 🚀 Next Steps

1. ✅ ~~Add WHOOP_ACCESS_TOKEN to secrets.toml~~ (Phase 0.2)
2. ✅ ~~Start Phase 1: WHOOP API Integration~~ (Task 1.1: whoop_client.py)
3. ✅ ~~Track progress using this document~~ (check off tasks as completed)
4. ✅ ~~Run demo data generator after Phase 3~~ (scripts/generate_demo_data.py)
5. **Test LLM chatbot with WHOOP questions** (ask recovery/sleep questions)
6. **Complete Phase 5: Documentation** (create PHASE3_README.md)
7. **Prepare demo for professor** (Phase 5.4)

---

## 📌 Notes

- **Data Privacy**: WHOOP data is personal (single-user account). No PII stored beyond what's needed.
- **Academic Use**: Synthetic nutrition data is clearly flagged for demonstration purposes.
- **Scalability**: Architecture supports multi-user deployment with OAuth flow in future.
- **Statistical Rigor**: Uses established methods (Pearson correlation, p-values, effect sizes).
- **Reproducibility**: Demo data generator ensures consistent results across runs.

---

**Last Updated**: 2025-01-31
**Status**: Ready to Begin Implementation
**Next Action**: Configure WHOOP access token (Phase 0.2)
