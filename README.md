# Mailcow Rspamd with Local LLM

A proxy server that enhances spam detection by integrating web search context with Local LLM's AI capabilities.

## Features

- Dual-stack IPv4/IPv6 HTTP server
- Extracts domains and names from email headers
- Fetches contextual information via web search
- Pluggable search provider: DuckDuckGo (via `ddgs`) or a self-hosted [Firecrawl](https://github.com/tekgnosis-net/firecrawl) instance (a fork with [Camoufox](https://github.com/daijro/camoufox) integration in place of generic Playwright, for stealthier and more reliable search/scrape)
- Integrates with Local LLM's API for AI-powered spam detection
- Retry logic for robust handling of network issues

## Installation

### Using Docker (Recommended)

`docker-compose.yaml` pulls the prebuilt image from GitHub Container Registry (`ghcr.io/tekgnosis-net/mailcow-rspamd-localllm:latest`).

```bash
cp .env.example .env   # then edit to match your setup
docker-compose up -d
```

To build locally instead, comment out `image:` and `pull_policy:` in `docker-compose.yaml` and uncomment the `build:` block.

### Manual Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the server:
```bash
python server.py
```

## Configuration

Configuration is via environment variables. With Docker Compose, put them in a `.env` file next to `docker-compose.yaml` (see `.env.example`) — compose reads it automatically and passes the values through to the container.

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API` | `http://127.0.0.1:8000/v1` | URL of the local LLM's OpenAI-compatible endpoint (vLLM, llama.cpp, or Ollama). Any form works: bare host, with `/v1`, or a full pasted `/v1/chat/completions` path. Inside the container `127.0.0.1` is the container itself, so point it at a reachable host or service name. |
| `SEARCH_PROVIDER` | `ddgs` | Web search provider used to enrich prompts: `ddgs` (Brave/DuckDuckGo via the `ddgs` library) or `firecrawl`. |
| `FIRECRAWL_API_URL` | `http://localhost:3002` | Base URL of your self-hosted Firecrawl instance (used when `SEARCH_PROVIDER=firecrawl`). Can also point at a [firecrawl-dashboard](https://github.com/tekgnosis-net/firecrawl-dashboard) transparent proxy so searches show up in its metrics. |
| `FIRECRAWL_API_KEY` | *(unset)* | Optional Bearer token, only needed if your Firecrawl instance enforces authentication. |

The proxy calls Firecrawl's `/v2/search` endpoint and falls back to `/v1/search` automatically for older self-hosted images. If `SEARCH_PROVIDER` is set to an unknown value, no search is performed at all — queries are never silently rerouted to a different engine.

## Mailcow setup / configuration

1. Configure your local LLM (vLLM or llama.cpp instance). Small model weights work well, as they are faster as well.

2. Edit the file in ``data/conf/rspamd/local.d/gpt.conf`` and replace it with the below config:
```ini
enabled = true; # Enable the plugin
type = "openai"; # Supported types: openai, ollama
api_key = "dummy"
model = "gemma3:12b"
temperature = 0.0;
autolearn = false;
max_tokens = 1000; # Maximum tokens to generate
timeout = 120s; # Timeout for requests
prompt = "You are an expert email evaluator analyzing messages for spam or malicious intent. Use the full content of the email, sender information, and web presence to assess its legitimacy. \n Assumptions: \n - DKIM authentication is valid; the sender address has not been spoofed. \n - You will be provided with the sender domain's web presence for additional context. \n Evaluation Criteria: \n 1. Domain legitimacy and sender identity (based on matching domain and content). \n 2. Language, tone, and structure: assess if it resembles common phishing or scam tactics. \n 3. External context: if the domain has a strong, legitimate online presence, this is a positive signal. \n Output exactly 3 lines: \n 1. Numeric spam/malicious probability from 0.00 to 1.00, less than 0.25 is ham and more than 0.75 is spam (if you find a concern category it's a spam). \n 2. One-sentence justification based on the strongest risk signal (or clearest sign of legitimacy). \n 3. (Only if score > 0.5, the concern category) phishing, scam, malware, or marketing. Leave blank otherwise."
url = "http://rspamdgpt:8080/api/v1/chat/completions"; # URL for the API
allow_passthrough = false; # Check messages with passthrough result
allow_ham = false; # Check messages that are apparent ham (no action and negative score)
reason_header = "X-GPT-Reason"; # Add header with reason (null to disable)
symbols_to_except = { MAILCOW_BLACK = 1998, BAYES_SPAM = 0.9, MAILCOW_FUZZY_DENIED = 1, FUZZY_DENIED = 1, WHITELIST_SPF = -1, WHITELIST_DKIM = -1, WHITELIST_DMARC = -1, REPLY = -1, }
json = false; # Use JSON format for response
```

3. Restart the rspamd with ``docker compose restart rspamd-mailcow``


## Development

### Running Tests

Install development dependencies:
```bash
pip install -r requirements-dev.txt
```

Run tests:
```bash
pytest
```

The `TestFetchSearch` class performs real web searches; when offline or rate-limited, skip it with:
```bash
pytest --deselect tests/test_server.py::TestFetchSearch
```

### Running Linters

```bash
flake8 .
```

## API

The server exposes a POST endpoint that:
1. Accepts chat completion requests
2. Extracts domains and sender names from messages
3. Fetches web context for extracted entities
4. Forwards enriched messages to the configured LLM API
5. Returns the AI-generated response

## Releases

Versioning and publishing are automated with [semantic-release](https://github.com/semantic-release/semantic-release): pushes to `master` with [Conventional Commit](https://www.conventionalcommits.org/) messages (`feat:`, `fix:`, `perf:`, or a `BREAKING CHANGE:` footer) create a GitHub release and publish a multi-arch (amd64/arm64) image to `ghcr.io/tekgnosis-net/mailcow-rspamd-localllm`, tagged `latest`, `X.Y.Z`, and `X.Y`. Commits typed `chore:`, `docs:`, etc. do not trigger a release.

> **Note:** the first package published to GHCR defaults to private visibility. Make it public in the package settings (or `docker login ghcr.io` on the deployment host) so `docker-compose pull` works.

## License

See LICENSE file for details.
