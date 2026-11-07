import requests
from bs4 import BeautifulSoup
import html
import ipaddress
import re
import socket
import xml.etree.ElementTree as ET
from urllib.parse import quote, urljoin, urlparse, parse_qs
import time
import random

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_MAX_PAGE_BYTES = 5 * 1024 * 1024


def is_public_http_url(url):
    """True only for http(s) URLs whose host resolves to public addresses.

    Guards read_webpage against user/search-result text pointing at file://,
    localhost, the LAN or cloud metadata endpoints (SSRF-style reads)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def _google_href_to_url(href):
    """Resolve a Google result href (possibly a /url?q= redirect) to the target URL."""
    if href.startswith('/url?'):
        target = parse_qs(urlparse(href).query).get('q', [''])[0]
        return target if target.startswith('http') else ''
    return href if href.startswith('http') else ''


class WebScraperSkill:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.timeout = 15

    @staticmethod
    def _looks_blocked(response) -> bool:
        """Detect CAPTCHA/block pages (UC 9.1): a 200 page can still be a block."""
        if response.status_code in (429, 503):
            return True
        try:
            text = response.text[:5000].lower()
        except Exception:
            return False
        # 'enablejs' = Google's JavaScript wall served to non-JS clients.
        markers = ('/sorry/', 'captcha', 'unusual traffic', 'are you a robot', '/httpservice/retry/enablejs')
        return any(marker in text for marker in markers)

    def search_google(self, query, num_results=5):
        """Search Google and return results without opening browser"""
        try:
            # Use Google search URL with additional parameters for better results
            search_url = f"https://www.google.com/search?q={quote(query)}&num={num_results}&hl=en"

            # Add random delay to avoid being blocked
            time.sleep(random.uniform(1, 3))

            response = self.session.get(search_url, timeout=self.timeout)
            if self._looks_blocked(response):
                return self._try_alternative_search(query)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            results = []
            
            # Try multiple selectors for search results
            search_containers = (
                soup.find_all('div', class_='g') or
                soup.find_all('div', {'data-hveid': True}) or
                soup.find_all('div', class_='tF2Cxc') or
                soup.find_all('div', class_='kCrYT')
            )
            
            for container in search_containers[:num_results]:
                try:
                    # Get title - try multiple selectors
                    title_element = (
                        container.find('h3') or
                        container.find('h3', class_='LC20lb') or
                        container.find('h3', class_='r') or
                        container.find('a')
                    )
                    title = title_element.get_text() if title_element else "No title"
                    
                    # Get URL - try multiple selectors
                    link_element = (
                        container.find('a', href=True) or
                        container.find('a', {'data-ved': True})
                    )
                    url = ""
                    if link_element and link_element.get('href'):
                        # Unwraps (and percent-decodes) Google's /url?q= redirect
                        url = _google_href_to_url(link_element['href'])

                    # Get snippet - try multiple selectors
                    snippet_elements = (
                        container.find_all(['span', 'div'], class_=['st', 'VwiC3b', 'yXK7lf', 's3v9rd']) or
                        container.find_all(['span', 'div'], string=re.compile(r'.{20,}'))
                    )
                    snippet = ""
                    for elem in snippet_elements:
                        text = elem.get_text()
                        if len(text) > 30 and not any(skip in text.lower() for skip in ['javascript', 'cookie', 'privacy']):
                            snippet = text[:300]  # Limit snippet length
                            break

                    if title and len(title) > 2:  # Ensure we have meaningful content
                        results.append({
                            'title': title.strip(),
                            'url': url.strip(),
                            'snippet': snippet.strip()
                        })
                        
                except Exception:
                    continue
            
            # Also try to get featured snippet or direct answer
            featured_snippet = self._get_featured_snippet(soup)
            
            if results or featured_snippet:
                formatted_results = f"🔍 Search results for '{query}':\n\n"
                
                if featured_snippet:
                    formatted_results += f"📌 Featured Answer:\n{featured_snippet}\n\n"
                
                for i, result in enumerate(results, 1):
                    formatted_results += f"{i}. {result['title']}\n"
                    if result['url']:
                        formatted_results += f"   🔗 {result['url']}\n"
                    if result['snippet']:
                        formatted_results += f"   💬 {result['snippet']}\n"
                    formatted_results += "\n"
                
                return formatted_results.strip()
            else:
                return self._try_alternative_search(query)
                
        except Exception as e:
            return self._try_alternative_search(query)
    
    def _get_featured_snippet(self, soup):
        """Extract featured snippet from Google search results"""
        try:
            # Try different selectors for featured snippets
            featured_selectors = [
                'div[data-attrid="wa:/description"]',
                'div.kno-rdesc span',
                'div.Z0LcW',
                'div.hgKElc',
                'div.kp-blk',
                'span.hgKElc'
            ]
            
            for selector in featured_selectors:
                element = soup.select_one(selector)
                if element:
                    text = element.get_text().strip()
                    if len(text) > 20:
                        return text[:500]  # Limit length
            
            return None
            
        except Exception:
            return None
    
    def _try_alternative_search(self, query):
        """Try alternative search methods when Google fails"""
        try:
            # Try DuckDuckGo as fallback
            # html.duckduckgo.com is the canonical no-JS endpoint (duckduckgo.com/html
            # only redirects there). A 202 status is DDG's rate-limit/anomaly reply.
            ddg_url = f"{DDG_HTML_URL}?q={quote(query)}"
            response = self.session.get(ddg_url, timeout=self.timeout)
            
            if response.status_code == 200:
                probe = response.text[:5000].lower()
                ddg_blocked = ('captcha' in probe or 'anomaly' in probe
                               or 'challenge' in probe or 'duckduckbot' in probe)
                if ddg_blocked:
                    return (f"Search engines are currently blocking automated requests for '{query}'. "
                            f"Try these links:\n\n🔗 Google: https://www.google.com/search?q={quote(query)}\n🔗 DuckDuckGo: https://duckduckgo.com/?q={quote(query)}")
                soup = BeautifulSoup(response.content, 'html.parser')
                results = []
                
                # DuckDuckGo result containers
                organic = [d for d in soup.find_all('div', class_='result')
                           if 'result--ad' not in (d.get('class') or [])]
                for result_div in organic[:3]:
                    title_elem = result_div.find('a', class_='result__a')
                    snippet_elem = result_div.find('a', class_='result__snippet')
                    
                    if title_elem:
                        title = title_elem.get_text()
                        url = title_elem.get('href', '')
                        if url.startswith('//'):
                            url = 'https:' + url
                        if 'uddg=' in url:
                            params = parse_qs(urlparse(url).query)
                            if 'uddg' in params:
                                url = params['uddg'][0]
                        snippet = snippet_elem.get_text() if snippet_elem else ""
                        
                        results.append(f"• {title}\n  {url}\n  {snippet[:150]}...")
                
                if results:
                    return f"🔍 Search results for '{query}' (via DuckDuckGo):\n\n" + "\n\n".join(results)
            
            # Final fallback
            return f"Search temporarily unavailable for '{query}'. Try these links:\n\n🔗 Google: https://www.google.com/search?q={quote(query)}\n🔗 DuckDuckGo: https://duckduckgo.com/?q={quote(query)}"
            
        except Exception:
            return f"No search results found for '{query}'"
    
    def search_wikipedia(self, query):
        """Search Wikipedia and get article summary"""
        try:
            query = (query or '').strip()
            if not query:
                return "Please tell me what to look up on Wikipedia."
            # REST summary endpoint takes a title path segment: spaces -> '_', and
            # '/' must be escaped too (quote() keeps it by default: "AC/DC" broke).
            title_path = quote(query.replace(' ', '_'), safe='')
            search_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title_path}"
            
            response = self.session.get(search_url, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                
                title = data.get('title', 'Unknown')
                extract = data.get('extract') or 'No summary available'
                page_url = data.get('content_urls', {}).get('desktop', {}).get('page', '')
                
                result = f"Wikipedia: {title}\n\n"
                result += f"{extract}\n\n"
                if data.get('type') == 'disambiguation':
                    result += "That title is ambiguous; try a more specific name.\n\n"
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
            if response.status_code != 200:
                return f"Wikipedia is not responding right now (HTTP {response.status_code}). Please try again shortly."
            data = response.json()
            
            if 'query' in data and 'search' in data['query'] and data['query']['search']:
                page_title = data['query']['search'][0]['title']
                snippet = data['query']['search'][0]['snippet']
                
                # Clean HTML tags from snippet
                snippet = html.unescape(re.sub(r'<[^>]+>', '', snippet))
                
                return f"Wikipedia: {page_title}\n\n{snippet}\n\nFor full article, visit: https://en.wikipedia.org/wiki/{quote(page_title.replace(' ', '_'))}"
            else:
                return f"No Wikipedia article found for '{query}'"
                
        except requests.RequestException:
            return f"I couldn't reach Wikipedia to look up '{query}'. Please check your connection."
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
            response = self.session.get(url, params={'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'},
                                        timeout=self.timeout)
            if response.status_code != 200:
                return []
            # Parse RSS with the stdlib: BeautifulSoup's 'xml' mode needs lxml,
            # which is not in requirements.txt, so it raised and returned [].
            root = ET.fromstring(response.content)
            
            headlines = []
            for item in root.iter('item'):
                if len(headlines) >= limit:
                    break
                title = (item.findtext('title') or '').strip() or "No title"
                link = (item.findtext('link') or '').strip()
                description = item.findtext('description') or ''
                # Google News descriptions are HTML fragments; keep plain text.
                description = BeautifulSoup(description, 'html.parser').get_text(' ', strip=True)
                
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
            # Current BBC markup: <h2 data-testid="card-headline">; older: class*=headline.
            headline_elements = (
                soup.find_all(['h3', 'h2'], attrs={'data-testid': re.compile(r'headline')}) or
                soup.find_all(['h3', 'h2'], class_=re.compile(r'.*headline.*|.*title.*'))
            )
            
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
            
            if not is_public_http_url(url):
                return f"I can only read public web pages; '{url}' is a local or unsupported address."
            
            # Follow redirects by hand so every hop is checked *before* it is requested: a public
            # page must not be able to bounce a GET onto the router or another LAN device.
            target = url
            for _hop in range(6):
                response = self.session.get(target, timeout=self.timeout, allow_redirects=False, stream=True)
                if not response.is_redirect:
                    break
                target = urljoin(target, response.headers.get('Location', ''))
                response.close()
                if not is_public_http_url(target):
                    return f"I can only read public web pages; '{url}' redirected to a local address."
            else:
                return f"'{url}' redirected too many times."
            response.raise_for_status()
            body = b""
            for chunk in response.iter_content(64 * 1024):
                body += chunk
                if len(body) > _MAX_PAGE_BYTES:
                    break                              # enough to read; never buffer a huge download
            response.close()

            soup = BeautifulSoup(body, 'html.parser')
            
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
            
            if read_first and search_results.startswith("🔍 Search results for"):
                # First result URL: Google lines are "🔗 <url>", DDG lines are bare URLs.
                # (Previously looked for a "Google search results"/"URL:" format that
                # search_google never produces, so nothing was ever read.)
                match = re.search(r'^\s*(?:🔗\s*)?(https?://\S+)\s*$', search_results, re.MULTILINE)
                first_url = match.group(1) if match else None
                
                if first_url:
                    # Add a delay to be respectful
                    time.sleep(1)
                    
                    webpage_content = self.read_webpage(first_url)
                    
                    return f"{search_results}\n\n--- Content from first result ---\n\n{webpage_content}"
            
            return search_results
            
        except Exception as e:
            return f"Error in search and read: {e}"
    
    def search_specific_site(self, query, site):
        """Search within a specific website"""
        try:
            # Use Google site search
            site_query = f"site:{site} {query}"
            return self.search_google(site_query, num_results=3)
            
        except Exception as e:
            return f"Error searching {site}: {e}"
    
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
                    return f"Quick fact about {topic}: {sentences[0].rstrip('.')}."
            
            # Fallback to Google search
            search_result = self.search_google(f"what is {topic}", num_results=1)
            return search_result
            
        except Exception as e:
            return f"Error getting fact about {topic}: {e}"
