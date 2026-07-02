from http.server import HTTPServer, BaseHTTPRequestHandler
import socket
import json
import requests
import re
import time
import os
from urllib.parse import urlparse, quote, urlunparse
from requests.adapters import HTTPAdapter, Retry
from ddgs import DDGS

class DualStackServer(HTTPServer):
    address_family = socket.AF_INET6
    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()

def extract_domains_and_names(messages):
    domain_regex = r'\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b'
    domains = set()
    names = set()

    for msg in messages:
        if msg["role"] == "user":
            content = msg.get("content", "")

            # Extract domains
            found_domains = re.findall(domain_regex, content)
            domains.update(found_domains)

            # Extract name from From header with various formats
            if content.lower().startswith("from:"):
                # Match patterns like:
                # From: John Doe <john@example.com>
                # From: <noreply@example.com>
                # From: Company Name <support@example.com>
                match = re.search(r'From:\s*(?:([^<]+?)\s*<|<([^>]+)>)', content, re.IGNORECASE)
                if match:
                    name = match.group(1) or match.group(2)
                    if name:
                        # Clean up the name (remove extra spaces, quotes, etc)
                        name = name.strip().strip('"\'')
                        names.add(name)

    # Convert domains set to list and take only first 3
    domains_list = list(domains)[:3]
    return domains_list, list(names)

def fetch_search_ddgs(query):
    """Search using DDGS library with multiple backends."""
    max_retries = 3
    backends = "brave, duckduckgo"
    
    for attempt in range(max_retries):
        try:
            ddgs = DDGS(timeout=10)
            results = ddgs.text(
                query=query,
                max_results=2,
                backend=backends
            )
            
            # Transform results to match expected format
            formatted_results = []
            for res in results:
                formatted_results.append({
                    'title': res.get('title', 'No title'),
                    'link': res.get('href', ''),
                    'snippet': res.get('body', '')
                })
            
            return formatted_results if formatted_results else [{"title": "No results", "link": "", "snippet": "No search results found"}]
            
        except Exception as e:
            if attempt == max_retries - 1:  # Last attempt
                return [{"title": "Error", "link": "", "snippet": "Search service error after {} attempts: {}".format(max_retries, str(e))}]
            print("Search attempt {} failed: {}. Retrying...".format(attempt + 1, e))
            time.sleep(1 * (attempt + 1))  # Exponential backoff
    
    return [{"title": "Error", "link": "", "snippet": "Search failed after all retries"}]


def fetch_search_firecrawl(query):
    """Search using a (self-hosted) Firecrawl instance's search API.

    Works against the Firecrawl API directly or through a transparent proxy
    such as firecrawl-dashboard — only the base URL differs.
    """
    max_retries = 3
    base_url = os.environ.get('FIRECRAWL_API_URL', 'http://localhost:3002').strip().rstrip('/')
    api_key = os.environ.get('FIRECRAWL_API_KEY', '').strip()

    headers = {'User-Agent': 'mailcow-rspamd-localllm'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    for attempt in range(max_retries):
        try:
            response = None
            # Older self-hosted images only expose /v1/search, so fall back on 404
            for endpoint in ('/v2/search', '/v1/search'):
                response = requests.post(
                    f'{base_url}{endpoint}',
                    json={'query': query, 'limit': 2},
                    headers=headers,
                    timeout=15
                )
                if response.status_code != 404:
                    break
            response.raise_for_status()
            payload = response.json()

            if not payload.get('success', True):
                raise ValueError(payload.get('warning') or 'Firecrawl returned success=false')

            data = payload.get('data', [])
            # v2 groups results by source ({"web": [...]}), v1 returns a flat list
            items = data.get('web', []) if isinstance(data, dict) else data

            formatted_results = []
            for res in items:
                formatted_results.append({
                    'title': res.get('title') or 'No title',
                    'link': res.get('url', ''),
                    'snippet': res.get('description') or ''
                })

            return formatted_results if formatted_results else [{"title": "No results", "link": "", "snippet": "No search results found"}]

        except Exception as e:
            if attempt == max_retries - 1:  # Last attempt
                return [{"title": "Error", "link": "", "snippet": "Search service error after {} attempts: {}".format(max_retries, str(e))}]
            print("Firecrawl search attempt {} failed: {}. Retrying...".format(attempt + 1, e))
            time.sleep(1 * (attempt + 1))  # Exponential backoff

    return [{"title": "Error", "link": "", "snippet": "Search failed after all retries"}]


def fetch_search(query):
    """Dispatch a search to the provider selected via SEARCH_PROVIDER (ddgs or firecrawl)."""
    provider = os.environ.get('SEARCH_PROVIDER', 'ddgs').strip().lower()
    if provider == 'firecrawl':
        return fetch_search_firecrawl(query)
    if provider in ('ddgs', 'duckduckgo'):
        return fetch_search_ddgs(query)
    # A misspelled provider must not silently send queries to an unintended engine
    print(f"Unknown SEARCH_PROVIDER '{provider}', not searching. Use 'ddgs' or 'firecrawl'.")
    return [{"title": "Error", "link": "", "snippet": f"Unknown SEARCH_PROVIDER: {provider}"}]


def _normalize_api_url(user_url: str, endpoint_type: str = "chat") -> str:
    """
    Normalizes URLs for vLLM, Ollama, and llama.cpp.

    endpoint_type: 'base' (for SDKs) or 'chat' (for raw requests)
    """
    # --- Examples ---
    # OpenAI or vLLM or llama.cpp
    # _normalize_api_url("localhost:8000", "base")
    # Output: http://localhost:8000/v1
    #
    # Ollama
    # _normalize_api_url("http://127.0.0.1:11434", "base")
    # Output: http://127.0.0.1:11434
    #
    # chat
    # _normalize_api_url("https://my-vllm-server.com", "chat")
    # Output: https://my-vllm-server.com/v1/chat/completions  (Perfect for requests.post)

    # Clean whitespace and trailing slashes
    url = user_url.strip().rstrip("/")

    # Ensure scheme exists
    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    parsed = urlparse(url)
    path = parsed.path

    # Remove redundant endpoints if user pasted the full path
    if path.endswith("/chat/completions"):
        path = path.replace("/chat/completions", "")
    if path.endswith("/v1"):
        path = path.replace("/v1", "")

    # Rebuild clean base path
    path = path.rstrip("/")

    if endpoint_type == "base":
        # Ollama natively handles its own routes; vLLM/llama.cpp usually need /v1
        if "11434" in parsed.netloc:
            new_path = path
        else:
            new_path = f"{path}/v1" if path else "/v1"
    elif endpoint_type == "chat":
        # For raw requests library (requests.post)
        if "11434" in parsed.netloc:
            new_path = f"{path}/v1/chat/completions" if path else "/v1/chat/completions"
        else:
            new_path = f"{path}/v1/chat/completions" if path else "/v1/chat/completions"

    # Clean up double slashes; keep an empty path empty (no trailing slash)
    if new_path:
        new_path = "/" + new_path.lstrip("/")

    return urlunparse(parsed._replace(path=new_path))


class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        url = _normalize_api_url(os.environ.get('LLM_API', 'http://127.0.0.1:8000/v1'), "chat")

        s = requests.Session()

        retries = Retry(total=10,
                backoff_factor=2,
                status_forcelist=[ 500, 502, 503, 504 ],
                raise_on_status=False)

        s.mount('http://', HTTPAdapter(max_retries=retries))

        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)

            if "messages" not in data or not data["messages"]:
                raise ValueError("Missing messages in request.")

            domains, names = extract_domains_and_names(data["messages"])
            search_queries = domains + names
            search_results = []

            for query in search_queries:
                results = fetch_search(query)
                for res in results:
                    search_results.append(f"{res['title']}\n{res['link']}\n{res['snippet']}")

            if search_results:
                system_message = {
                    "role": "system",
                    "content": "Web context:\n" + "\n\n".join(search_results)
                }
                data["messages"].insert(1, system_message)  # insert after initial system prompt

            headers = dict(self.headers)

            # Retry logic for the main request
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = s.post(
                        url,
                        json=data,
                        headers=headers,
                        timeout=45
                    )
                    break  # Success, exit retry loop
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    if attempt == max_retries - 1:  # Last attempt
                        raise e
                    print("Attempt {} failed with timeout/connection error: {}. Retrying...".format(attempt + 1, e))
                    # Optional: add a brief delay between retries
                    import time
                    time.sleep(1 * (attempt + 1))  # Exponential backoff

            content = response.content
            self.send_response(response.status_code)
            self.send_header('Content-Length', len(content))
            for header, value in response.headers.items():
                if header.lower() not in ['transfer-encoding', 'content-length']:
                    self.send_header(header, value)
            self.end_headers()
            self.wfile.write(content)

        except Exception as e:
            print(f"Exception occurred: {e}")  # Print the error message
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            error_response = json.dumps({'error': str(e)})
            self.wfile.write(error_response.encode())


def run_server(port=8080):
    server_address = ('::', port)
    httpd = DualStackServer(server_address, RequestHandler)
    print(f'Server running on:: [IPv6] http://[::]:{port} and [IPv4] http://0.0.0.0:{port}')
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()
