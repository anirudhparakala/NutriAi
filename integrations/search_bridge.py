from tavily import TavilyClient
from typing import Callable, Optional


def create_search_tool_function(tavily_client: TavilyClient, metric_logger: Optional[Callable[[str, int], None]] = None):
    """
    Creates a search function with the tavily client injected and optional metric logging.

    Args:
        tavily_client: Configured TavilyClient instance
        metric_logger: Optional callback function to log search metrics (query, result_count)

    Returns:
        Function that performs web search using the provided client
    """
    def search_with_client(query: str) -> list[dict]:
        """
        Perform web search and return Python list (not JSON string).
        The Gemini SDK accepts dict/list tool outputs directly.
        """
        try:
            print(f"Performing search for: {query}")
            results = tavily_client.search(query=query, search_depth="basic")
            rows = [{"url": obj["url"], "content": obj["content"]} for obj in results.get("results", [])]

            # Call metric logger hook if provided
            if metric_logger:
                try:
                    metric_logger(query, len(rows))
                except Exception as log_error:
                    print(f"Metric logging failed (non-fatal): {log_error}")

            return rows
        except Exception as e:
            print(f"Error during search: {e}")
            # Return structured error so callers can branch, not a string
            return [{"error": str(e)}]

    return search_with_client