"""
Chatbot module for nutrition coaching.
Uses OpenAI function calling to answer user questions about their nutrition data.
"""

from openai import OpenAI
from datetime import datetime, timedelta
from typing import List, Dict
import json
from core import metrics
from core import whoop_metrics


# OpenAI function definitions for all 16 metric functions
FUNCTION_DEFINITIONS = [
    {
        "name": "get_most_recent_logged_date",
        "description": "Get the most recent date with logged meals. Use this to find the actual last day with data when queries return no results.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_calories_for_date",
        "description": "Get total calories logged on a specific date",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (e.g., '2025-01-20')"
                }
            },
            "required": ["date"]
        }
    },
    {
        "name": "get_average_daily_calories",
        "description": "Get average daily calories over a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                }
            },
            "required": ["start_date", "end_date"]
        }
    },
    {
        "name": "get_average_daily_macros",
        "description": "Get average daily protein, carbs, and fat (in grams) over a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                }
            },
            "required": ["start_date", "end_date"]
        }
    },
    {
        "name": "get_macro_distribution",
        "description": "Get macro distribution as percentages (protein%, carbs%, fat%) over a date range. Use this to analyze diet balance.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                }
            },
            "required": ["start_date", "end_date"]
        }
    },
    {
        "name": "get_days_logged",
        "description": "Count how many unique days have logged meals in a date range. Use this to check tracking consistency.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                }
            },
            "required": ["start_date", "end_date"]
        }
    },
    {
        "name": "get_meal_count",
        "description": "Get total number of meals logged in a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                }
            },
            "required": ["start_date", "end_date"]
        }
    },
    {
        "name": "get_average_calories_per_meal",
        "description": "Get average calories per meal over a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                }
            },
            "required": ["start_date", "end_date"]
        }
    },
    {
        "name": "get_average_macros_per_meal",
        "description": "Get average protein, carbs, and fat (in grams) per meal over a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                }
            },
            "required": ["start_date", "end_date"]
        }
    },
    {
        "name": "get_highest_calorie_days",
        "description": "Get the top N days with highest calories in a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of days to return (default 5)"
                }
            },
            "required": ["start_date", "end_date"]
        }
    },
    {
        "name": "get_lowest_calorie_days",
        "description": "Get the top N days with lowest calories in a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of days to return (default 5)"
                }
            },
            "required": ["start_date", "end_date"]
        }
    },
    {
        "name": "get_highest_macro_days",
        "description": "Get the top N days with highest amount of a specific macro (protein, carbs, or fat)",
        "parameters": {
            "type": "object",
            "properties": {
                "macro_type": {
                    "type": "string",
                    "enum": ["protein", "carbs", "fat"],
                    "description": "Type of macro to analyze"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of days to return (default 5)"
                }
            },
            "required": ["macro_type", "start_date", "end_date"]
        }
    },
    {
        "name": "get_lowest_macro_days",
        "description": "Get the top N days with lowest amount of a specific macro (protein, carbs, or fat)",
        "parameters": {
            "type": "object",
            "properties": {
                "macro_type": {
                    "type": "string",
                    "enum": ["protein", "carbs", "fat"],
                    "description": "Type of macro to analyze"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of days to return (default 5)"
                }
            },
            "required": ["macro_type", "start_date", "end_date"]
        }
    },
    {
        "name": "get_most_frequent_foods",
        "description": "Get the most frequently logged food items over a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of foods to return (default 10)"
                }
            },
            "required": ["start_date", "end_date"]
        }
    },
    {
        "name": "get_food_calorie_contribution",
        "description": "Get total calories and macros from a specific food item over a date range. Use this for questions like 'how much did I eat from McDonald's' or 'how many calories from chicken'.",
        "parameters": {
            "type": "object",
            "properties": {
                "food_name": {
                    "type": "string",
                    "description": "Name of the food to search for (partial match, case-insensitive)"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format"
                }
            },
            "required": ["food_name", "start_date", "end_date"]
        }
    },
    {
        "name": "compare_time_periods",
        "description": "Compare two time periods across multiple metrics (calories, macros, distribution, days logged, meal count). Use this for 'this week vs last week' type questions.",
        "parameters": {
            "type": "object",
            "properties": {
                "period1_start": {
                    "type": "string",
                    "description": "Period 1 start date in YYYY-MM-DD format"
                },
                "period1_end": {
                    "type": "string",
                    "description": "Period 1 end date in YYYY-MM-DD format"
                },
                "period2_start": {
                    "type": "string",
                    "description": "Period 2 start date in YYYY-MM-DD format"
                },
                "period2_end": {
                    "type": "string",
                    "description": "Period 2 end date in YYYY-MM-DD format"
                }
            },
            "required": ["period1_start", "period1_end", "period2_start", "period2_end"]
        }
    },
    {
        "name": "get_whoop_correlations",
        "description": "Get correlations between nutrition (protein, carbs, fat, calories) and WHOOP physiological metrics (recovery, sleep, strain, HRV). Shows which nutrition factors correlate with performance.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to analyze (default 30)",
                    "default": 30
                },
                "min_significance": {
                    "type": "number",
                    "description": "Minimum p-value for significance (default 0.05)",
                    "default": 0.05
                }
            },
            "required": []
        }
    },
    {
        "name": "get_whoop_suggestions",
        "description": "Get personalized nutrition suggestions based on discovered correlations with WHOOP metrics. Provides actionable recommendations to improve recovery, sleep, or performance.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to analyze (default 30)",
                    "default": 30
                },
                "focus_metric": {
                    "type": "string",
                    "description": "Optional: focus on specific WHOOP metric (recovery_score, sleep_performance, strain, hrv)",
                    "enum": ["recovery_score", "sleep_performance", "strain", "hrv"]
                }
            },
            "required": []
        }
    },
    {
        "name": "get_whoop_recovery_suggestions",
        "description": "Get nutrition suggestions specifically for improving recovery score. Use when user asks about improving recovery or feels tired.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to analyze (default 30)",
                    "default": 30
                }
            },
            "required": []
        }
    },
    {
        "name": "get_whoop_sleep_suggestions",
        "description": "Get nutrition suggestions specifically for improving sleep performance. Use when user asks about sleep quality or sleep issues.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to analyze (default 30)",
                    "default": 30
                }
            },
            "required": []
        }
    },
    {
        "name": "get_whoop_data_availability",
        "description": "Check how many days of WHOOP and nutrition data are available for analysis. Use this to verify sufficient data before running correlation analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to check (default 30)",
                    "default": 30
                }
            },
            "required": []
        }
    },
    {
        "name": "get_whoop_summary",
        "description": "Get summary statistics for WHOOP metrics (average recovery, strain, sleep, HRV, etc.) over a time period.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to summarize (default 30)",
                    "default": 30
                }
            },
            "required": []
        }
    },
    {
        "name": "get_strain_controlled_correlations",
        "description": "Get correlations between nutrition and WHOOP metrics with strain's confounding effect REMOVED. Shows nutrition's TRUE independent effect. Use this for more accurate insights when strain might be masking the real relationship.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to analyze (default 30)",
                    "default": 30
                }
            },
            "required": []
        }
    },
    {
        "name": "get_stratified_analysis",
        "description": "Analyze if nutrition matters MORE on high-strain days vs low-strain days. Splits data into low/medium/high strain groups to discover when nutrition has the biggest impact.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to analyze (default 30)",
                    "default": 30
                }
            },
            "required": []
        }
    },
    {
        "name": "get_interaction_effects",
        "description": "Discover when nutrition matters MORE based on context (strain, sleep debt, recovery state, HRV, calorie burn). Tests 5 interaction types to find optimal timing for nutrition interventions.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to analyze (default 30)",
                    "default": 30
                }
            },
            "required": []
        }
    },
    {
        "name": "get_context_aware_suggestions",
        "description": "Get personalized nutrition suggestions based on CURRENT physiological state (strain, recovery, sleep debt). Provides context-aware recommendations that adapt to today's conditions.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to analyze (default 30)",
                    "default": 30
                },
                "current_strain": {
                    "type": "number",
                    "description": "Current strain score (optional). If provided, generates strain-specific advice."
                },
                "current_recovery": {
                    "type": "number",
                    "description": "Current recovery percentage (optional). If provided, adjusts advice based on recovery state."
                },
                "current_sleep_debt": {
                    "type": "number",
                    "description": "Current sleep debt in minutes (optional). If provided, factors in sleep deprivation."
                }
            },
            "required": []
        }
    }
]


# Map function names to actual Python functions
FUNCTION_MAP = {
    "get_most_recent_logged_date": metrics.get_most_recent_logged_date,
    "get_calories_for_date": metrics.get_calories_for_date,
    "get_average_daily_calories": metrics.get_average_daily_calories,
    "get_average_daily_macros": metrics.get_average_daily_macros,
    "get_macro_distribution": metrics.get_macro_distribution,
    "get_days_logged": metrics.get_days_logged,
    "get_meal_count": metrics.get_meal_count,
    "get_average_calories_per_meal": metrics.get_average_calories_per_meal,
    "get_average_macros_per_meal": metrics.get_average_macros_per_meal,
    "get_highest_calorie_days": metrics.get_highest_calorie_days,
    "get_lowest_calorie_days": metrics.get_lowest_calorie_days,
    "get_highest_macro_days": metrics.get_highest_macro_days,
    "get_lowest_macro_days": metrics.get_lowest_macro_days,
    "get_most_frequent_foods": metrics.get_most_frequent_foods,
    "get_food_calorie_contribution": metrics.get_food_calorie_contribution,
    "compare_time_periods": metrics.compare_time_periods,
    # WHOOP correlation functions
    "get_whoop_correlations": whoop_metrics.get_whoop_correlations,
    "get_whoop_suggestions": whoop_metrics.get_whoop_suggestions,
    "get_whoop_recovery_suggestions": whoop_metrics.get_whoop_recovery_suggestions,
    "get_whoop_sleep_suggestions": whoop_metrics.get_whoop_sleep_suggestions,
    "get_whoop_data_availability": whoop_metrics.get_whoop_data_availability,
    "get_whoop_summary": whoop_metrics.get_whoop_summary,
    # Advanced WHOOP analytics functions
    "get_strain_controlled_correlations": whoop_metrics.get_strain_controlled_correlations,
    "get_stratified_analysis": whoop_metrics.get_stratified_analysis,
    "get_interaction_effects": whoop_metrics.get_interaction_effects,
    "get_context_aware_suggestions": whoop_metrics.get_context_aware_suggestions
}


class NutritionChatbot:
    """
    AI nutrition coach chatbot using OpenAI function calling.
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        """
        Initialize chatbot with OpenAI API key.

        Args:
            api_key: OpenAI API key
            model: OpenAI model to use (default: gpt-4o-mini for cost efficiency)
        """
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.conversation_history = []

        # System prompt for nutrition coaching
        self.system_prompt = f"""You are an AI nutrition coach assistant with access to both nutrition tracking data and WHOOP physiological metrics. You help users optimize their nutrition based on how it affects their recovery, sleep, and performance.

Current date: {datetime.now().strftime('%Y-%m-%d')}

When users ask questions:
1. Use the available functions to query their nutrition data
2. If a query for a specific date returns no data, use get_most_recent_logged_date() to find the actual last day with data, then query that date instead
3. Provide insightful, actionable advice based on the data
4. Compare their macro distribution to healthy baselines:
   - Protein: 25-35% of calories
   - Carbs: 45-55% of calories
   - Fat: 20-30% of calories
5. For bodyweight protein recommendations, use 1.6-2.2g per kg bodyweight for active individuals
6. Be supportive and encouraging while providing honest feedback
7. When dates are mentioned relatively (yesterday, last week, etc.), calculate the actual dates based on current date

**WHOOP Integration Capabilities:**
8. Use WHOOP correlation functions to discover relationships between nutrition and physiological metrics:
   BASIC FUNCTIONS:
   - get_whoop_correlations(): Shows which nutrients correlate with recovery, sleep, strain, HRV
   - get_whoop_suggestions(): Provides personalized recommendations based on discovered correlations
   - get_whoop_recovery_suggestions(): Focus on improving recovery score
   - get_whoop_sleep_suggestions(): Focus on improving sleep quality
   - get_whoop_summary(): Get average WHOOP metrics over a period
   - get_whoop_data_availability(): Check if enough data exists for analysis

   ADVANCED FUNCTIONS (Use these for deeper insights):
   - get_strain_controlled_correlations(): Shows nutrition's TRUE effect after removing strain's confounding influence
   - get_stratified_analysis(): Discover if nutrition matters MORE on high-strain vs low-strain days
   - get_interaction_effects(): Find when nutrition matters MORE based on context (strain, sleep debt, recovery state)
   - get_context_aware_suggestions(): Get personalized advice based on TODAY's strain, recovery, and sleep debt

9. When discussing WHOOP correlations:
   - Explain correlation strength (weak <0.3, moderate 0.3-0.5, strong >0.5)
   - Mention statistical significance (p-value)
   - Explain lag effects (e.g., "protein today affects recovery tomorrow")
   - Always emphasize correlation ≠ causation
   - Suggest trying recommendations as experiments, not guaranteed results
   - Use advanced functions when users want deeper insights or ask "when does nutrition matter more"

10. Proactively suggest WHOOP analysis when users ask about:
    - Recovery, energy levels, or feeling tired
    - Sleep quality or sleep issues
    - Performance optimization
    - What to change in their diet
    - When nutrition matters more (use get_stratified_analysis or get_interaction_effects)
    - Today's specific recommendations (use get_context_aware_suggestions)

Format your responses in a friendly, conversational tone. Use specific numbers from the data to support your recommendations. When presenting correlation data, be clear about statistical confidence and suggest actionable experiments."""

        self.conversation_history.append({
            "role": "system",
            "content": self.system_prompt
        })

    def _execute_function(self, function_name: str, arguments: Dict) -> str:
        """
        Execute a metrics function and return results as JSON string.

        Args:
            function_name: Name of function to call
            arguments: Dict of function arguments

        Returns:
            JSON string of function results
        """
        if function_name not in FUNCTION_MAP:
            return json.dumps({"error": f"Unknown function: {function_name}"})

        try:
            func = FUNCTION_MAP[function_name]
            result = func(**arguments)
            return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def chat(self, user_message: str) -> str:
        """
        Send a message to the chatbot and get a response.

        Args:
            user_message: User's question or message

        Returns:
            Chatbot's response as a string
        """
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Convert function definitions to tools format
        tools = [{"type": "function", "function": func_def} for func_def in FUNCTION_DEFINITIONS]

        # Initial API call
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.conversation_history,
            tools=tools,
            tool_choice="auto"
        )

        assistant_message = response.choices[0].message

        # Handle tool calling loop
        while assistant_message.tool_calls:
            tool_call = assistant_message.tool_calls[0]
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)

            print(f"[DEBUG] Calling function: {function_name} with args: {function_args}")

            # Execute the function
            function_result = self._execute_function(function_name, function_args)

            # Add assistant's tool call to history
            self.conversation_history.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": function_name,
                        "arguments": tool_call.function.arguments
                    }
                }]
            })

            # Add tool result to history
            self.conversation_history.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": function_result
            })

            # Get next response from model
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.conversation_history,
                tools=tools,
                tool_choice="auto"
            )

            assistant_message = response.choices[0].message

        # Add final assistant response to history
        assistant_response = assistant_message.content
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_response
        })

        return assistant_response

    def clear_history(self):
        """Reset conversation history (keeps system prompt)."""
        self.conversation_history = [{
            "role": "system",
            "content": self.system_prompt
        }]
