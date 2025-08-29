from default_api import web_fetch

class GoogleSearchSkill:
    def search(self, query):
        try:
            response = web_fetch(prompt=f"summarize https://www.google.com/search?q={query}")
            return response
        except Exception as e:
            return f"An error occurred: {e}"