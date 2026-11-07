import re
import webbrowser
import requests
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
    
    def search_web(self, query, engine="google", open_browser=False, llm_brain=None):
        """Search the web for a query and provide LLM-enhanced summaries"""
        if not query.strip():
            return "Please provide a search query."
        
        # Extract just the search terms from the query
        search_terms = self._extract_search_terms(query)
        
        engine = engine.lower()
        
        # Use web scraping with LLM summarization
        if not open_browser:
            try:
                if engine == "google" or engine not in self.search_engines:
                    # Get search results (this already works well)
                    search_results = self.scraper.search_google(search_terms, num_results=6)
                    
                    if search_results and "No search results found" not in search_results and "Error searching" not in search_results:
                        # Use LLM to create a better summary of the search results
                        if llm_brain:
                            return self._create_llm_summary(search_terms, search_results, llm_brain)
                        else:
                            return search_results  # Return original results if no LLM
                    else:
                        # Fallback to simpler search
                        return self._fallback_search(search_terms)
                else:
                    # For other engines, fall back to URL generation
                    search_url = self.search_engines[engine] + quote(search_terms)
                    return f"Search URL for '{search_terms}' on {engine}: {search_url}"
            except Exception as e:
                return self._fallback_search(search_terms)
        else:
            # Legacy browser opening mode
            if engine not in self.search_engines:
                engine = self.default_engine
            
            search_url = self.search_engines[engine] + quote(search_terms)
            
            try:
                webbrowser.open(search_url)
                return f"Opening {engine} search for '{search_terms}' in your browser."
            except Exception as e:
                return f"Could not open browser: {e}"
    
    def _create_llm_summary(self, query, search_results, llm_brain):
        """Use LLM to create a comprehensive summary from search results"""
        try:
            prompt = f"""Please analyze and summarize the following search results for the query "{query}". 

Provide a clean, well-organized summary that:
1. Gives an overview of the topic
2. Highlights the most important information from all sources
3. Organizes the information clearly with simple formatting
4. Includes specific details, dates, and facts where available

Important: Use plain text formatting only. No markdown symbols like *, **, #, - or bullet points. Use simple paragraphs and line breaks for organization.

Search Results:
{search_results}

Please create a clear, readable summary without any special formatting symbols."""

            summary = llm_brain.process_command(prompt, use_context=False)
            if getattr(summary, "is_error", False) or not str(summary).strip():
                return f"Search Results for '{query}':\n\n{search_results}"
            
            # Clean up any remaining markdown symbols that might have been generated
            cleaned_summary = str(summary).replace('*', '').replace('#', '').replace('---', '')
            
            # Remove excessive bullet points and format cleanly
            lines = cleaned_summary.split('\n')
            clean_lines = []
            for line in lines:
                line = line.strip()
                if line:
                    # Strip leading bullet markers only; a mid-sentence " - " (e.g.
                    # "2020 - 2021") used to be deleted too.
                    line = re.sub(r'^(?:[•\-*]\s+)+', '', line)
                    if line:
                        clean_lines.append(line)
            
            cleaned_summary = '\n'.join(clean_lines)
            
            # Add simple header
            result = f"Search Summary for '{query}':\n\n"
            result += cleaned_summary
            
            return result
            
        except Exception as e:
            # Fallback to original results if LLM fails
            return f"Search Results for '{query}':\n\n{search_results}"

    def _extract_search_terms(self, query):
        """Extract search terms from user query"""
        # Remove only command words, preserve content words
        query = query.lower().strip()
        
        # Define command patterns that should be removed
        command_patterns = [
            'search the web and find out about',
            'search the web for',
            'search for',
            'find out about',
            'look up',
            'search',
            'google',
            'find',
            'web',
            'look'
        ]
        
        # Remove command patterns (longer patterns first)
        command_patterns.sort(key=len, reverse=True)
        for pattern in command_patterns:
            # Whole-word match only: "website builders" / "finding nemo" used to
            # lose their first letters ("site builders", "ing nemo").
            if re.match(re.escape(pattern) + r'\b', query):
                remainder = query[len(pattern):].strip()
                if remainder:
                    query = remainder
                break
        
        # If still has command words at the start, remove them
        words = query.split()
        while words and words[0] in ['the', 'a', 'an']:
            words = words[1:]
        
        result = ' '.join(words) if words else query
        return result.strip()
    
    def _fallback_search(self, query):
        """Fallback search method when main scraping fails"""
        try:
            # Try DuckDuckGo instant answers API
            ddg_url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
            response = requests.get(ddg_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check for instant answer
                if data.get('AbstractText'):
                    result = f"Quick answer for '{query}':\n\n"
                    result += data['AbstractText']
                    if data.get('AbstractURL'):
                        result += f"\n\nSource: {data['AbstractURL']}"
                    return result
                
                # Check for related topics (entries may be groups: {"Name", "Topics": [...]})
                topics = []
                for topic in data.get('RelatedTopics') or []:
                    if not isinstance(topic, dict):
                        continue
                    group = topic.get('Topics') if isinstance(topic.get('Topics'), list) else [topic]
                    topics.extend(t for t in group if isinstance(t, dict) and t.get('Text'))
                if topics:
                    result = f"Related information for '{query}':\n\n"
                    for i, topic in enumerate(topics[:3], 1):
                        result += f"{i}. {topic['Text']}\n"
                        if topic.get('FirstURL'):
                            result += f"   Source: {topic['FirstURL']}\n"
                    return result
            
            # Final fallback - provide search URLs
            return f"""I couldn't retrieve search results for '{query}' right now, but you can search manually:

Google: https://www.google.com/search?q={quote(query)}
DuckDuckGo: https://duckduckgo.com/?q={quote(query)}
Bing: https://www.bing.com/search?q={quote(query)}

This might be due to network issues or search engine restrictions."""
            
        except Exception:
            return f"Search temporarily unavailable. You can search manually at: https://www.google.com/search?q={quote(query)}"
    
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
