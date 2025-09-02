import webbrowser
import subprocess
import platform
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
            
            # Clean up any remaining markdown symbols that might have been generated
            cleaned_summary = summary.replace('*', '').replace('#', '').replace('**', '').replace('---', '')
            
            # Remove excessive bullet points and format cleanly
            lines = cleaned_summary.split('\n')
            clean_lines = []
            for line in lines:
                line = line.strip()
                if line:
                    # Remove bullet point symbols
                    line = line.replace('• ', '').replace('- ', '').replace('* ', '')
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
            if query.startswith(pattern):
                query = query[len(pattern):].strip()
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
                
                # Check for related topics
                if data.get('RelatedTopics'):
                    result = f"Related information for '{query}':\n\n"
                    for i, topic in enumerate(data['RelatedTopics'][:3], 1):
                        if isinstance(topic, dict) and topic.get('Text'):
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
    
    def _extract_urls_from_results(self, search_results):
        """Extract URLs from search results text"""
        import re
        # Find URLs in the search results
        url_pattern = r'🔗 (https?://[^\s\n]+)'
        urls = re.findall(url_pattern, search_results)
        return urls
    
    def _create_comprehensive_summary(self, query, urls, llm_brain=None):
        """Create comprehensive summary by scraping content from multiple URLs and using LLM for summarization"""
        summaries = []
        successful_scrapes = 0
        all_content = []
        
        summary_header = f"📋 **Comprehensive Summary for '{query}'**\n"
        summary_header += f"📊 Analyzed {len(urls)} sources\n\n"
        
        for i, url in enumerate(urls, 1):
            if successful_scrapes >= 6:  # Limit to top 6 successful scrapes
                break
                
            try:
                content = self._scrape_website_content(url)
                if content and len(content.strip()) > 100:  # Only include substantial content
                    successful_scrapes += 1
                    domain = self._extract_domain(url)
                    
                    # Store content for LLM summarization
                    all_content.append({
                        'domain': domain,
                        'url': url,
                        'content': content[:2000]  # Limit content length for LLM
                    })
                    
            except Exception as e:
                continue  # Skip failed scrapes
        
        if all_content and llm_brain:
            # Use LLM to create comprehensive summary
            try:
                combined_content = ""
                for item in all_content:
                    combined_content += f"\n\nSource: {item['domain']} ({item['url']})\nContent: {item['content']}\n"
                
                prompt = f"""Please create a comprehensive summary of the following web search results for the query "{query}". 

Analyze the content from these {len(all_content)} sources and provide:
1. A brief overview of the topic
2. Key information from each source
3. Any important details, dates, or facts
4. Conclusion with the most relevant information

Sources and content:
{combined_content}

Please format the response clearly with sections and include source references."""

                llm_summary = llm_brain.process_command(prompt, use_context=False)
                
                # Add source list at the end
                source_list = "\n\n📚 **Sources:**\n"
                for i, item in enumerate(all_content, 1):
                    source_list += f"{i}. {item['domain']} - {item['url']}\n"
                
                return summary_header + llm_summary + source_list
                
            except Exception as e:
                # Fallback to manual summary if LLM fails
                pass
        
        # Fallback: Create manual summary if LLM not available or fails
        if all_content:
            result = summary_header
            for i, item in enumerate(all_content, 1):
                summary_item = f"## {i}. {item['domain']}\n"
                summary_item += f"🔗 **Source:** {item['url']}\n\n"
                summary_item += f"📄 **Content:**\n{item['content'][:800]}{'...' if len(item['content']) > 800 else ''}\n\n"
                summary_item += "---\n\n"
                result += summary_item
            
            result += f"✅ **Summary complete** - Successfully analyzed {len(all_content)} sources"
            return result
        else:
            # Fallback to original search results if scraping fails
            return f"⚠️ Could not scrape detailed content. Here are the search results:\n\n{self.scraper.search_google(query, num_results=6)}"
    
    def _scrape_website_content(self, url):
        """Scrape and summarize content from a website"""
        try:
            import requests
            from bs4 import BeautifulSoup
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                element.decompose()
            
            # Extract text from main content areas
            content_selectors = [
                'main', 'article', '.content', '.post', '.entry',
                '.article-content', '.post-content', '#content'
            ]
            
            text_content = ""
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    text_content = elements[0].get_text()
                    break
            
            # If no main content found, get all paragraph text
            if not text_content:
                paragraphs = soup.find_all('p')
                text_content = ' '.join([p.get_text() for p in paragraphs])
            
            # Clean and format the text
            lines = text_content.split('\n')
            cleaned_lines = [line.strip() for line in lines if line.strip()]
            cleaned_text = ' '.join(cleaned_lines)
            
            # Remove extra whitespace
            import re
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
            
            return cleaned_text.strip()
            
        except Exception as e:
            return None
    
    def _extract_domain(self, url):
        """Extract domain name from URL"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain.title()
        except:
            return "Unknown Source"
    
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
