"""Offline resilience tests for search scraping fallbacks (UC 9.1)."""
import unittest
from unittest.mock import Mock, patch

from skills.web_scraper import WebScraperSkill


def fake_response(status_code=200, text='', content=b''):
    fake = Mock()
    fake.status_code = status_code
    fake.text = text
    fake.content = content if content else text.encode('utf-8')
    fake.raise_for_status = Mock()
    return fake


GOOGLE_CAPTCHA = ('<html><body>Our systems have detected unusual traffic from your '
                  'computer network. Please solve the captcha: /sorry/index</body></html>')
DDG_RESULTS = '''
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fguide&rut=abc">Guide Title</a>
  <a class="result__snippet">A useful snippet about the guide.</a>
</div>
'''
DDG_BLOCK = ('<html><body>Unfortunately, bots use DuckDuckGo too. '
             'Please complete a security challenge. captcha</body></html>')


class SearchResilienceTests(unittest.TestCase):
    def setUp(self):
        self.skill = WebScraperSkill()

    def test_looks_blocked_detects_captcha_and_rate_limits(self):
        self.assertTrue(self.skill._looks_blocked(fake_response(200, GOOGLE_CAPTCHA)))
        self.assertTrue(self.skill._looks_blocked(fake_response(429)))
        self.assertTrue(self.skill._looks_blocked(fake_response(503)))
        self.assertFalse(self.skill._looks_blocked(fake_response(200, '<html><h3>Fine</h3></html>')))

    def test_blocked_google_page_falls_back_to_ddg(self):
        blocked = fake_response(200, GOOGLE_CAPTCHA)
        ddg = fake_response(200, DDG_RESULTS)
        with patch.object(self.skill.session, 'get', side_effect=[blocked, ddg]) as get, \
             patch('skills.web_scraper.time.sleep'):
            result = self.skill.search_google('test query')
        self.assertIn('(via DuckDuckGo)', result)
        self.assertIn('Guide Title', result)
        self.assertIn('https://example.com/guide', result)
        self.assertEqual(get.call_count, 2)

    def test_ddg_block_returns_honest_message(self):
        with patch.object(self.skill.session, 'get', return_value=fake_response(200, DDG_BLOCK)):
            result = self.skill._try_alternative_search('test query')
        self.assertIn('blocking automated requests', result)
        self.assertIn('https://www.google.com/search?q=test%20query', result)

    def test_ddg_non_200_returns_manual_links(self):
        with patch.object(self.skill.session, 'get', return_value=fake_response(500, 'boom')):
            result = self.skill._try_alternative_search('test query')
        self.assertIn('Search temporarily unavailable', result)
        self.assertIn('DuckDuckGo: https://duckduckgo.com/?q=test%20query', result)

    def test_network_error_reports_no_results(self):
        with patch.object(self.skill.session, 'get', side_effect=OSError('down')):
            result = self.skill._try_alternative_search('test query')
        self.assertIn("No search results found for 'test query'", result)


if __name__ == '__main__':
    unittest.main()
