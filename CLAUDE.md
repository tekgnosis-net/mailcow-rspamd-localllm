# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A single-file HTTP proxy (`server.py`) that sits between mailcow's rspamd `gpt` plugin and a local OpenAI-compatible LLM (vLLM, llama.cpp, or Ollama). It enriches spam-detection prompts with live web-search context about the sender before forwarding them to the LLM.

## Commands

```bash
make install     # pip install -r requirements-dev.txt (includes runtime deps)
make test        # pytest (verbose, strict markers — see pytest.ini)
make lint        # flake8 server.py tests/ --max-line-length=127
pytest tests/test_server.py::TestExtractDomainsAndNames::test_max_three_domains  # single test
python server.py        # run locally on port 8080
docker-compose up -d    # production deployment
```

Supported Python: 3.10–3.14 (CI matrix in `.github/workflows/tests.yml`; 3.9 was deliberately dropped).

## Architecture

Request flow, all in `server.py`:

1. rspamd POSTs an OpenAI-style chat-completion request to this proxy on port 8080 (the URL path is ignored — the handler accepts POSTs on any path).
2. `extract_domains_and_names()` scans `user`-role messages for domains (regex, capped at 3) and the sender name from a `From:` header line.
3. `fetch_search()` dispatches each extracted entity to the provider selected by `SEARCH_PROVIDER`: `fetch_search_ddgs()` (default; brave + duckduckgo backends via the `ddgs` library) or `fetch_search_firecrawl()` (self-hosted Firecrawl at `FIRECRAWL_API_URL`, optional `FIRECRAWL_API_KEY` Bearer auth; posts to `/v2/search`, falls back to `/v1/search` on 404). Both cap at 2 results and use 3 retries with backoff. An unknown provider value returns an error result without querying anything — deliberate, so typos never leak queries to an unintended engine.
4. Search results are injected as a `system` message at index 1, after the original system prompt.
5. The enriched request is forwarded to the LLM's `/v1/chat/completions` endpoint (urllib3 `Retry` on 5xx plus a manual timeout/connection retry loop) and the response is relayed back verbatim.

Key components:

- `DualStackServer` — `HTTPServer` subclass bound to `::` with `IPV6_V6ONLY=0`, so one socket serves both IPv4 and IPv6.
- `_normalize_api_url()` — turns whatever form of `LLM_API` the user set (bare host, trailing `/v1`, or full pasted path) into a clean URL. `do_POST` uses `"chat"` mode, which always yields `.../v1/chat/completions` (correct for vLLM, llama.cpp, and Ollama's OpenAI-compatible API alike); `"base"` mode is for SDK-style base URLs, where Ollama (detected by port `11434`) gets no `/v1` suffix.
- Any exception in `do_POST` returns a JSON 500; rspamd treats that as "no GPT verdict" rather than a hard failure.

## Releases & Commit Style

- **Commit messages matter**: `.github/workflows/release.yml` runs semantic-release on pushes to `master`. Conventional Commits (`feat:`, `fix:`, `perf:`, `BREAKING CHANGE:`) trigger a GitHub release and publish a multi-arch image to `ghcr.io/tekgnosis-net/mailcow-rspamd-localllm` (`latest`, `X.Y.Z`, `X.Y`); `chore:`/`docs:` do not release.
- semantic-release config lives in `.releaserc.json` (tag format `vX.Y.Z`, no npm plugin — this is not a package).

## Testing Notes

- `TestFetchSearch` performs **real network searches** via DDGS (no mocks) — these are slow and fail offline or when search backends rate-limit. All other test classes mock the network (CI's release gate runs `pytest --deselect tests/test_server.py::TestFetchSearch`).
- pytest `--deselect` matches node IDs by **string prefix** — a new test class must not start with `TestFetchSearch` or the release gate will silently skip it (this is why the Firecrawl class is named `TestFirecrawlSearch`).
- Handler tests instantiate `RequestHandler` via `object.__new__()` and stub `rfile`/`wfile`/`send_response`/`send_header`/`end_headers` instead of starting a server; follow this pattern for new handler tests.

## Deployment Context

- `docker-compose.yaml` pulls `ghcr.io/tekgnosis-net/mailcow-rspamd-localllm:latest` (local `build:` block is commented out for development), joins the external `mailcowdockerized_mailcow-network`, and runs hardened: `read_only`, `cap_drop: ALL`, non-root user, `no-new-privileges`. The server must not write to disk.
- The rspamd side is configured in mailcow at `data/conf/rspamd/local.d/gpt.conf`, pointing at `http://rspamdgpt:8080/...` (full sample config in README.md).
- Env vars (documented in README.md and `.env.example`; compose passes them through from `.env`): `LLM_API` (default `http://127.0.0.1:8000/v1` — inside the container `127.0.0.1` is the container itself, so deployments must override it), `SEARCH_PROVIDER`, `FIRECRAWL_API_URL`, `FIRECRAWL_API_KEY`.
- The user's Firecrawl is a current fork (`tekgnosis-net/firecrawl`, has `/v2/search`) with Camoufox integration (`apps/camoufox-service-ts`) instead of generic Playwright for stealthier search/scrape, usually fronted by the `tekgnosis-net/firecrawl-dashboard` transparent proxy — `FIRECRAWL_API_URL` may point at either; the firecrawl client sends a `mailcow-rspamd-localllm` User-Agent so the dashboard can attribute traffic per client. Link these forks in docs, not the upstreams.
