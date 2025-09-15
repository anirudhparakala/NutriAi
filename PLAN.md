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

## **Phase 2 — Database & Whoop Integration**

**Goal:** Add persistence + biometrics layer.

* **SQLite Schema**

  * `meals`: nutrition breakdown logs.
  * `whoop_daily`: fitness/recovery metrics.
  * `user_metrics`: weight, goals, notes.

* **Whoop API Integration**

  * `/whoop/sync` → fetch daily stats (burned kcal, HRV, sleep, recovery, strain).
  * Insert into `whoop_daily`.

* **Insight Layer (lightweight)**

  * Compare intake vs burn.
  * Simple daily/weekly summaries → stored or displayed.

---

## **Phase 3 — Intelligent Insights**

**Goal:** Automated, AI-driven daily coaching.

* **Daily Insights Prompt**

  * Gemini sees combined data (meals + whoop + goals).
  * Generates 5 insights that merge food + recovery context (e.g., “yesterday overate → burn 400 more today”).

* **Trend Analysis**

  * Rolling averages (7-day intake vs expenditure).
  * Correlations (sleep/HRV ↔ macros).
  * Goal-aware nudges (cut/bulk/maintain stored in DB).

---

## **Phase 4 — Chatbot Layer**

**Goal:** Conversational access to logged data with **query decomposition**.

* **Metric Registry (atomic functions)**

  * Define \~15 metrics (e.g., `calorie_intake(days)`, `burn(days)`, `balance(days)`, `avg_protein(days)`, `deficit_series(days)`, `goal()`, `set_goal()`).
  * Each metric is deterministic, tested, and safe.

* **LLM Planner Role**

  * User asks natural question.
  * LLM decomposes into **metric function calls** + operators (filter, group, avg).
  * Example: *“What’s my average deficit last 2 weeks?”* → `balance(14)/14`.

* **Fallback Ladder**

  1. Reformulate to nearest known metric.
  2. Ask at most one clarifying question (time window, goal, etc.).
  3. Partial answer with disclosure (“2 missing days in window”).
  4. Explicit can’t-answer if DB data missing.

* **AI Narration**

  * Gemini contextualizes numbers → natural language output.
  * No invented numbers — always backed by DB functions.
  * Transparent: states time window, assumptions, defaults.

---

## **Final State**

* **Meal Flow:** Upload → Gemini guess + smart clarifications → USDA lookup → validation → DB log → UI.
* **Whoop Flow:** Sync daily → DB → available for insights.
* **Insights Flow:** Daily coaching using DB + Gemini.
* **Chatbot Flow:** Flexible queries resolved via metric registry + LLM decomposition.

---

⚡ **Integration point:** Phase 4 is no longer “list of fixed tools” → it’s **a registry + planner approach**. That way you don’t need to anticipate every question — just define safe atomic metrics and let Gemini compose them.

---
