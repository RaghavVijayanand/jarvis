import webbrowser
import subprocess
import platform
from urllib.parse import quote
from skills.web_scraper import WebScraperSkill

class WebSearchSkill:
    def __init__(self):
        self.search_engines = {
            "google": "https://www.google.com/search?q=",
            "bing": "https://www.bing.com/search?q=",
            "duckduckgo": "https://duckduckgo.com/?q="
        }
        self.default_engine = "google"
        self.scraper = WebScraperSkill()
    
    def search_web(self, query, engine="google", open_browser=False):
        """Search the web for a query - now using web scraping by default"""
        if not query.strip():
            return "Please provide a search query."
        
        engine = engine.lower()
        
        # Use web scraping by default (no browser opening)
        if not open_browser:
            try:
                if engine == "google" or engine not in self.search_engines:
                    return self.scraper.search_google(query)
                else:
                    # For other engines, fall back to URL generation
                    search_url = self.search_engines[engine] + quote(query)
                    return f"Search URL for '{query}' on {engine}: {search_url}\n\nFor Google results without opening browser:\n{self.scraper.search_google(query)}"
            except Exception as e:
                return f"Web scraping failed: {e}. Search URL: {self.search_engines[self.default_engine] + quote(query)}"
        else:
            # Legacy browser opening mode
            if engine not in self.search_engines:
                engine = self.default_engine
            
            search_url = self.search_engines[engine] + quote(query)
            
            try:
                webbrowser.open(search_url)
                return f"Opening {engine} search for '{query}' in your browser."
            except Exception as e:
                return f"Could not open browser: {e}"
    
    def search_wikipedia(self, query, open_browser=False):
        """Search Wikipedia - now using web scraping by default"""
        try:
            if not open_browser:
                # Use web scraping
                return self.scraper.search_wikipedia(query)
            else:
                # Legacy browser opening mode
                wiki_url = f"https://en.wikipedia.org/wiki/Special:Search?search={quote(query)}"
                webbrowser.open(wiki_url)
                return f"Opening Wikipedia search for '{query}' in your browser."
        except Exception as e:
            return f"Error searching Wikipedia: {e}"
    
    def get_news_headlines(self, source="general", open_browser=False):
        """Get news headlines - now using web scraping by default"""
        try:
            if not open_browser:
                # Use web scraping
                return self.scraper.get_news_headlines(source)
            else:
                # Legacy browser opening mode
                news_sites = [
                    "https://news.google.com",
                    "https://www.bbc.com/news",
                    "https://www.reuters.com",
                    "https://www.cnn.com"
                ]
                
                import random
                site = random.choice(news_sites)
                webbrowser.open(site)
                return f"Opening news website in your browser."
        except Exception as e:
            return f"Error getting news: {e}"
    
    def read_webpage(self, url):
        """Read and summarize a webpage without opening browser"""
        try:
            return self.scraper.read_webpage(url)
        except Exception as e:
            return f"Error reading webpage: {e}"
    
    def search_and_read(self, query):
        """Search Google and read the first result"""
        try:
            return self.scraper.search_and_read(query)
        except Exception as e:
            return f"Error in search and read: {e}"
    
    def get_quick_fact(self, topic):
        """Get a quick fact about something"""
        try:
            return self.scraper.quick_fact(topic)
        except Exception as e:
            return f"Error getting fact: {e}"
    
    def open_website(self, url):
        """Open a website in the default browser (legacy mode)"""
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            
            webbrowser.open(url)
            return f"Opening {url} in your browser."
        except Exception as e:
            return f"Could not open website: {e}"
