import requests
from bs4 import BeautifulSoup
import json
import re
from urllib.parse import quote, urljoin, urlparse
from datetime import datetime
import time
import random

class WebScraperSkill:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.timeout = 15
        
    def search_google(self, query, num_results=5):
        """Search Google and return results without opening browser"""
        try:
            # Use Google search URL
            search_url = f"https://www.google.com/search?q={quote(query)}&num={num_results}"
            
            response = self.session.get(search_url, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            results = []
            
            # Find search result containers
            search_containers = soup.find_all('div', class_='g')
            
            for container in search_containers[:num_results]:
                try:
                    # Get title
                    title_element = container.find('h3')
                    title = title_element.get_text() if title_element else "No title"
                    
                    # Get URL
                    link_element = container.find('a', href=True)
                    url = link_element['href'] if link_element else ""
                    
                    # Get snippet
                    snippet_elements = container.find_all(['span', 'div'], class_=['st', 'VwiC3b'])
                    snippet = ""
                    for elem in snippet_elements:
                        text = elem.get_text()
                        if len(text) > 20:  # Filter out very short text
                            snippet = text
                            break
                    
                    if title and url:
                        results.append({
                            'title': title,
                            'url': url,
                            'snippet': snippet
                        })
                        
                except Exception:
                    continue
            
            if results:
                formatted_results = f"Google search results for '{query}':\n\n"
                for i, result in enumerate(results, 1):
                    formatted_results += f"{i}. {result['title']}\n"
                    formatted_results += f"   URL: {result['url']}\n"
                    if result['snippet']:
                        formatted_results += f"   Summary: {result['snippet'][:200]}...\n"
                    formatted_results += "\n"
                
                return formatted_results.strip()
            else:
                return f"No search results found for '{query}'"
                
        except Exception as e:
            return f"Error searching Google: {e}"
    
    def search_wikipedia(self, query):
        """Search Wikipedia and get article summary"""
        try:
            # Use Wikipedia API for search
            search_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(query)}"
            
            response = self.session.get(search_url, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                
                title = data.get('title', 'Unknown')
                extract = data.get('extract', 'No summary available')
                page_url = data.get('content_urls', {}).get('desktop', {}).get('page', '')
                
                result = f"Wikipedia: {title}\n\n"
                result += f"{extract}\n\n"
                if page_url:
                    result += f"Full article: {page_url}"
                
                return result
            else:
                # Fallback to search API
                return self._wikipedia_search_fallback(query)
                
        except Exception:
            return self._wikipedia_search_fallback(query)
    
    def _wikipedia_search_fallback(self, query):
        """Fallback Wikipedia search"""
        try:
            search_url = f"https://en.wikipedia.org/w/api.php"
            params = {
                'action': 'query',
                'format': 'json',
                'list': 'search',
                'srsearch': query,
                'srlimit': 1
            }
            
            response = self.session.get(search_url, params=params, timeout=self.timeout)
            data = response.json()
            
            if 'query' in data and 'search' in data['query'] and data['query']['search']:
                page_title = data['query']['search'][0]['title']
                snippet = data['query']['search'][0]['snippet']
                
                # Clean HTML tags from snippet
                snippet = re.sub(r'<[^>]+>', '', snippet)
                
                return f"Wikipedia: {page_title}\n\n{snippet}\n\nFor full article, visit: https://en.wikipedia.org/wiki/{quote(page_title.replace(' ', '_'))}"
            else:
                return f"No Wikipedia article found for '{query}'"
                
        except Exception as e:
            return f"Error searching Wikipedia: {e}"
    
    def get_news_headlines(self, source="general", limit=5):
        """Get news headlines from various sources"""
        try:
            headlines = []
            
            if source.lower() == "general" or source.lower() == "google":
                # Google News
                headlines.extend(self._get_google_news(limit))
            
            if source.lower() == "bbc" or source.lower() == "general":
                # BBC News
                headlines.extend(self._get_bbc_news(limit))
            
            if source.lower() == "reuters" or source.lower() == "general":
                # Reuters
                headlines.extend(self._get_reuters_news(limit))
            
            if headlines:
                result = f"Latest News Headlines ({source}):\n\n"
                for i, headline in enumerate(headlines[:limit], 1):
                    result += f"{i}. {headline['title']}\n"
                    if headline.get('summary'):
                        result += f"   {headline['summary'][:150]}...\n"
                    if headline.get('url'):
                        result += f"   Source: {headline['url']}\n"
                    result += "\n"
                
                return result.strip()
            else:
                return f"Unable to fetch news headlines from {source}"
                
        except Exception as e:
            return f"Error fetching news: {e}"
    
    def _get_google_news(self, limit):
        """Get news from Google News"""
        try:
            url = "https://news.google.com/rss"
            response = self.session.get(url, timeout=self.timeout)
            
            soup = BeautifulSoup(response.content, 'xml')
            items = soup.find_all('item')
            
            headlines = []
            for item in items[:limit]:
                title = item.find('title').text if item.find('title') else "No title"
                link = item.find('link').text if item.find('link') else ""
                description = item.find('description').text if item.find('description') else ""
                
                headlines.append({
                    'title': title,
                    'url': link,
                    'summary': description
                })
            
            return headlines
            
        except Exception:
            return []
    
    def _get_bbc_news(self, limit):
        """Get news from BBC"""
        try:
            url = "https://www.bbc.com/news"
            response = self.session.get(url, timeout=self.timeout)
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            headlines = []
            # Look for BBC news headlines
            headline_elements = soup.find_all(['h3', 'h2'], class_=re.compile(r'.*headline.*|.*title.*'))
            
            for elem in headline_elements[:limit]:
                title = elem.get_text().strip()
                if len(title) > 10:  # Filter out very short titles
                    parent = elem.find_parent('a')
                    url = ""
                    if parent and parent.get('href'):
                        url = urljoin('https://www.bbc.com', parent['href'])
                    
                    headlines.append({
                        'title': title,
                        'url': url,
                        'summary': ""
                    })
            
            return headlines
            
        except Exception:
            return []
    
    def _get_reuters_news(self, limit):
        """Get news from Reuters"""
        try:
            url = "https://www.reuters.com"
            response = self.session.get(url, timeout=self.timeout)
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            headlines = []
            # Look for Reuters headlines
            headline_elements = soup.find_all('a', attrs={'data-testid': re.compile(r'.*Heading.*')})
            
            for elem in headline_elements[:limit]:
                title = elem.get_text().strip()
                if len(title) > 10:
                    url = urljoin('https://www.reuters.com', elem.get('href', ''))
                    
                    headlines.append({
                        'title': title,
                        'url': url,
                        'summary': ""
                    })
            
            return headlines
            
        except Exception:
            return []
    
    def read_webpage(self, url, summarize=True):
        """Read and optionally summarize a webpage"""
        try:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get page title
            title = soup.find('title')
            title_text = title.get_text() if title else "No title"
            
            # Extract main content
            content_selectors = [
                'article', 'main', '.content', '#content', 
                '.post-content', '.entry-content', '.article-body'
            ]
            
            content = ""
            for selector in content_selectors:
                content_elem = soup.select_one(selector)
                if content_elem:
                    content = content_elem.get_text()
                    break
            
            if not content:
                # Fallback to body content
                body = soup.find('body')
                if body:
                    content = body.get_text()
            
            # Clean up the content
            content = re.sub(r'\s+', ' ', content).strip()
            
            if summarize and len(content) > 500:
                # Simple summarization - get first few paragraphs
                sentences = content.split('. ')
                summary = '. '.join(sentences[:5]) + '.'
                
                result = f"Page: {title_text}\nURL: {url}\n\nSummary:\n{summary}\n\n"
                result += f"Full content length: {len(content)} characters"
                
                return result
            else:
                return f"Page: {title_text}\nURL: {url}\n\nContent:\n{content[:2000]}{'...' if len(content) > 2000 else ''}"
                
        except Exception as e:
            return f"Error reading webpage '{url}': {e}"
    
    def search_and_read(self, query, read_first=True):
        """Search Google and optionally read the first result"""
        try:
            # First search Google
            search_results = self.search_google(query, num_results=3)
            
            if read_first and "Google search results" in search_results:
                # Extract first URL from search results
                lines = search_results.split('\n')
                first_url = None
                
                for line in lines:
                    if line.strip().startswith('URL:'):
                        first_url = line.split('URL:', 1)[1].strip()
                        break
                
                if first_url:
                    # Add a delay to be respectful
                    time.sleep(1)
                    
                    webpage_content = self.read_webpage(first_url)
                    
                    return f"{search_results}\n\n--- Content from first result ---\n\n{webpage_content}"
            
            return search_results
            
        except Exception as e:
            return f"Error in search and read: {e}"
    
    def get_weather_from_web(self, city=""):
        """Alternative weather scraping (backup for weather skill)"""
        try:
            if city:
                url = f"https://wttr.in/{city}?format=%l:+%C+%t+%h+%w+%p"
            else:
                url = "https://wttr.in/?format=%l:+%C+%t+%h+%w+%p"
            
            headers = {'User-Agent': 'curl/7.68.0'}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return f"Weather: {response.text.strip()}"
            else:
                return "Unable to fetch weather data"
                
        except Exception as e:
            return f"Weather fetch error: {e}"
    
    def search_specific_site(self, query, site):
        """Search within a specific website"""
        try:
            # Use Google site search
            site_query = f"site:{site} {query}"
            return self.search_google(site_query, num_results=3)
            
        except Exception as e:
            return f"Error searching {site}: {e}"
    
    def get_stock_info(self, symbol):
        """Get basic stock information"""
        try:
            # Simple stock info from Yahoo Finance
            url = f"https://finance.yahoo.com/quote/{symbol.upper()}"
            
            response = self.session.get(url, timeout=self.timeout)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try to extract stock price
            price_elem = soup.find('fin-streamer', {'data-field': 'regularMarketPrice'})
            if not price_elem:
                price_elem = soup.find('span', class_=re.compile(r'.*price.*'))
            
            if price_elem:
                price = price_elem.get_text()
                return f"{symbol.upper()} stock price: {price}"
            else:
                return f"Could not fetch stock price for {symbol.upper()}"
                
        except Exception as e:
            return f"Error fetching stock info: {e}"
    
    def quick_fact(self, topic):
        """Get a quick fact about something using Wikipedia"""
        try:
            wiki_result = self.search_wikipedia(topic)
            
            if "No Wikipedia article found" not in wiki_result:
                # Extract just the first sentence or two
                lines = wiki_result.split('\n')
                if len(lines) >= 3:
                    fact = lines[2]  # Skip title and empty line
                    sentences = fact.split('. ')
                    return f"Quick fact about {topic}: {sentences[0]}."
            
            # Fallback to Google search
            search_result = self.search_google(f"what is {topic}", num_results=1)
            return search_result
            
        except Exception as e:
            return f"Error getting fact about {topic}: {e}"
