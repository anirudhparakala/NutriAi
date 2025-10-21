"""
Chatbot module for nutrition coaching.
Uses OpenAI function calling to answer user questions about their nutrition data.
"""

from openai import OpenAI
from datetime import datetime, timedelta
from typing import List, Dict
import json
from core import metrics


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
    "compare_time_periods": metrics.compare_time_periods
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
        self.system_prompt = f"""You are an AI nutrition coach assistant. You help users understand their eating habits by analyzing their food log data.

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

Format your responses in a friendly, conversational tone. Use specific numbers from the data to support your recommendations."""

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
