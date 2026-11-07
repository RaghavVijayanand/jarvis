"""Offline coverage for web search/scraping, Ollama management and the legacy
automation skill. All network/process access is mocked at the boundary."""
import json
import socket
import subprocess
import unittest
from collections import namedtuple
from unittest.mock import Mock, patch

import requests

from skills.web_scraper import WebScraperSkill, is_public_http_url
from skills.web_search import WebSearchSkill


def resp(status=200, text='', content=None, json_data=None, url=None):
    r = Mock()
    r.status_code = status
    if json_data is not None and not text:
        text = json.dumps(json_data)
    r.text = text
    r.content = content if content is not None else text.encode('utf-8')
    r.url = url
    r.is_redirect = 300 <= status < 400
    r.headers = {}
    r.iter_content = Mock(side_effect=lambda *a, **k: iter([r.content]))
    if json_data is not None:
        r.json = Mock(return_value=json_data)
    else:
        r.json = Mock(side_effect=ValueError('Expecting value: line 1 column 1 (char 0)'))
    if status >= 400:
        r.raise_for_status = Mock(side_effect=requests.HTTPError(f'{status} Client Error'))
    else:
        r.raise_for_status = Mock()
    return r


def public_dns(host, *a, **k):
    table = {'example.com': '93.184.215.14', 'www.example.com': '93.184.215.14',
             'news.example.org': '151.101.0.81', 'localhost': '127.0.0.1',
             'router.lan': '192.168.1.1', 'metadata.google.internal': '169.254.169.254',
             'evil.example.net': '10.0.0.5'}
    if host not in table:
        raise socket.gaierror('Name or service not known')
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (table[host], 0))]


# ── Realistic payloads ─────────────────────────────────────────────────────

GOOGLE_HTML = '''<html><body><div id="search">
<div class="g"><div class="tF2Cxc">
  <a href="/url?q=https://www.python.org/downloads/%3Fsource%3Dg&amp;sa=U&amp;ved=2ah"><h3 class="LC20lb">Download Python | Python.org</h3></a>
  <div class="VwiC3b">The official home of the Python Programming Language. Download the latest release.</div>
</div></div>
<div class="g"><a href="https://docs.python.org/3/"><h3>3.13 Documentation</h3></a>
  <span class="VwiC3b">Welcome! This is the official documentation for Python 3.13.</span></div>
</div></body></html>'''

GOOGLE_JS_WALL = ('<html><head><noscript><meta content="0;url=/httpservice/retry/enablejs?sei=abc" '
                  'http-equiv="refresh"></noscript></head><body>If you\'re having trouble accessing '
                  'Google Search, please click here</body></html>')

DDG_HTML = '''<!DOCTYPE html><html><body><div class="serp__results"><div id="links" class="results">
<div class="result results_links results_links_deep result--ad">
  <div class="links_main links_deep result__body"><h2 class="result__title">
  <a rel="nofollow" class="result__a" href="https://duckduckgo.com/y.js?ad_domain=ads.example&amp;ad_provider=bingv7aa">Sponsored Thing</a></h2>
  <a class="result__snippet" href="https://duckduckgo.com/y.js?x">Buy now.</a></div></div>
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body"><h2 class="result__title">
  <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2F&amp;rut=6f1a">Welcome to Python.org</a></h2>
  <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2F">The official home of the <b>Python</b> Programming Language.</a></div></div>
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body"><h2 class="result__title">
  <a rel="nofollow" class="result__a" href="https://en.wikipedia.org/wiki/Python_(programming_language)">Python (programming language) - Wikipedia</a></h2>
  <a class="result__snippet">Python is a high-level, general-purpose programming language.</a></div></div>
</div></div></body></html>'''

DDG_ANOMALY = ('<html><body><div class="anomaly-modal__title">Unfortunately, bots use DuckDuckGo too.</div>'
               '<div>Please complete the following challenge to confirm this search was made by a human.</div></body></html>')

WIKI_SUMMARY = {
    "type": "standard", "title": "Python (programming language)",
    "displaytitle": "<span class=\"mw-page-title-main\">Python (programming language)</span>",
    "pageid": 23862, "lang": "en", "dir": "ltr",
    "description": "General-purpose programming language",
    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Python_(programming_language)"},
                     "mobile": {"page": "https://en.m.wikipedia.org/wiki/Python_(programming_language)"}},
    "extract": "Python is a high-level, general-purpose programming language. Its design philosophy "
               "emphasizes code readability with the use of significant indentation.",
}

WIKI_DISAMBIG = {
    "type": "disambiguation", "title": "Mercury",
    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Mercury"}},
    "extract": "Mercury most commonly refers to:",
}

WIKI_404 = {"type": "https://mediawiki.org/wiki/HyperSwitch/errors/not_found", "title": "Not found.",
            "method": "get", "detail": "Page or revision not found.", "uri": "/en.wikipedia.org/v1/page/summary/Xq"}

WIKI_SEARCH = {"batchcomplete": "", "continue": {"sroffset": 1, "continue": "-||"},
               "query": {"searchinfo": {"totalhits": 5210},
                         "search": [{"ns": 0, "title": "Albert Einstein", "pageid": 736, "size": 230000,
                                     "wordcount": 21000,
                                     "snippet": "<span class=\"searchmatch\">Albert</span> <span class=\"searchmatch\">Einstein</span> was a German-born theoretical physicist &quot;best known&quot;",
                                     "timestamp": "2026-09-01T10:00:00Z"}]}}

WIKI_SEARCH_EMPTY = {"batchcomplete": "", "query": {"searchinfo": {"totalhits": 0}, "search": []}}

GNEWS_RSS = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<rss xmlns:media="http://search.yahoo.com/mrss/" version="2.0"><channel>
<generator>NFE/5.0</generator><title>Top stories - Google News</title>
<link>https://news.google.com/?hl=en-US&amp;gl=US&amp;ceid=US:en</link>
<item><title>Markets rally as inflation cools - Reuters</title>
<link>https://news.google.com/rss/articles/CBMiAAA?oc=5</link>
<guid isPermaLink="false">CBMiAAA</guid><pubDate>Wed, 23 Sep 2026 12:00:00 GMT</pubDate>
<description>&lt;a href="https://news.google.com/rss/articles/CBMiAAA?oc=5" target="_blank"&gt;Markets rally as inflation cools&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;Reuters&lt;/font&gt;</description>
<source url="https://www.reuters.com">Reuters</source></item>
<item><title>Storm season update \xe2\x80\x94 caf\xc3\xa9 owners prepare</title>
<link>https://news.google.com/rss/articles/CBMiBBB?oc=5</link><description>Short</description></item>
</channel></rss>'''

BBC_HTML = '''<html><body>
<a href="/news/articles/c1"><div><h2 data-testid="card-headline" class="sc-8ea7699c-3 dhclWg">Leaders meet for climate summit talks</h2></div></a>
<a href="/news/articles/c2"><h2 data-testid="card-headline">Short</h2></a>
</body></html>'''

REUTERS_HTML = '''<html><body>
<a data-testid="Heading" href="/world/some-long-story-2026-09-23/">A long Reuters headline about the world</a>
</body></html>'''

ARTICLE_HTML = ('<html><head><title>Example Article</title><script>var x=1;</script></head><body>'
                '<nav>Menu</nav><article><p>' + 'This is a sentence about things. ' * 40 + '</p></article></body></html>')

DDG_INSTANT = {"Abstract": "", "AbstractText": "Python is a high-level programming language.",
               "AbstractURL": "https://en.wikipedia.org/wiki/Python_(programming_language)",
               "Heading": "Python", "RelatedTopics": []}
DDG_INSTANT_GROUPS = {"AbstractText": "", "RelatedTopics": [
    {"Name": "Programming", "Topics": [
        {"FirstURL": "https://duckduckgo.com/Python_(programming_language)",
         "Text": "Python (programming language) A high-level programming language."}]},
    {"FirstURL": "https://duckduckgo.com/Monty_Python", "Text": "Monty Python British comedy troupe."}]}
DDG_INSTANT_EMPTY = {"AbstractText": "", "RelatedTopics": [{"Name": "Empty", "Topics": []}]}

OLLAMA_TAGS = {"models": [
    {"name": "llama3.2:3b", "model": "llama3.2:3b", "modified_at": "2026-08-01T10:00:00.0-07:00",
     "size": 2019393189, "digest": "a80c4f17acd5",
     "details": {"format": "gguf", "family": "llama", "parameter_size": "3.2B", "quantization_level": "Q4_K_M"}},
    {"name": "qwen2.5vl:3b", "model": "qwen2.5vl:3b", "size": 3200000000, "digest": "fb90415cde1e",
     "details": {"family": "qwen25vl"}},
    {"name": "", "model": ""}]}

GIB = 1024 * 1024 * 1024
PULL_LINES = [
    b'{"status":"pulling manifest"}',
    b'',
    b'{"status":"pulling fb90415cde1e","digest":"sha256:fb90415cde1e","total":2147483648}',
    b'{"status":"pulling fb90415cde1e","digest":"sha256:fb90415cde1e","total":2147483648,"completed":536870912}',
    b'{"status":"pulling fb90415cde1e","digest":"sha256:fb90415cde1e","total":2147483648,"completed":1181116006}',
    b'{"status":"pulling fb90415cde1e","digest":"sha256:fb90415cde1e","total":2147483648,"completed":2147483648}',
    b'not json',
    b'{"status":"verifying sha256 digest"}',
    b'{"status":"writing manifest"}',
    b'{"status":"success"}',
]


# ── WebScraperSkill ───────────────────────────────────────────────────────

class ScraperTests(unittest.TestCase):
    def setUp(self):
        self.s = WebScraperSkill()
        p = patch('skills.web_scraper.time.sleep')
        p.start()
        self.addCleanup(p.stop)

    def test_google_results_parsed_and_redirect_decoded(self):
        with patch.object(self.s.session, 'get', return_value=resp(200, GOOGLE_HTML)):
            out = self.s.search_google('python', num_results=5)
        self.assertIn('Download Python | Python.org', out)
        self.assertIn('https://www.python.org/downloads/?source=g', out)
        self.assertNotIn('&sa=U', out)
        self.assertIn('https://docs.python.org/3/', out)
        self.assertIn('official home', out)

    def test_google_js_wall_falls_back_to_ddg_skipping_ads(self):
        with patch.object(self.s.session, 'get', side_effect=[resp(200, GOOGLE_JS_WALL), resp(200, DDG_HTML)]) as g:
            out = self.s.search_google('python')
        self.assertIn('(via DuckDuckGo)', out)
        self.assertIn('https://www.python.org/', out)
        self.assertIn('Python (programming language) - Wikipedia', out)
        self.assertNotIn('Sponsored', out)
        self.assertTrue(g.call_args_list[1].args[0].startswith('https://html.duckduckgo.com/html/?q=python'))

    def test_google_429_timeout_and_empty_page(self):
        with patch.object(self.s.session, 'get', side_effect=[resp(429, 'Too Many Requests'), resp(202, DDG_ANOMALY)]):
            self.assertIn('Search temporarily unavailable', self.s.search_google('x'))
        with patch.object(self.s.session, 'get', side_effect=requests.Timeout('read timed out')):
            self.assertIn("No search results found for 'x'", self.s.search_google('x'))
        with patch.object(self.s.session, 'get', side_effect=[resp(200, '<html><body>nothing</body></html>'),
                                                            resp(200, DDG_ANOMALY)]):
            self.assertIn('blocking automated requests', self.s.search_google('x'))

    def test_google_bad_html_does_not_raise(self):
        with patch.object(self.s.session, 'get', side_effect=[resp(200, '<div class="g"><<<>>'), resp(500, '')]):
            out = self.s.search_google('x')
        self.assertIsInstance(out, str)

    def test_featured_snippet(self):
        html_doc = ('<div class="g"><a href="https://a.example/"><h3>Title here</h3></a></div>'
                    '<div class="hgKElc">Paris is the capital and largest city of France.</div>')
        with patch.object(self.s.session, 'get', return_value=resp(200, html_doc)):
            out = self.s.search_google('capital of france')
        self.assertIn('Featured Answer', out)
        self.assertIsNone(self.s._get_featured_snippet(None))

    def test_ddg_empty_results_gives_links(self):
        with patch.object(self.s.session, 'get', return_value=resp(200, '<html><body>No results.</body></html>')):
            out = self.s._try_alternative_search('zzqx')
        self.assertIn('Search temporarily unavailable', out)

    def test_wikipedia_summary(self):
        with patch.object(self.s.session, 'get', return_value=resp(200, json_data=WIKI_SUMMARY)) as g:
            out = self.s.search_wikipedia('Python (programming language)')
        self.assertIn('Wikipedia: Python (programming language)', out)
        self.assertIn('high-level', out)
        self.assertIn('Full article: https://en.wikipedia.org/wiki/Python_(programming_language)', out)
        self.assertTrue(g.call_args.args[0].endswith('/page/summary/Python_%28programming_language%29'))

    def test_wikipedia_slash_title_is_escaped(self):
        with patch.object(self.s.session, 'get', return_value=resp(200, json_data=WIKI_SUMMARY)) as g:
            self.s.search_wikipedia('AC/DC')
        self.assertTrue(g.call_args.args[0].endswith('/page/summary/AC%2FDC'))

    def test_wikipedia_disambiguation_and_empty(self):
        with patch.object(self.s.session, 'get', return_value=resp(200, json_data=WIKI_DISAMBIG)):
            self.assertIn('ambiguous', self.s.search_wikipedia('mercury'))
        self.assertIn('what to look up', self.s.search_wikipedia('  '))

    def test_wikipedia_404_uses_search_api(self):
        with patch.object(self.s.session, 'get', side_effect=[resp(404, json_data=WIKI_404),
                                                            resp(200, json_data=WIKI_SEARCH)]) as g:
            out = self.s.search_wikipedia('albert einstein physicist')
        self.assertIn('Wikipedia: Albert Einstein', out)
        self.assertIn('"best known"', out)
        self.assertNotIn('<span', out)
        self.assertIn('https://en.wikipedia.org/wiki/Albert_Einstein', out)
        self.assertEqual(g.call_args.kwargs['params']['list'], 'search')

    def test_wikipedia_failures_are_friendly(self):
        with patch.object(self.s.session, 'get', side_effect=[resp(404, json_data=WIKI_404),
                                                            resp(200, json_data=WIKI_SEARCH_EMPTY)]):
            self.assertIn("No Wikipedia article found for 'qqzx'", self.s.search_wikipedia('qqzx'))
        with patch.object(self.s.session, 'get', side_effect=[resp(429, 'Too many requests'),
                                                            resp(429, '<html>Too many requests</html>')]):
            self.assertIn('not responding', self.s.search_wikipedia('x'))
        with patch.object(self.s.session, 'get', side_effect=requests.ConnectionError('offline')):
            self.assertIn("couldn't reach Wikipedia", self.s.search_wikipedia('x'))
        with patch.object(self.s.session, 'get', return_value=resp(200, '<html>maintenance</html>')):
            out = self.s.search_wikipedia('x')
        self.assertIn('Error searching Wikipedia', out)

    def test_news_headlines_all_sources(self):
        def fake_get(url, **kw):
            if 'news.google.com' in url:
                return resp(200, content=GNEWS_RSS, text='')
            if 'bbc' in url:
                return resp(200, BBC_HTML)
            return resp(200, REUTERS_HTML)
        with patch.object(self.s.session, 'get', side_effect=fake_get):
            out = self.s.get_news_headlines('general', limit=10)
        self.assertIn('Markets rally as inflation cools - Reuters', out)
        self.assertIn('café owners', out)
        self.assertNotIn('&lt;a', out)
        self.assertNotIn('<font', out)
        self.assertIn('Leaders meet for climate summit talks', out)
        self.assertIn('https://www.bbc.com/news/articles/c1', out)
        self.assertIn('https://www.reuters.com/world/some-long-story-2026-09-23/', out)
        self.assertNotIn('Short\n', out.split('Leaders')[1])

    def test_news_failures(self):
        with patch.object(self.s.session, 'get', side_effect=requests.Timeout('t')):
            self.assertEqual(self.s.get_news_headlines('general'), 'Unable to fetch news headlines from general')
        with patch.object(self.s.session, 'get', return_value=resp(503, 'down')):
            self.assertEqual(self.s._get_google_news(5), [])
        with patch.object(self.s.session, 'get', return_value=resp(200, content=b'<rss><not-closed>', text='')):
            self.assertEqual(self.s._get_google_news(5), [])
        with patch.object(self.s, '_get_google_news', side_effect=RuntimeError('x')):
            self.assertIn('Error fetching news', self.s.get_news_headlines('google'))

    def test_read_webpage_summary_and_short(self):
        with patch('skills.web_scraper.socket.getaddrinfo', side_effect=public_dns), \
             patch.object(self.s.session, 'get', return_value=resp(200, ARTICLE_HTML, url='https://example.com/a')):
            out = self.s.read_webpage('example.com/a')
        self.assertIn('Page: Example Article', out)
        self.assertIn('URL: https://example.com/a', out)
        self.assertIn('Summary:', out)
        self.assertNotIn('var x', out)
        short = '<html><head><title>T</title></head><body><p>Tiny page.</p></body></html>'
        with patch('skills.web_scraper.socket.getaddrinfo', side_effect=public_dns), \
             patch.object(self.s.session, 'get', return_value=resp(200, short, url='https://example.com/')):
            out = self.s.read_webpage('https://example.com/')
        self.assertIn('Content:\nTiny page.', out)

    def test_read_webpage_blocks_local_targets(self):
        with patch('skills.web_scraper.socket.getaddrinfo', side_effect=public_dns), \
             patch.object(self.s.session, 'get') as g:
            for target in ('file:///C:/Windows/win.ini', 'http://localhost:11434/api/tags',
                           'http://127.0.0.1/', 'http://169.254.169.254/latest/meta-data/',
                           'http://router.lan/admin', 'http://[::1]:8080/', 'ftp://example.com/x',
                           'http://metadata.google.internal/', 'http://unknown-host.invalid/'):
                self.assertIn('public web pages', self.s.read_webpage(target), target)
            g.assert_not_called()

    def test_read_webpage_redirect_to_private_and_http_error(self):
        bounce = resp(302, '', url='https://example.com/r')
        bounce.headers = {'Location': 'http://evil.example.net/admin'}
        with patch('skills.web_scraper.socket.getaddrinfo', side_effect=public_dns), \
             patch.object(self.s.session, 'get', return_value=bounce) as g:
            self.assertIn('redirected to a local address', self.s.read_webpage('https://example.com/r'))
        g.assert_called_once()           # the private address itself is never requested
        with patch('skills.web_scraper.socket.getaddrinfo', side_effect=public_dns), \
             patch.object(self.s.session, 'get', return_value=resp(404, 'nf', url='https://example.com/x')):
            self.assertIn("Error reading webpage 'https://example.com/x'", self.s.read_webpage('https://example.com/x'))

    def test_is_public_http_url(self):
        with patch('skills.web_scraper.socket.getaddrinfo', side_effect=public_dns):
            self.assertTrue(is_public_http_url('https://example.com/path?q=1'))
            self.assertFalse(is_public_http_url('https://printer.local/'))
            self.assertFalse(is_public_http_url('http://[not-an-ip/'))
        with patch('skills.web_scraper.socket.getaddrinfo',
                   return_value=[(2, 1, 6, '', ('not-an-ip', 0))]):
            self.assertFalse(is_public_http_url('https://example.com/'))

    def test_search_and_read_reads_first_result(self):
        with patch.object(self.s, 'search_google', return_value=(
                "🔍 Search results for 'py':\n\n1. Python\n   🔗 https://www.python.org/\n   💬 snip")), \
             patch.object(self.s, 'read_webpage', return_value='PAGE') as rw:
            out = self.s.search_and_read('py')
        rw.assert_called_once_with('https://www.python.org/')
        self.assertIn('--- Content from first result ---\n\nPAGE', out)
        ddg = "🔍 Search results for 'py' (via DuckDuckGo):\n\n• Python\n  https://www.python.org/\n  snip..."
        with patch.object(self.s, 'search_google', return_value=ddg), \
             patch.object(self.s, 'read_webpage', return_value='PAGE') as rw:
            self.s.search_and_read('py')
        rw.assert_called_once_with('https://www.python.org/')
        with patch.object(self.s, 'search_google', return_value='Search temporarily unavailable'), \
             patch.object(self.s, 'read_webpage') as rw:
            self.assertEqual(self.s.search_and_read('py'), 'Search temporarily unavailable')
        rw.assert_not_called()
        with patch.object(self.s, 'search_google', side_effect=RuntimeError('boom')):
            self.assertIn('Error in search and read', self.s.search_and_read('py'))

    def test_quick_fact_and_site_search(self):
        with patch.object(self.s.session, 'get', return_value=resp(200, json_data=WIKI_SUMMARY)):
            out = self.s.quick_fact('python')
        self.assertEqual(out, 'Quick fact about python: Python is a high-level, general-purpose programming language.')
        one = dict(WIKI_SUMMARY, extract='Paris is the capital of France.')
        with patch.object(self.s.session, 'get', return_value=resp(200, json_data=one)):
            self.assertTrue(self.s.quick_fact('paris').endswith('capital of France.'))
            self.assertFalse(self.s.quick_fact('paris').endswith('..'))
        with patch.object(self.s, 'search_wikipedia', return_value="No Wikipedia article found for 'x'"), \
             patch.object(self.s, 'search_google', return_value='G') as sg:
            self.assertEqual(self.s.quick_fact('x'), 'G')
        sg.assert_called_once_with('what is x', num_results=1)
        with patch.object(self.s, 'search_wikipedia', side_effect=RuntimeError('boom')):
            self.assertIn('Error getting fact', self.s.quick_fact('x'))
        with patch.object(self.s, 'search_google', return_value='R') as sg:
            self.assertEqual(self.s.search_specific_site('asyncio', 'docs.python.org'), 'R')
        sg.assert_called_once_with('site:docs.python.org asyncio', num_results=3)
        with patch.object(self.s, 'search_google', side_effect=RuntimeError('boom')):
            self.assertIn('Error searching', self.s.search_specific_site('a', 'b'))

    def test_looks_blocked_text_error(self):
        r = Mock(status_code=200)
        type(r).text = property(lambda self: (_ for _ in ()).throw(UnicodeDecodeError('utf-8', b'', 0, 1, 'x')))
        self.assertFalse(WebScraperSkill._looks_blocked(r))


# ── WebSearchSkill ────────────────────────────────────────────────────────

class WebSearchTests(unittest.TestCase):
    def setUp(self):
        self.w = WebSearchSkill()

    def test_extract_search_terms_word_boundaries(self):
        ex = self.w._extract_search_terms
        self.assertEqual(ex('Search the web for Python tutorials'), 'python tutorials')
        self.assertEqual(ex('website builders'), 'website builders')
        self.assertEqual(ex('finding nemo cast'), 'finding nemo cast')
        self.assertEqual(ex('looking glass'), 'looking glass')
        self.assertEqual(ex('look up the eiffel tower'), 'eiffel tower')
        self.assertEqual(ex('google'), 'google')

    def test_search_web_empty_and_results_without_llm(self):
        self.assertEqual(self.w.search_web('   '), 'Please provide a search query.')
        with patch.object(self.w.scraper, 'search_google', return_value='🔍 Search results for x') as sg:
            self.assertEqual(self.w.search_web('search for x'), '🔍 Search results for x')
        sg.assert_called_once_with('x', num_results=6)

    def test_search_web_llm_summary_cleanup(self):
        brain = Mock()
        brain.process_command.return_value = '## Overview\n- **Python** 3.13 released 2024 - 2025\n\n• Fast\n* Free'
        with patch.object(self.w.scraper, 'search_google', return_value='RESULTS'):
            out = self.w.search_web('python news', llm_brain=brain)
        self.assertTrue(out.startswith("Search Summary for 'python news':"))
        self.assertIn('Python 3.13 released 2024 - 2025', out)
        self.assertIn('\nFast\nFree', out)
        self.assertNotIn('*', out)
        self.assertNotIn('#', out)

    def test_search_web_llm_error_falls_back_to_raw(self):
        class Err(str):
            is_error = True
        brain = Mock()
        brain.process_command.return_value = Err('rate limited')
        with patch.object(self.w.scraper, 'search_google', return_value='RESULTS'):
            self.assertEqual(self.w.search_web('x y', llm_brain=brain), "Search Results for 'x y':\n\nRESULTS")
        brain.process_command.side_effect = RuntimeError('down')
        with patch.object(self.w.scraper, 'search_google', return_value='RESULTS'):
            self.assertIn('RESULTS', self.w.search_web('x y', llm_brain=brain))

    def test_search_web_fallback_instant_answer(self):
        with patch.object(self.w.scraper, 'search_google', return_value="No search results found for 'python'"), \
             patch('skills.web_search.requests.get', return_value=resp(200, json_data=DDG_INSTANT)) as g:
            out = self.w.search_web('python')
        self.assertIn("Quick answer for 'python'", out)
        self.assertIn('Source: https://en.wikipedia.org/wiki/Python_(programming_language)', out)
        self.assertIn('timeout', g.call_args.kwargs)
        self.assertTrue(g.call_args.args[0].startswith('https://api.duckduckgo.com/?q=python&format=json'))

    def test_fallback_related_topic_groups_and_empty(self):
        with patch('skills.web_search.requests.get', return_value=resp(200, json_data=DDG_INSTANT_GROUPS)):
            out = self.w._fallback_search('python')
        self.assertIn('1. Python (programming language)', out)
        self.assertIn('2. Monty Python', out)
        with patch('skills.web_search.requests.get', return_value=resp(200, json_data=DDG_INSTANT_EMPTY)):
            self.assertIn("couldn't retrieve search results", self.w._fallback_search('python'))
        with patch('skills.web_search.requests.get', return_value=resp(429, 'slow down')):
            self.assertIn('Bing: https://www.bing.com/search?q=python', self.w._fallback_search('python'))
        with patch('skills.web_search.requests.get', side_effect=requests.Timeout('t')):
            self.assertIn('Search temporarily unavailable', self.w._fallback_search('python'))

    def test_search_web_scraper_exception_and_other_engines(self):
        with patch.object(self.w.scraper, 'search_google', side_effect=RuntimeError('x')), \
             patch.object(self.w, '_fallback_search', return_value='FB'):
            self.assertEqual(self.w.search_web('q'), 'FB')
        self.assertIn('https://www.bing.com/search?q=cats', self.w.search_web('cats', engine='Bing'))
        with patch('skills.web_search.webbrowser.open') as o:
            self.assertIn('Opening google search', self.w.search_web('cats', engine='nope', open_browser=True))
        o.assert_called_once_with('https://www.google.com/search?q=cats')
        with patch('skills.web_search.webbrowser.open', side_effect=OSError('no browser')):
            self.assertIn('Could not open browser', self.w.search_web('cats', open_browser=True))

    def test_delegates(self):
        sc = self.w.scraper
        with patch.object(sc, 'search_wikipedia', return_value='W'), \
             patch.object(sc, 'get_news_headlines', return_value='N'), \
             patch.object(sc, 'read_webpage', return_value='R'), \
             patch.object(sc, 'search_and_read', return_value='S'), \
             patch.object(sc, 'quick_fact', return_value='F'):
            self.assertEqual(self.w.search_wikipedia('a'), 'W')
            self.assertEqual(self.w.get_news_headlines(), 'N')
            self.assertEqual(self.w.read_webpage('u'), 'R')
            self.assertEqual(self.w.search_and_read('q'), 'S')
            self.assertEqual(self.w.get_quick_fact('t'), 'F')
        for name, meth, arg in (('search_wikipedia', self.w.search_wikipedia, 'a'),
                                ('get_news_headlines', self.w.get_news_headlines, 'general'),
                                ('read_webpage', self.w.read_webpage, 'u'),
                                ('search_and_read', self.w.search_and_read, 'q'),
                                ('quick_fact', self.w.get_quick_fact, 't')):
            with patch.object(sc, name, side_effect=RuntimeError('boom')):
                self.assertIn('Error', meth(arg))
        with patch('skills.web_search.webbrowser.open'):
            self.assertIn('Opening Wikipedia search', self.w.search_wikipedia('a b', open_browser=True))
            self.assertIn('Opening news website', self.w.get_news_headlines(open_browser=True))
            self.assertEqual(self.w.open_website('example.com'), 'Opening https://example.com in your browser.')
        with patch('skills.web_search.webbrowser.open', side_effect=OSError('x')):
            self.assertIn('Could not open website', self.w.open_website('http://example.com'))


# ── OllamaManager ─────────────────────────────────────────────────────────

class FakeStream:
    def __init__(self, lines, status=200):
        self.lines, self.status_code = lines, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        return iter(self.lines)


class OllamaTests(unittest.TestCase):
    def setUp(self):
        from core import ollama_manager as om
        self.om = om
        with patch('core.ollama_manager.shutil.which', return_value='/usr/bin/ollama'):
            self.m = om.OllamaManager()
        self.msgs = []
        self.m._on_status = self.msgs.append
        p = patch('core.ollama_manager.time.sleep')
        p.start()
        self.addCleanup(p.stop)

    def test_list_local_models_and_ready(self):
        with patch('core.ollama_manager.requests.get', return_value=resp(200, json_data=OLLAMA_TAGS)) as g:
            models = self.m.list_local_models()
            self.assertTrue(self.m.is_ready())
        self.assertEqual(models, [{'name': 'llama3.2:3b', 'supports_vision': False},
                                  {'name': 'qwen2.5vl:3b', 'supports_vision': True}])
        self.assertTrue(g.call_args.args[0].endswith('/api/tags'))
        with patch('core.ollama_manager.requests.get', return_value=resp(500, 'err')):
            self.assertEqual(self.m.list_local_models(), [])
        with patch('core.ollama_manager.requests.get', side_effect=requests.ConnectionError('refused')):
            self.assertEqual(self.m.list_local_models(), [])
            self.assertFalse(self.m.is_ready())

    def test_pull_success_progress(self):
        with patch('core.ollama_manager.requests.post', return_value=FakeStream(PULL_LINES)) as post:
            self.m._pull_model()
        body = post.call_args.kwargs['json']
        self.assertEqual(body['model'], self.om._model())
        self.assertTrue(body['stream'])
        self.assertIsInstance(post.call_args.kwargs['timeout'], tuple)
        joined = '\n'.join(self.msgs)
        self.assertIn(': 25%', joined)
        self.assertIn(': 54%', joined)   # 50% band reported although 50% itself was skipped
        self.assertIn(': 100%', joined)
        self.assertIn('verifying sha256 digest', joined)
        self.assertTrue(self.m.ready)
        self.assertIn('ready!', self.msgs[-1])

    def test_pull_error_line_and_http_error(self):
        err = [b'{"status":"pulling manifest"}',
               b'{"error":"pull model manifest: file does not exist"}']
        with patch('core.ollama_manager.requests.post', return_value=FakeStream(err)):
            self.m._pull_model()
        self.assertFalse(self.m.ready)
        self.assertIn('file does not exist', self.msgs[-1])
        with patch('core.ollama_manager.requests.post', return_value=FakeStream([], status=500)):
            self.m._pull_model()
        self.assertIn('HTTP 500', self.msgs[-1])
        with patch('core.ollama_manager.requests.post', return_value=FakeStream([b'{"status":"pulling manifest"}', b'[]'])):
            self.m._pull_model()
        self.assertIn('did not complete', self.msgs[-1])
        with patch('core.ollama_manager.requests.post', side_effect=requests.Timeout('read timeout')):
            self.m._pull_model()
        self.assertIn('Model download failed: read timeout', self.msgs[-1])
        self.assertFalse(self.m.ready)

    def test_worker_not_installed(self):
        self.m._exe = None
        self.assertFalse(self.m.is_installed())
        self.m._worker()
        self.assertIn('Ollama not found', self.msgs[-1])

    def test_worker_already_running_with_models(self):
        with patch.object(self.m, 'is_ready', return_value=True), \
             patch('core.ollama_manager.subprocess.Popen') as popen, \
             patch('core.ollama_manager.requests.get', return_value=resp(200, json_data=OLLAMA_TAGS)):
            self.m._worker()
        popen.assert_not_called()
        self.assertTrue(self.m.ready)
        self.assertIn('llama3.2:3b', self.msgs[-1])

    def test_worker_starts_server_then_pulls(self):
        proc = Mock()
        proc.poll.return_value = None
        with patch.object(self.m, 'is_ready', side_effect=[False, False, True]), \
             patch('core.ollama_manager.subprocess.Popen', return_value=proc) as popen, \
             patch.object(self.m, 'list_local_models', return_value=[]), \
             patch.object(self.m, '_pull_model') as pull:
            self.m._worker()
        args, kw = popen.call_args
        self.assertEqual(args[0], ['/usr/bin/ollama', 'serve'])
        self.assertEqual(kw['creationflags'], getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(kw['stdin'], subprocess.DEVNULL)
        pull.assert_called_once()
        self.assertIs(self.m._process, proc)

    def test_worker_popen_fails_or_server_exits_or_never_ready(self):
        with patch.object(self.m, 'is_ready', return_value=False), \
             patch('core.ollama_manager.subprocess.Popen', side_effect=OSError('denied')):
            self.m._worker()
        self.assertIn('failed to start: denied', self.msgs[-1])
        proc = Mock()
        proc.poll.return_value = 1
        with patch.object(self.m, 'is_ready', return_value=False), \
             patch('core.ollama_manager.subprocess.Popen', return_value=proc):
            self.m._worker()
        self.assertIn('exited during startup', self.msgs[-1])
        self.assertIsNone(self.m._process)
        proc.poll.return_value = None
        clock = iter(range(0, 100, 5))
        with patch.object(self.m, 'is_ready', return_value=False), \
             patch('core.ollama_manager.time.monotonic', side_effect=lambda: next(clock)), \
             patch('core.ollama_manager.subprocess.Popen', return_value=proc):
            self.m._worker()
        self.assertIn('did not respond', self.msgs[-1])

    def test_stop_kills_tree_and_waits(self):
        proc = Mock(pid=4321)
        proc.poll.return_value = None
        child = Mock()
        fake_psutil = Mock()
        fake_psutil.Process.return_value.children.return_value = [child]
        self.m._process = proc
        with patch.dict('sys.modules', {'psutil': fake_psutil}):
            self.m.stop()
        fake_psutil.Process.assert_called_once_with(4321)
        child.kill.assert_called_once()
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=5)
        self.assertIsNone(self.m._process)
        self.m.stop()  # no-op when nothing spawned

    def test_stop_escalates_to_kill_and_handles_exited(self):
        proc = Mock(pid=1)
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired('ollama', 5), 0]
        self.m._process = proc
        with patch.dict('sys.modules', {'psutil': None}):
            self.m.stop()
        proc.kill.assert_called_once()
        done = Mock()
        done.poll.return_value = 0
        self.m._process = done
        self.m.stop()
        done.terminate.assert_not_called()
        bad = Mock()
        bad.poll.side_effect = OSError('gone')
        self.m._process = bad
        with self.assertLogs('jarvis.ollama', 'WARNING'):
            self.m.stop()
        self.assertIsNone(self.m._process)

    def test_singleton_start_and_emit_resilience(self):
        with patch.object(self.om.OllamaManager, '_instance', None), \
             patch('core.ollama_manager.shutil.which', return_value=None), \
             patch('core.ollama_manager.os.path.exists', return_value=False):
            a = self.om.OllamaManager.get()
            self.assertIs(a, self.om.OllamaManager.get())
            self.assertFalse(a.is_installed())
        with patch('core.ollama_manager.threading.Thread') as t:
            self.m.start(on_status=lambda s: None)
        t.return_value.start.assert_called_once()
        self.m._on_status = Mock(side_effect=RuntimeError('ui gone'))
        self.m._emit('hello')  # must not raise
        with patch('core.ollama_manager.shutil.which', return_value=None), \
             patch('core.ollama_manager.os.path.exists', side_effect=lambda p: p == r'C:\Program Files\Ollama\ollama.exe'):
            self.assertEqual(self.m._find_exe(), r'C:\Program Files\Ollama\ollama.exe')

    def test_api_url_read_at_call_time(self):
        with patch.object(self.om.Config, 'OLLAMA_URL', 'http://gpu-box:11434/'):
            self.assertEqual(self.om._api(), 'http://gpu-box:11434')


# ── AutomationSkill ───────────────────────────────────────────────────────

class AutomationTests(unittest.TestCase):
    def test_screen_size_and_no_global_pause_override(self):
        import skills.automation as auto
        Size = namedtuple('Size', 'width height')
        with patch.object(auto, 'pyautogui') as gui:
            gui.PAUSE = 0.15
            gui.size.return_value = Size(2560, 1440)
            skill = auto.AutomationSkill()
            self.assertEqual(skill.get_screen_size(), 'Screen size: 2560 x 1440')
            self.assertEqual(gui.PAUSE, 0.15)
            self.assertTrue(gui.FAILSAFE)
            gui.size.side_effect = RuntimeError('no display')
            self.assertIn('Error getting screen size', skill.get_screen_size())


if __name__ == '__main__':
    unittest.main()
