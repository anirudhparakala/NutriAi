import json
from tavily import TavilyClient


def create_search_tool_function(tavily_client: TavilyClient):
    """
    Creates a search function with the tavily client injected.

    Args:
        tavily_client: Configured TavilyClient instance

    Returns:
        Function that performs web search using the provided client
    """
    def search_with_client(query: str) -> str:
        try:
            print(f"Performing search for: {query}")
            results = tavily_client.search(query=query, search_depth="basic")
            return json.dumps([{"url": obj["url"], "content": obj["content"]} for obj in results['results']])
        except Exception as e:
            print(f"Error during search: {e}")
            return f"Error performing search: {e}"

    return search_with_client