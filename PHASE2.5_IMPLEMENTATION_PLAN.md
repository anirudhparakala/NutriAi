# Phase 2.5 Implementation Plan

## Overview
Phase 2.5 adds visual analytics and conversational database access to leverage the existing nutrition logging database. This is a stopgap measure while waiting for WHOOP API access approval.

---

## Part A: Analytics Dashboard

### Goal
Provide visual insights into logged nutrition data with real-time and historical views.

### Implementation Approach

#### 1. **Technology Stack**
- **Charting Library**: Streamlit native charts (`st.plotly_chart` with Plotly)
  - **Why Plotly**: Interactive, professional-looking, built-in Streamlit support
  - **Alternative**: `st.pyplot` with matplotlib (simpler but less interactive)
- **Data Source**: Existing `sessions` and `session_items` tables in SQLite
- **Navigation**: Streamlit sidebar with page selector

#### 2. **Database Query Functions** (new file: `integrations/analytics.py`)
Create atomic query functions that extract aggregated data:

**Function signatures:**
```python
def get_today_totals() -> Dict[str, float]
    """Returns {calories, protein, carbs, fat} for today's logged meals."""

def get_meals_by_date(date: str) -> List[Dict]
    """Returns list of meals logged on specific date with breakdowns."""

def get_date_range_summary(start_date: str, end_date: str) -> Dict
    """Returns daily aggregates for date range."""

def get_macro_percentages(totals: Dict) -> Dict[str, float]
    """Calculates % breakdown: protein/carbs/fat from gram totals."""
```

**Key considerations:**
- Parse `final_json` field from sessions table to extract macro totals
- Handle missing/null data gracefully (sessions without final_json)
- Use SQLite date functions for efficient filtering
- Cache results for performance (Streamlit's `@st.cache_data` decorator)

#### 3. **UI Components** (new file: `ui/dashboard.py`)

**Page Structure:**
```
Sidebar:
  - Page selector: "Upload Food" / "Dashboard" / "Chatbot"
  - Date picker (for historical view)

Main Dashboard Layout:
  [Header] Today's Nutrition Summary

  [Section 1] Today's Macro Breakdown
    - Pie chart: Protein % / Carbs % / Fat %
    - Total calories badge
    - Meal count badge

  [Section 2] Today's Meals
    - Expandable cards for each meal
    - Time logged, dish name, macro totals per meal

  [Section 3] Historical View
    - Date selector (calendar widget)
    - Same visualization as Section 1-2 but for selected date
    - Line chart: 7-day trend (calories, protein, carbs, fat)
```

**Streamlit Components Used:**
- `st.sidebar.selectbox()` - Page navigation
- `st.date_input()` - Date picker
- `st.plotly_chart()` - Pie chart and line charts
- `st.metric()` - Display calorie/macro totals with deltas
- `st.expander()` - Collapsible meal cards
- `st.columns()` - Layout macro metrics side-by-side

#### 4. **Data Flow**
```
User opens Dashboard page
  ↓
analytics.get_today_totals() queries DB
  ↓
Parse final_json from sessions
  ↓
Calculate macro percentages
  ↓
Render Plotly pie chart
  ↓
analytics.get_meals_by_date(today) for meal list
  ↓
Display expandable meal cards
```

**Edge Cases:**
- No meals logged today → Show empty state with helpful message
- Incomplete session data → Skip or show partial data with warning
- Invalid JSON in final_json → Log error, skip that session

---

## Part B: Database Chatbot

### Goal
Allow users to ask natural language questions about their nutrition history, with all answers grounded in actual database data (no hallucinations).

### Implementation Approach

#### 1. **Technology Stack**
- **LLM**: OpenAI GPT-4o-mini (fast, cheap, good at function calling)
  - **Why OpenAI**: Native function calling support, reliable structured outputs
  - **API**: OpenAI Python SDK (`openai` package)
- **Architecture**: Function calling / tool use pattern
  - LLM acts as **query planner** (decomposes questions into DB queries)
  - Python functions execute **actual DB queries**
  - LLM acts as **narrator** (formats results in natural language)
- **Data Source**: Same `sessions` and `session_items` tables

#### 2. **Metric Registry** (new file: `core/metrics.py`)
Define atomic, deterministic functions for common nutrition queries:

**Function categories:**

**A. Intake Metrics:**
```python
def avg_daily_calories(days: int = 7) -> float
    """Average daily calorie intake for last N days."""

def avg_daily_protein(days: int = 7) -> float
    """Average daily protein (grams) for last N days."""

def avg_daily_carbs(days: int = 7) -> float
    """Average daily carbs (grams) for last N days."""

def avg_daily_fat(days: int = 7) -> float
    """Average daily fat (grams) for last N days."""

def total_meals_logged(days: int = 7) -> int
    """Count of meals logged in last N days."""
```

**B. Ratio Metrics:**
```python
def macro_ratio_breakdown(days: int = 7) -> Dict[str, float]
    """Returns {protein_pct, carbs_pct, fat_pct} averaged over N days."""

def calorie_distribution_by_meal_type() -> Dict[str, float]
    """Breakdown by breakfast/lunch/dinner/snack (if categorized)."""
```

**C. Temporal Metrics:**
```python
def daily_calorie_series(days: int = 7) -> List[Tuple[str, float]]
    """Returns [(date, calories), ...] for last N days."""

def streak_days() -> int
    """Longest consecutive days with logged meals."""
```

**D. Food-Specific:**
```python
def top_foods_by_frequency(limit: int = 10) -> List[Tuple[str, int]]
    """Most frequently logged dishes."""

def protein_sources_breakdown() -> Dict[str, float]
    """Breakdown of protein by source (chicken, beans, etc.) from session_items."""
```

**Key Principles:**
- **Deterministic**: Same input → same output
- **Safe**: No mutations, no side effects
- **Tested**: Unit tests for each metric
- **Transparent**: Returns None if insufficient data, doesn't invent numbers

#### 3. **OpenAI Function Calling Integration** (new file: `core/chatbot.py`)

**Architecture:**
```python
# Define function schemas for OpenAI
METRIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "avg_daily_calories",
            "description": "Get average daily calorie intake for last N days",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days to average"}
                },
                "required": ["days"]
            }
        }
    },
    # ... repeat for all metrics
]

def answer_question(user_question: str) -> str:
    """
    Main chatbot entry point.

    Flow:
    1. Send question + tool definitions to OpenAI
    2. LLM returns function calls (e.g., avg_daily_calories(days=7))
    3. Execute functions, get results from DB
    4. Send results back to LLM
    5. LLM generates natural language answer
    6. Return answer to user
    """
    messages = [
        {"role": "system", "content": CHATBOT_SYSTEM_PROMPT},
        {"role": "user", "content": user_question}
    ]

    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        tools=METRIC_TOOLS,
        tool_choice="auto"
    )

    # Check if LLM wants to call functions
    if response.choices[0].message.tool_calls:
        # Execute function calls
        for tool_call in response.choices[0].message.tool_calls:
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)

            # Call actual metric function
            result = METRIC_REGISTRY[function_name](**arguments)

            # Append result to conversation
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result)
            })

        # Get final natural language response
        final_response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
        return final_response.choices[0].message.content
    else:
        return response.choices[0].message.content
```

**System Prompt:**
```
You are a nutrition data analyst assistant. You help users understand their eating patterns based on their logged meal data.

CRITICAL RULES:
1. NEVER invent numbers - only use data from function calls
2. If insufficient data, say so explicitly
3. Always state time windows (e.g., "over the last 7 days")
4. If a function returns None, explain missing data
5. Be conversational but precise

Example good response:
"Over the last 7 days, you averaged 2,150 calories per day. Your macro breakdown was 25% protein, 45% carbs, and 30% fat."

Example bad response (NEVER DO THIS):
"Based on typical patterns, you're probably eating around 2,000 calories." [HALLUCINATION - no function call]
```

#### 4. **UI Integration** (add to `ui/app.py` or new `ui/chatbot_page.py`)

**Page Structure:**
```
Sidebar:
  - Page selector: "Upload Food" / "Dashboard" / "Chatbot"

Main Chatbot Layout:
  [Header] Ask About Your Nutrition

  [Chat History]
    - Display conversation (user questions + bot answers)
    - Scrollable container

  [Input Box]
    - st.text_input() for user question
    - Example questions shown as clickable buttons:
      • "What's my average protein intake?"
      • "Show my macro breakdown for last 2 weeks"
      • "What foods do I eat most often?"
```

**Streamlit Components:**
- `st.chat_message()` - Display chat bubbles (user/assistant)
- `st.chat_input()` - User question input
- `st.button()` - Example question shortcuts
- `st.session_state.messages` - Persist chat history across reruns

**Data Flow:**
```
User types question
  ↓
chatbot.answer_question(question) called
  ↓
OpenAI determines which metric functions to call
  ↓
Execute metric functions → query DB
  ↓
Return results to OpenAI
  ↓
OpenAI generates natural language answer
  ↓
Display answer in chat UI
  ↓
Append to st.session_state.messages
```

#### 5. **Fallback Handling**

**Scenarios:**

**A. Ambiguous Question:**
```
User: "Am I eating too much?"
Bot: "I need more context. Are you asking about:
  1. Total daily calories
  2. A specific macro (protein/carbs/fat)
  3. Meal frequency
Please clarify, and I can help!"
```

**B. Insufficient Data:**
```
User: "What's my average over the last month?"
Function returns: None (only 3 days of data logged)
Bot: "I only have 3 days of meal data logged. I need at least 7 days to provide a reliable average. Keep logging meals, and ask again soon!"
```

**C. Out-of-Scope Question:**
```
User: "Should I go keto?"
Bot: "I can analyze your current eating patterns, but I can't provide medical or dietary advice. I'd recommend consulting a registered dietitian for personalized recommendations. What I can tell you is your current macro breakdown - would that help?"
```

**D. No Function Match:**
```
User: "What's the weather today?"
Bot: "I'm a nutrition data assistant - I can only answer questions about your logged meals and eating patterns. Try asking about your calorie intake, macro breakdown, or most-eaten foods!"
```

---

## Implementation Order

### Priority 1: Analytics Dashboard (Simpler, visible results)
1. Create `integrations/analytics.py` with query functions
2. Create `ui/dashboard.py` with Streamlit UI
3. Add page navigation to `ui/app.py`
4. Test with existing database data
5. Polish visuals (colors, spacing, empty states)

**Estimated Time:** 3-4 hours

### Priority 2: Database Chatbot (More complex, impressive demo)
1. Install OpenAI SDK: `pip install openai`
2. Create `core/metrics.py` with 10-15 metric functions
3. Write unit tests for metrics
4. Create `core/chatbot.py` with OpenAI function calling logic
5. Create `ui/chatbot_page.py` with chat UI
6. Add OpenAI API key to secrets
7. Test conversation flows and edge cases

**Estimated Time:** 5-6 hours

**Total Estimated Time:** 8-10 hours

---

## Dependencies & Setup

### New Python Packages
```bash
pip install openai plotly
```

### Secrets Configuration
```toml
# .streamlit/secrets.toml
GEMINI_API_KEY = "..."
TAVILY_API_KEY = "..."
USDA_API_KEY = "..."
OPENAI_API_KEY = "sk-..."  # NEW for chatbot
```

### Database Requirements
- No schema changes needed ✅
- Existing `sessions` and `session_items` tables have all required data
- `final_json` field contains macro breakdowns

---

## Testing Strategy

### Analytics Dashboard
- **Unit Tests**: Test query functions with mock DB data
- **Integration Tests**: Test with real database (at least 7 days of data)
- **Edge Cases**: Empty database, single day of data, missing final_json

### Chatbot
- **Unit Tests**: Test each metric function independently
- **Mock Tests**: Test OpenAI integration with mocked API responses
- **Integration Tests**: Real conversations with real DB data
- **Edge Cases**: Ambiguous questions, insufficient data, out-of-scope queries

---

## Success Metrics

### Analytics Dashboard
- ✅ Loads today's data in <1 second
- ✅ Pie chart accurately represents macro percentages
- ✅ Historical date selector works for any date
- ✅ Graceful handling of missing data
- ✅ Mobile-responsive layout

### Chatbot
- ✅ Answers 10+ common nutrition questions correctly
- ✅ Never invents numbers (all answers grounded in DB)
- ✅ Response time <3 seconds for simple queries
- ✅ Handles ambiguity with clarifying questions
- ✅ Explicitly states when data is insufficient

---

## Risks & Mitigation

### Risk 1: OpenAI API Costs
- **Mitigation**: Use GPT-4o-mini (cheap model), cache common queries
- **Estimated Cost**: ~$0.01 per conversation (very low)

### Risk 2: Chatbot Hallucinations
- **Mitigation**: Strict system prompt, function calling only, unit tests verify no invented data
- **Monitoring**: Log all chatbot responses for quality review

### Risk 3: Empty Database (New Users)
- **Mitigation**: Show helpful onboarding messages, example questions grayed out until data exists
- **UX**: "Log at least 3 meals to enable chatbot features"

### Risk 4: Complex Queries Beyond Metric Functions
- **Mitigation**: LLM can compose multiple functions (e.g., "compare this week to last week" = two function calls)
- **Fallback**: Ask clarifying questions to narrow scope

---

## Phase 2.5 Success Definition

**Demo-Ready Criteria:**
1. ✅ Dashboard shows today's nutrition with pie chart
2. ✅ Historical date selector works smoothly
3. ✅ Chatbot answers ≥5 sample questions correctly
4. ✅ No hallucinations (all answers database-backed)
5. ✅ Professional visual polish (charts, spacing, colors)
6. ✅ Runs on professor's machine with sample data

**Stretch Goals (if time permits):**
- 7-day trend line chart
- Meal streak counter
- Top foods leaderboard
- Export data to CSV
- Weekly summary email (scheduled job)

---

**Phase 2.5 Status: PLANNING COMPLETE → Ready for Implementation**
