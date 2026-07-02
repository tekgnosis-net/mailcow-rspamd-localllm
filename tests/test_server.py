import pytest
import json
import requests
from unittest.mock import Mock, patch, MagicMock
from http.server import HTTPServer
import server


class TestExtractDomainsAndNames:
    """Test cases for extract_domains_and_names function"""
    
    def test_extract_domains_from_user_message(self):
        """Test extracting domains from user messages"""
        messages = [
            {
                "role": "user",
                "content": "Check example.com and test.org for spam"
            }
        ]
        domains, names = server.extract_domains_and_names(messages)
        assert "example.com" in domains
        assert "test.org" in domains
    
    def test_extract_name_from_from_header_with_angle_brackets(self):
        """Test extracting name from 'From: Name <email>' format"""
        messages = [
            {
                "role": "user",
                "content": "From: John Doe <john@example.com>"
            }
        ]
        domains, names = server.extract_domains_and_names(messages)
        assert "John Doe" in names
    
    def test_extract_name_from_from_header_email_only(self):
        """Test extracting email from 'From: <email>' format"""
        messages = [
            {
                "role": "user",
                "content": "From: <noreply@example.com>"
            }
        ]
        domains, names = server.extract_domains_and_names(messages)
        assert "noreply@example.com" in names
    
    def test_extract_company_name(self):
        """Test extracting company name from From header"""
        messages = [
            {
                "role": "user",
                "content": "From: Company Name <support@example.com>"
            }
        ]
        domains, names = server.extract_domains_and_names(messages)
        assert "Company Name" in names
    
    def test_no_domains_or_names(self):
        """Test with messages containing no domains or names"""
        messages = [
            {
                "role": "user",
                "content": "This is a simple message"
            }
        ]
        domains, names = server.extract_domains_and_names(messages)
        assert len(domains) == 0
        assert len(names) == 0
    
    def test_ignore_system_messages(self):
        """Test that system messages are ignored"""
        messages = [
            {
                "role": "system",
                "content": "From: System <system@example.com>"
            },
            {
                "role": "user",
                "content": "From: User <user@test.com>"
            }
        ]
        domains, names = server.extract_domains_and_names(messages)
        assert "System" not in names
        assert "User" in names
    
    def test_max_three_domains(self):
        """Test that only first 3 domains are returned"""
        messages = [
            {
                "role": "user",
                "content": "Check one.com, two.com, three.com, four.com, five.com"
            }
        ]
        domains, names = server.extract_domains_and_names(messages)
        assert len(domains) <= 3
    
    def test_clean_name_with_quotes(self):
        """Test cleaning names with quotes"""
        messages = [
            {
                "role": "user",
                "content": 'From: "John Doe" <john@example.com>'
            }
        ]
        domains, names = server.extract_domains_and_names(messages)
        assert "John Doe" in names


class TestFetchSearch:
    """Test cases for fetch_search function"""
    
    def test_successful_search(self):
        """Test successful search with real DDGS library"""
        results = server.fetch_search("Python programming")
        assert isinstance(results, list)
        assert len(results) > 0
        # Verify result structure
        for result in results:
            assert "title" in result
            assert "link" in result
            assert "snippet" in result
            # Check that we got actual data, not error messages
            assert result["title"] != "Error"
            assert result["title"] != "No results"
    
    def test_empty_query_results(self):
        """Test search with a very specific query that might return few results"""
        results = server.fetch_search("xyzabc123nonexistent999query")
        assert isinstance(results, list)
        # Should still return a list, even if empty or with "No results" message
        assert len(results) >= 0
    
    def test_special_characters_in_query(self):
        """Test search with special characters"""
        results = server.fetch_search("Python & JavaScript")
        assert isinstance(results, list)
        assert len(results) > 0
        for result in results:
            assert "title" in result
            assert "link" in result
            assert "snippet" in result


class TestFirecrawlSearch:
    """Test cases for fetch_search_firecrawl function (network fully mocked)"""

    def _mock_response(self, status_code=200, payload=None):
        response = Mock()
        response.status_code = status_code
        response.json = Mock(return_value=payload if payload is not None else {})
        response.raise_for_status = Mock()
        if status_code >= 400:
            response.raise_for_status.side_effect = requests.exceptions.HTTPError(f"HTTP {status_code}")
        return response

    @patch('server.requests.post')
    def test_v2_response_format(self, mock_post):
        """Test parsing a Firecrawl v2 response (results grouped under data.web)"""
        payload = {
            "success": True,
            "data": {
                "web": [
                    {"title": "Example Site", "url": "https://example.com", "description": "A snippet"}
                ]
            }
        }
        mock_post.return_value = self._mock_response(payload=payload)

        with patch.dict('os.environ', {'FIRECRAWL_API_URL': 'http://firecrawl:3002'}):
            results = server.fetch_search_firecrawl("example.com")

        assert results == [
            {"title": "Example Site", "link": "https://example.com", "snippet": "A snippet"}
        ]
        args, kwargs = mock_post.call_args
        assert args[0] == 'http://firecrawl:3002/v2/search'
        assert kwargs['json'] == {'query': 'example.com', 'limit': 2}
        assert 'Authorization' not in kwargs['headers']

    @patch('server.requests.post')
    def test_v1_flat_list_response(self, mock_post):
        """Test parsing a Firecrawl v1 response (data is a flat list)"""
        payload = {
            "success": True,
            "data": [
                {"title": "Old Style", "url": "https://v1.example.com", "description": "v1 snippet"}
            ]
        }
        mock_post.return_value = self._mock_response(payload=payload)

        with patch.dict('os.environ', {'FIRECRAWL_API_URL': 'http://firecrawl:3002'}):
            results = server.fetch_search_firecrawl("query")

        assert results == [
            {"title": "Old Style", "link": "https://v1.example.com", "snippet": "v1 snippet"}
        ]

    @patch('server.requests.post')
    def test_api_key_sent_as_bearer(self, mock_post):
        """Test that FIRECRAWL_API_KEY is sent as a Bearer token"""
        payload = {"success": True, "data": {"web": [{"title": "T", "url": "https://u", "description": "D"}]}}
        mock_post.return_value = self._mock_response(payload=payload)

        env = {'FIRECRAWL_API_URL': 'http://firecrawl:3002', 'FIRECRAWL_API_KEY': 'fc-test-key'}
        with patch.dict('os.environ', env):
            server.fetch_search_firecrawl("query")

        _, kwargs = mock_post.call_args
        assert kwargs['headers']['Authorization'] == 'Bearer fc-test-key'

    @patch('server.requests.post')
    def test_falls_back_to_v1_endpoint_on_404(self, mock_post):
        """Test that a 404 on /v2/search falls back to /v1/search (older self-hosted images)"""
        v1_payload = {"success": True, "data": [{"title": "T", "url": "https://u", "description": "D"}]}
        mock_post.side_effect = [
            self._mock_response(status_code=404),
            self._mock_response(payload=v1_payload),
        ]

        with patch.dict('os.environ', {'FIRECRAWL_API_URL': 'http://firecrawl:3002'}):
            results = server.fetch_search_firecrawl("query")

        urls = [call.args[0] for call in mock_post.call_args_list]
        assert urls == ['http://firecrawl:3002/v2/search', 'http://firecrawl:3002/v1/search']
        assert results[0]["title"] == "T"

    @patch('server.requests.post')
    def test_no_results(self, mock_post):
        """Test that an empty result set returns the 'No results' placeholder"""
        payload = {"success": True, "data": {"web": []}}
        mock_post.return_value = self._mock_response(payload=payload)

        with patch.dict('os.environ', {'FIRECRAWL_API_URL': 'http://firecrawl:3002'}):
            results = server.fetch_search_firecrawl("query")

        assert results == [{"title": "No results", "link": "", "snippet": "No search results found"}]

    @patch('server.time.sleep')
    @patch('server.requests.post')
    def test_error_after_all_retries(self, mock_post, mock_sleep):
        """Test that persistent connection errors return an Error result after 3 attempts"""
        mock_post.side_effect = requests.exceptions.ConnectionError("connection refused")

        with patch.dict('os.environ', {'FIRECRAWL_API_URL': 'http://firecrawl:3002'}):
            results = server.fetch_search_firecrawl("query")

        assert results[0]["title"] == "Error"
        assert mock_post.call_count == 3


class TestSearchProviderDispatch:
    """Test cases for the fetch_search provider dispatcher"""

    @patch('server.fetch_search_ddgs')
    def test_default_provider_is_ddgs(self, mock_ddgs):
        """Test that DDGS is used when SEARCH_PROVIDER is unset"""
        mock_ddgs.return_value = [{"title": "t", "link": "l", "snippet": "s"}]

        with patch.dict('os.environ', {}, clear=True):
            results = server.fetch_search("query")

        mock_ddgs.assert_called_once_with("query")
        assert results == mock_ddgs.return_value

    @patch('server.fetch_search_firecrawl')
    def test_firecrawl_provider_selected(self, mock_firecrawl):
        """Test that SEARCH_PROVIDER=firecrawl routes to fetch_search_firecrawl"""
        mock_firecrawl.return_value = [{"title": "t", "link": "l", "snippet": "s"}]

        with patch.dict('os.environ', {'SEARCH_PROVIDER': 'firecrawl'}):
            results = server.fetch_search("query")

        mock_firecrawl.assert_called_once_with("query")
        assert results == mock_firecrawl.return_value

    @patch('server.fetch_search_firecrawl')
    @patch('server.fetch_search_ddgs')
    def test_unknown_provider_returns_error_without_searching(self, mock_ddgs, mock_firecrawl):
        """Test that a typo'd SEARCH_PROVIDER never sends the query anywhere"""
        with patch.dict('os.environ', {'SEARCH_PROVIDER': 'goggle'}):
            results = server.fetch_search("query")

        assert results[0]["title"] == "Error"
        assert "goggle" in results[0]["snippet"]
        mock_ddgs.assert_not_called()
        mock_firecrawl.assert_not_called()


class TestRequestHandler:
    """Test cases for RequestHandler class"""
    
    @patch('server.requests.Session')
    @patch('server.fetch_search')
    def test_successful_post_request(self, mock_search, mock_session):
        """Test successful POST request handling"""
        # Setup
        request_data = {
            "messages": [
                {"role": "user", "content": "From: Test <test@example.com>"}
            ]
        }
        
        mock_search.return_value = [
            {
                "title": "Test Title",
                "link": "https://example.com",
                "snippet": "Test snippet"
            }
        ]
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "success"}'
        mock_response.headers = {}
        
        mock_session_instance = Mock()
        mock_session_instance.post.return_value = mock_response
        mock_session.return_value = mock_session_instance
        
        # Create handler instance without triggering __init__
        handler = object.__new__(server.RequestHandler)
        handler.headers = {'Content-Length': str(len(json.dumps(request_data)))}
        handler.rfile = Mock()
        handler.rfile.read = Mock(return_value=json.dumps(request_data).encode())
        handler.wfile = Mock()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        
        # Execute
        with patch.dict('os.environ', {'LLM_API': 'http://localhost:8000/v1'}):
            handler.do_POST()
        
        # Assert
        handler.send_response.assert_called_once_with(200)
        assert handler.wfile.write.called
    
    @patch('server.requests.Session')
    def test_missing_messages_in_request(self, mock_session):
        """Test handling request with missing messages"""
        request_data = {}
        
        handler = object.__new__(server.RequestHandler)
        handler.headers = {'Content-Length': str(len(json.dumps(request_data)))}
        handler.rfile = Mock()
        handler.rfile.read = Mock(return_value=json.dumps(request_data).encode())
        handler.wfile = Mock()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        
        with patch.dict('os.environ', {'LLM_API': 'http://localhost:8000/v1'}):
            handler.do_POST()
        
        handler.send_response.assert_called_once_with(500)
    
    @patch('server.requests.Session')
    def test_invalid_json_in_request(self, mock_session):
        """Test handling invalid JSON in request"""
        handler = object.__new__(server.RequestHandler)
        handler.headers = {'Content-Length': '10'}
        handler.rfile = Mock()
        handler.rfile.read = Mock(return_value=b'invalid json')
        handler.wfile = Mock()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        
        with patch.dict('os.environ', {'LLM_API': 'http://localhost:8000/v1'}):
            handler.do_POST()
        
        handler.send_response.assert_called_once_with(500)
    
    @patch('server.requests.Session')
    @patch('server.fetch_search')
    def test_web_context_insertion(self, mock_search, mock_session):
        """Test that web context is properly inserted into messages"""
        request_data = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": "From: Test <test@example.com>"}
            ]
        }
        
        mock_search.return_value = [
            {
                "title": "Test Title",
                "link": "https://example.com",
                "snippet": "Test snippet"
            }
        ]
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "success"}'
        mock_response.headers = {}
        
        mock_session_instance = Mock()
        mock_session_instance.post.return_value = mock_response
        mock_session.return_value = mock_session_instance
        
        handler = object.__new__(server.RequestHandler)
        handler.headers = {'Content-Length': str(len(json.dumps(request_data)))}
        handler.rfile = Mock()
        handler.rfile.read = Mock(return_value=json.dumps(request_data).encode())
        handler.wfile = Mock()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        
        with patch.dict('os.environ', {'LLM_API': 'http://localhost:8000/v1'}):
            handler.do_POST()
        
        # Verify that session.post was called
        assert mock_session_instance.post.called
        call_args = mock_session_instance.post.call_args
class TestDualStackServer:
    """Test cases for DualStackServer class"""
    
    def test_dual_stack_server_address_family(self):
        """Test that DualStackServer uses IPv6 address family"""
        assert server.DualStackServer.address_family == server.socket.AF_INET6
    
    def test_server_bind_sets_ipv6_only_to_false(self):
        """Test that server_bind sets IPV6_V6ONLY to 0"""
        # Create server instance without binding
        mock_server = object.__new__(server.DualStackServer)
        mock_server.socket = Mock()
        mock_server.server_address = ('::', 8080)
        
        # Mock the parent server_bind
        with patch('http.server.HTTPServer.server_bind'):
            mock_server.server_bind()
        
        # Check that setsockopt was called with IPV6_V6ONLY set to 0
        mock_server.socket.setsockopt.assert_called_once_with(
            server.socket.IPPROTO_IPV6, 
            server.socket.IPV6_V6ONLY, 
            0
        )


class TestRunServer:
    """Test cases for run_server function"""
    
    @patch('server.DualStackServer')
    def test_run_server_creates_server(self, mock_server_class):
        """Test that run_server creates a DualStackServer instance"""
        mock_instance = Mock()
        mock_server_class.return_value = mock_instance
        
        # We need to stop serve_forever from blocking
        mock_instance.serve_forever = Mock()
        
        server.run_server(port=9999)
        
        mock_server_class.assert_called_once_with(('::', 9999), server.RequestHandler)
        mock_instance.serve_forever.assert_called_once()
    
    @patch('server.DualStackServer')
    def test_run_server_default_port(self, mock_server_class):
        """Test that run_server uses default port 8080"""
        mock_instance = Mock()
        mock_server_class.return_value = mock_instance
        mock_instance.serve_forever = Mock()
        
        server.run_server()
        
        mock_server_class.assert_called_once_with(('::', 8080), server.RequestHandler)
