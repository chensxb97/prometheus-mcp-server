"""Tests for the MCP tools functionality."""

import pytest
import json
from unittest.mock import patch, MagicMock
from fastmcp import Client
from prometheus_mcp_server.server import mcp, execute_query, execute_range_query, list_metrics, get_metric_metadata, get_targets, list_labels, get_label_values, find_series

@pytest.fixture
def mock_make_request():
    """Mock the make_prometheus_request function."""
    with patch("prometheus_mcp_server.server.make_prometheus_request") as mock:
        yield mock

@pytest.mark.asyncio
async def test_execute_query(mock_make_request):
    """Test the execute_query tool."""
    # Setup
    mock_make_request.return_value = {
        "resultType": "vector",
        "result": [{"metric": {"__name__": "up"}, "value": [1617898448.214, "1"]}]
    }

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("execute_query", {"query":"up", "tenant":"default"})

        # Verify
        mock_make_request.assert_called_once_with("query", params={"query": "up"}, tenant_name="default")
        assert result.data["resultType"] == "vector"
        assert len(result.data["result"]) == 1

@pytest.mark.asyncio
async def test_execute_query_with_time(mock_make_request):
    """Test the execute_query tool with a specified time."""
    # Setup
    mock_make_request.return_value = {
        "resultType": "vector",
        "result": [{"metric": {"__name__": "up"}, "value": [1617898448.214, "1"]}]
    }

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("execute_query", {"query":"up", "time":"2023-01-01T00:00:00Z", "tenant": "default"})
        
        # Verify
        mock_make_request.assert_called_once_with("query", params={"query": "up", "time": "2023-01-01T00:00:00Z"}, tenant_name="default")
        assert result.data["resultType"] == "vector"

@pytest.mark.asyncio
async def test_execute_range_query(mock_make_request):
    """Test the execute_range_query tool."""
    # Setup
    mock_make_request.return_value = {
        "resultType": "matrix",
        "result": [{
            "metric": {"__name__": "up"},
            "values": [
                [1617898400, "1"],
                [1617898415, "1"]
            ]
        }]
    }

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool(
            "execute_range_query",{
            "query": "up", 
            "start": "2023-01-01T00:00:00Z", 
            "end": "2023-01-01T01:00:00Z", 
            "step": "15s",
            "tenant": "default"
        })

        # Verify
        mock_make_request.assert_called_once_with("query_range", params={
            "query": "up",
            "start": "2023-01-01T00:00:00Z",
            "end": "2023-01-01T01:00:00Z",
            "step": "15s"
        }, tenant_name="default")
        assert result.data["resultType"] == "matrix"
        assert len(result.data["result"]) == 1
        assert len(result.data["result"][0]["values"]) == 2

@pytest.mark.asyncio
async def test_list_metrics(mock_make_request):
    """Test the list_metrics tool."""
    # Setup
    mock_make_request.return_value = ["up", "go_goroutines", "http_requests_total"]

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("list_metrics", {"tenant":"default"})

        payload = result.content[0].text
        json_data = json.loads(payload)

        # Verify
        mock_make_request.assert_called_once_with("label/__name__/values", params=None, tenant_name="default")
        assert json_data["metrics"] == ["up", "go_goroutines", "http_requests_total"]

@pytest.mark.asyncio
async def test_get_metric_metadata(mock_make_request):
    """Test the get_metric_metadata tool."""
    # Setup
    mock_make_request.return_value = {"metadata": [
        {"metric": "up", "type": "gauge", "help": "Up indicates if the scrape was successful", "unit": ""}
    ]}

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("get_metric_metadata", {"metric":"up", "tenant":"default"})

        payload = result.content[0].text
        json_data = json.loads(payload)

        # Verify
        mock_make_request.assert_called_once_with("metadata", params={"metric": "up"}, tenant_name="default")
        assert len(json_data["metadata"]) == 1
        assert json_data["metadata"][0]["metric"] == "up"
        assert json_data["metadata"][0]["type"] == "gauge"

@pytest.mark.asyncio
async def test_get_targets(mock_make_request):
    """Test the get_targets tool."""
    # Setup
    mock_make_request.return_value = {
        "activeTargets": [
            {"discoveredLabels": {"__address__": "localhost:9090"}, "labels": {"job": "prometheus"}, "health": "up"}
        ],
        "droppedTargets": []
    }

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("get_targets",{"tenant":"default"})

        payload = result.content[0].text
        json_data = json.loads(payload)

        # Verify
        mock_make_request.assert_called_once_with("targets", tenant_name="default")
        assert len(json_data["activeTargets"]) == 1
        assert json_data["activeTargets"][0]["health"] == "up"
        assert len(json_data["droppedTargets"]) == 0

# Pagination Tests

@pytest.mark.asyncio
async def test_list_metrics_with_limit(mock_make_request):
    """Test the list_metrics tool with pagination limit."""
    # Setup
    mock_make_request.return_value = ["up", "go_goroutines"]
    
    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("list_metrics", {"limit": 2, "tenant": "default"})
        
        payload = result.content[0].text
        json_data = json.loads(payload)
        # Verify
        mock_make_request.assert_called_once_with("label/__name__/values", params={"limit": 2}, tenant_name="default")
        assert json_data["metrics"] == ["up", "go_goroutines"]

@pytest.mark.asyncio
async def test_list_metrics_without_limit(mock_make_request):
    """Test the list_metrics tool maintains backward compatibility."""
    # Setup
    mock_make_request.return_value = ["up", "go_goroutines", "http_requests_total"]
    
    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("list_metrics", {"tenant": "default"})
        
        payload = result.content[0].text
        json_data = json.loads(payload)

        # Verify
        mock_make_request.assert_called_once_with("label/__name__/values", params=None, tenant_name="default")
        assert json_data["metrics"] == ["up", "go_goroutines", "http_requests_total"]

@pytest.mark.asyncio
async def test_get_metric_metadata_with_limit(mock_make_request):
    """Test the get_metric_metadata tool with pagination limit."""
    # Setup
    mock_make_request.return_value = {"metadata": [
        {"metric": "up", "type": "gauge", "help": "Up indicates if the scrape was successful", "unit": ""}
    ]}

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("get_metric_metadata", {"metric": "up", "limit": 1, "tenant": "default"})

        payload = result.content[0].text
        json_data = json.loads(payload)

        # Verify
        mock_make_request.assert_called_once_with("metadata", params={"metric": "up", "limit": 1}, tenant_name="default")
        assert len(json_data["metadata"]) == 1
        assert json_data["metadata"][0]["metric"] == "up"

@pytest.mark.asyncio
async def test_list_labels(mock_make_request):
    """Test the new list_labels tool."""
    # Setup
    mock_make_request.return_value = ["__name__", "job", "instance"]

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("list_labels", {"tenant":"default"})

        # Verify
        mock_make_request.assert_called_once_with("labels", params=None, tenant_name="default")
        assert result.data == ["__name__", "job", "instance"]

@pytest.mark.asyncio
async def test_list_labels_with_limit(mock_make_request):
    """Test the list_labels tool with pagination limit."""
    # Setup
    mock_make_request.return_value = ["__name__", "job"]

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("list_labels", {"limit": 2, "tenant": "default"})

        # Verify
        mock_make_request.assert_called_once_with("labels", params={"limit": 2}, tenant_name="default")
        assert result.data == ["__name__", "job"]

@pytest.mark.asyncio
async def test_get_label_values(mock_make_request):
    """Test the new get_label_values tool."""
    # Setup
    mock_make_request.return_value = ["prometheus", "node-exporter"]

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("get_label_values", {"label_name": "job", "tenant": "default"})

        # Verify
        mock_make_request.assert_called_once_with("label/job/values", params=None, tenant_name="default")
        assert result.data == ["prometheus", "node-exporter"]

@pytest.mark.asyncio
async def test_get_label_values_with_limit(mock_make_request):
    """Test the get_label_values tool with pagination limit."""
    # Setup
    mock_make_request.return_value = ["prometheus"]

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("get_label_values", {"label_name": "job", "limit": 1, "tenant": "default"})

        # Verify
        mock_make_request.assert_called_once_with("label/job/values", params={"limit": 1}, tenant_name="default")
        assert result.data == ["prometheus"]

@pytest.mark.asyncio
async def test_find_series(mock_make_request):
    """Test the new find_series tool."""
    # Setup
    mock_make_request.return_value = [
        {"__name__": "up", "job": "prometheus", "instance": "localhost:9090"}
    ]

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("find_series", {"match": ["up"], "tenant": "default"})

        payload = result.content[0].text
        json_data = json.loads(payload)

        # Verify
        mock_make_request.assert_called_once_with("series", params={"match[]": ["up"]}, tenant_name="default")
        assert len(json_data) == 1
        assert json_data[0]["__name__"] == "up"

@pytest.mark.asyncio
async def test_find_series_with_limit_and_time_range(mock_make_request):
    """Test the find_series tool with all optional parameters."""
    # Setup
    mock_make_request.return_value = [
        {"__name__": "up", "job": "prometheus", "instance": "localhost:9090"}
    ]

    async with Client(mcp) as client:
        # Execute
        result = await client.call_tool("find_series", {
            "match": ["up", "process_start_time_seconds"],
            "limit": 1,
            "start": "2023-01-01T00:00:00Z",
            "end": "2023-01-01T01:00:00Z",
            "tenant": "default"
        })

        payload = result.content[0].text
        json_data = json.loads(payload)

        # Verify
        mock_make_request.assert_called_once_with("series", params={
            "match[]": ["up", "process_start_time_seconds"],
            "limit": 1,
            "start": "2023-01-01T00:00:00Z",
            "end": "2023-01-01T01:00:00Z"
        }, tenant_name="default")
        assert len(json_data) == 1
