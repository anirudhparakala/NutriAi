from tavily import TavilyClient


def create_search_tool_function(tavily_client: TavilyClient):
    """
    Creates a search function with the tavily client injected.

    Args:
        tavily_client: Configured TavilyClient instance

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

            # OPTIONAL: Log search telemetry here if you have session_id in scope
            # db.log_search_query(st.session_state.get("active_session_id"), query, len(rows))

            return rows
        except Exception as e:
            print(f"Error during search: {e}")
            # Return structured error so callers can branch, not a string
            return [{"error": str(e)}]

    return search_with_client