# Mailcow Rspamd with Local LLM

A proxy server that enhances spam detection by integrating web search context with Local LLM's AI capabilities.

## Features

- Dual-stack IPv4/IPv6 HTTP server
- Extracts domains and names from email headers
- Fetches contextual information via web search
- Integrates with Local LLM's API for AI-powered spam detection
- Retry logic for robust handling of network issues

## Installation

### Using Docker (Recommended)

```bash
docker-compose up -d
```

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

Set the following environment variable:

- `LLM_API`: URL of the Local LLM API endpoint (default: `http://127.0.0.1:8000/v1`)

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

### Running Linters

```bash
flake8 .
```

## API

The server exposes a POST endpoint that:
1. Accepts chat completion requests
2. Extracts domains and sender names from messages
3. Fetches web context for extracted entities
4. Forwards enriched messages to Ollama API
5. Returns the AI-generated response

## License

See LICENSE file for details.
