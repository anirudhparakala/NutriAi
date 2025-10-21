# 🛠 Enhanced Roadmap for Your Personal Health AI System

---

## **Phase 1 — Core Refactor (Meals & Validation)**

**Goal:** Replace hallucinations with structured estimates + USDA lookup + trust-building clarifications.

* **Gemini Prompting**

  * Identify dish + portion size (always assume full portion = user’s serving).
  * Expand into default ingredient list.
  * Highlight “critical clarification points” (oil type, meat leanness, cheese type, etc.).

* **Clarification Layer**

  * AI shows inference first → asks only about high-impact variables.
  * User can skip → defaults applied.

* **Nutrition Lookup (USDA/Nutritionix)**

  * Each ingredient mapped to DB entry.
  * Portion scaled to grams.
  * Totals computed from real data.

* **Validation Layer**

  * Clamp portion ranges (curry bowls 200–800g, burgers 100–400g, etc.).
  * Cross-check macros vs calories (4/4/9 rule).
  * Auto-correct or flag anomalies.

* **UI Output**

  * Transparent reasoning (“I assumed 250g chicken, 20g butter, 100g rice…”).
  * Per-ingredient breakdown + totals.

* **Entry Logging**

  * Insert into `meals` table: timestamp, per-item JSON, totals, assumptions, confidence.

---

## **Phase 2 — Database Quality Tracking**

**Goal:** Transform database from passive data lake to active feedback loop.

* **Schema Migration 4**

  * Add quality tracking fields to `sessions` table (validated, image_hash, run_ms, stage1_ok, stage2_shown, stage2_changed, portion_heuristic_rate).
  * Create `session_items` table for per-ingredient tracking.
  * Create `golden_labels` table for accuracy measurement.

* **Analytics Functions**

  * Baseline health comparison by prompt version.
  * Stage-2 effectiveness measurement.
  * Portion heuristic rate tracking.

* **Stage-2 Parser Improvements**

  * Deterministic-first parsing (regex + lexicons).
  * Partial success model (apply what works, warn about rest).
  * Safe ingredient matching (fixes dal→daliya bug).
  * Variant handling for beverages (diet/zero/light).

---

## **Phase 2.5 — Analytics Dashboard & Database Chatbot**

**Goal:** Provide visual insights and conversational access to logged nutrition data.

* **Analytics Dashboard**

  * **Today's Summary**: Real-time macro breakdown (pie chart) for meals logged today.
  * **Date Selector**: View historical food intake for any past date.
  * **Macro Visualizations**: Daily totals (calories, protein, carbs, fat) with charts.
  * **Meal History**: Chronological list of logged meals with thumbnails and summaries.

* **Database Chatbot**

  * **Natural Language Queries**: Ask questions about nutrition patterns ("How much % carbs am I having in general?").
  * **Database-Backed Answers**: All responses grounded in actual logged data (no hallucinations).
  * **Metric Functions**: Atomic functions for common queries (avg intake, macro ratios, date ranges).
  * **OpenAI Integration**: Use OpenAI API for query understanding and natural language generation.

---

## **Phase 3 — WHOOP Integration & Biometrics**

**Goal:** Add biometrics layer for comprehensive health tracking.

* **SQLite Schema Extensions**

  * `whoop_daily`: fitness/recovery metrics (burned kcal, HRV, sleep, recovery, strain).
  * `user_metrics`: weight, goals, notes.

* **WHOOP API Integration**

  * OAuth authentication flow.
  * `/whoop/sync` → fetch daily stats.
  * Insert into `whoop_daily` table.

* **Insight Layer (lightweight)**

  * Compare intake vs burn.
  * Simple daily/weekly summaries → stored or displayed.

---

## **Phase 4 — Intelligent Insights (with WHOOP)**

**Goal:** Automated, AI-driven daily coaching combining nutrition + biometrics.

* **Daily Insights Prompt**

  * LLM sees combined data (meals + whoop + goals).
  * Generates 5 insights that merge food + recovery context (e.g., "yesterday overate → burn 400 more today").

* **Trend Analysis**

  * Rolling averages (7-day intake vs expenditure).
  * Correlations (sleep/HRV ↔ macros).
  * Goal-aware nudges (cut/bulk/maintain stored in DB).

---

## **Final State**

* **Meal Flow:** Upload → Gemini guess + smart clarifications → USDA lookup → validation → DB log → UI.
* **Whoop Flow:** Sync daily → DB → available for insights.
* **Insights Flow:** Daily coaching using DB + Gemini.
* **Chatbot Flow:** Flexible queries resolved via metric registry + LLM decomposition.

---

⚡ **Integration point:** Phase 4 is no longer “list of fixed tools” → it’s **a registry + planner approach**. That way you don’t need to anticipate every question — just define safe atomic metrics and let Gemini compose them.

---
