import webbrowser
from urllib.parse import quote

class GoogleSearchSkill:
    def __init__(self):
        self.search_engines = {
            "google": "https://www.google.com/search?q=",
            "bing": "https://www.bing.com/search?q=",
            "duckduckgo": "https://duckduckgo.com/?q="
        }
    
    def search(self, query):
        """Search using Google (opens in browser - no API required)"""
        try:
            if not query.strip():
                return "Please provide a search query."
            
            search_url = self.search_engines["google"] + quote(query)
            webbrowser.open(search_url)
            return f"Opening Google search for '{query}' in your browser."
        except Exception as e:
            return f"Error opening search: {e}"