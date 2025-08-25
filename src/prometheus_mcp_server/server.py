#!/usr/bin/env python

import os
import json
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
import time
from datetime import datetime, timedelta
from enum import Enum

import dotenv
import requests
from fastmcp import FastMCP
from prometheus_mcp_server.logging_config import get_logger

dotenv.load_dotenv()
mcp = FastMCP("Prometheus MCP")

# Get logger instance
logger = get_logger()

class TransportType(str, Enum):
    """Supported MCP server transport types."""

    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"

    @classmethod
    def values(cls) -> list[str]:
        """Get all valid transport values."""
        return [transport.value for transport in cls]

@dataclass
class MCPServerConfig:
    """Global Configuration for MCP."""
    mcp_server_transport: TransportType = None
    mcp_bind_host: str = None
    mcp_bind_port: int = None

    def __post_init__(self):
        """Validate mcp configuration."""
        if not self.mcp_server_transport:
            raise ValueError("MCP SERVER TRANSPORT is required")
        if not self.mcp_bind_host:
            raise ValueError(f"MCP BIND HOST is required")
        if not self.mcp_bind_port:
            raise ValueError(f"MCP BIND PORT is required")

@dataclass
class PrometheusTenant:
    """Configuration for a single Prometheus tenant."""
    name: str
    url: str
    # Optional credentials
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    # Optional Org ID for multi-tenant setups
    org_id: Optional[str] = None
    
    def __post_init__(self):
        """Validate tenant configuration."""
        if not self.name:
            raise ValueError("Tenant name is required")
        if not self.url:
            raise ValueError(f"URL is required for tenant '{self.name}'")

@dataclass
class PrometheusConfig:
    """Multi-tenant Prometheus configuration."""
    tenants: Dict[str, PrometheusTenant]
    default_tenant: Optional[str] = None
    # Optional Custom MCP Server Configuration
    mcp_server_config: Optional[MCPServerConfig] = None
    
    def __post_init__(self):
        """Validate configuration and set default tenant."""
        if not self.tenants:
            raise ValueError("At least one tenant must be configured")
        
        if not self.default_tenant:
            raise ValueError("Missing default tenant")
            
        # Validate default tenant exists
        if self.default_tenant and not self.get_tenant(self.default_tenant):
            raise ValueError(f"Default tenant '{self.default_tenant}' not found in tenant list")
    
    def get_tenant(self, name: str) -> Optional[PrometheusTenant]:
        """Get tenant configuration by name."""
        if name in self.tenants:
            return self.tenants[name]
        
        return None
    
    def list_tenant_names(self) -> List[str]:
        """Get list of all tenant names."""
        return [tenant.name for tenant in self.tenants]

def load_multi_tenant_config() -> PrometheusConfig:
    """Load multi-tenant configuration from environment variables."""
    # MCP Server Configuration
    mcp_server_config=MCPServerConfig(
        mcp_server_transport=os.environ.get("PROMETHEUS_MCP_SERVER_TRANSPORT", "stdio").lower(),
        mcp_bind_host=os.environ.get("PROMETHEUS_MCP_BIND_HOST", "127.0.0.1"),
        mcp_bind_port=int(os.environ.get("PROMETHEUS_MCP_BIND_PORT", "8080"))
    )

    # Check if we have a JSON configuration for multiple tenants
    tenants_json_file = os.environ.get("PROMETHEUS_TENANTS", "")
    tenants_json = ""
    if tenants_json_file:
        try:
            with open(tenants_json_file, 'r') as f:
                tenants_json = json.load(f)
            print("JSON data loaded successfully:")
            print(tenants_json)
        except FileNotFoundError:
            print(f"Error: JSON file not found at {tenants_json_file}")
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON format in {tenants_json_file}")
    else:
        print("Error: PROMETHEUS_TENANTS environment variable not set.")
    
    if tenants_json:
        # Multi-tenant configuration via JSON
        try:
            tenants_data = json.loads(tenants_json)
            tenants = {}
            
            for tenant_data in tenants_data:
                tenant = PrometheusTenant(
                    name=tenant_data["name"],
                    url=tenant_data["url"],
                    username=tenant_data.get("username"),
                    password=tenant_data.get("password"),
                    token=tenant_data.get("token"),
                    org_id=tenant_data.get("org_id")
                )
                tenants[tenant_data["name"]] = tenant
            
            default_tenant = os.environ.get("PROMETHEUS_DEFAULT_TENANT")
            return PrometheusConfig(tenants=tenants, default_tenant=default_tenant, mcp_server_config=mcp_server_config)
            
        except json.JSONDecodeError as e:
            logger.error("Failed to parse PROMETHEUS_TENANTS JSON", error=str(e))
            raise ValueError(f"Invalid JSON in PROMETHEUS_TENANTS: {str(e)}")
        except KeyError as e:
            logger.error("Missing required field in tenant configuration", error=str(e))
            raise ValueError(f"Missing required field in tenant configuration: {str(e)}")
    else:
        # Single tenant configuration (backward compatibility)
        url = os.environ.get("PROMETHEUS_URL", "")
        if not url:
            raise ValueError("Either PROMETHEUS_TENANTS or PROMETHEUS_URL must be set")
        
        tenant = PrometheusTenant(
            name="default",
            url=url,
            username=os.environ.get("PROMETHEUS_USERNAME"),
            password=os.environ.get("PROMETHEUS_PASSWORD"),
            token=os.environ.get("PROMETHEUS_TOKEN"),
            org_id=os.environ.get("ORG_ID")
        )
        return PrometheusConfig(tenants={"default": tenant}, default_tenant="default", mcp_server_config=mcp_server_config)

# Load configuration
config = load_multi_tenant_config()

def get_prometheus_auth(tenant: PrometheusTenant):
    """Get authentication for Prometheus based on tenant credentials."""
    if tenant.token:
        return {"Authorization": f"Bearer {tenant.token}"}
    elif tenant.username and tenant.password:
        return requests.auth.HTTPBasicAuth(tenant.username, tenant.password)
    return None

def make_prometheus_request(endpoint, params=None, tenant_name: Optional[str] = None):
    """Make a request to the Prometheus API with proper authentication and headers."""
    # Use default tenant if none specified
    if tenant_name is None:
        tenant_name = config.default_tenant
    
    tenant = config.get_tenant(tenant_name)
    if not tenant:
        logger.error("Tenant not found", tenant=tenant_name, available_tenants=config.list_tenant_names())
        raise ValueError(f"Tenant '{tenant_name}' not found. Available tenants: {config.list_tenant_names()}")

    url = f"{tenant.url.rstrip('/')}/api/v1/{endpoint}"
    auth = get_prometheus_auth(tenant)
    headers = {}

    if isinstance(auth, dict):  # Token auth is passed via headers
        headers.update(auth)
        auth = None  # Clear auth for requests.get if it's already in headers
    
    # Add OrgID header if specified
    if tenant.org_id:
        headers["X-Scope-OrgID"] = tenant.org_id

    try:
        logger.debug("Making Prometheus API request", 
                    endpoint=endpoint, url=url, params=params, 
                    tenant=tenant_name, org_id=tenant.org_id)
        
        # Make the request with appropriate headers and auth
        response = requests.get(url, params=params, auth=auth, headers=headers)
        
        response.raise_for_status()
        result = response.json()
        
        if result["status"] != "success":
            error_msg = result.get('error', 'Unknown error')
            logger.error("Prometheus API returned error", 
                        endpoint=endpoint, error=error_msg, status=result["status"],
                        tenant=tenant_name)
            raise ValueError(f"Prometheus API error for tenant '{tenant_name}': {error_msg}")
        
        data_field = result.get("data", {})
        if isinstance(data_field, dict):
            result_type = data_field.get("resultType")
        else:
            result_type = "list"
        logger.debug("Prometheus API request successful", 
                    endpoint=endpoint, result_type=result_type, tenant=tenant_name)
        return result["data"]
    
    except requests.exceptions.RequestException as e:
        logger.error("HTTP request to Prometheus failed", 
                    endpoint=endpoint, url=url, error=str(e), error_type=type(e).__name__,
                    tenant=tenant_name)
        raise
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Prometheus response as JSON", 
                    endpoint=endpoint, url=url, error=str(e), tenant=tenant_name)
        raise ValueError(f"Invalid JSON response from Prometheus tenant '{tenant_name}': {str(e)}")
    except Exception as e:
        logger.error("Unexpected error during Prometheus request", 
                    endpoint=endpoint, url=url, error=str(e), error_type=type(e).__name__,
                    tenant=tenant_name)
        raise

@mcp.tool(description="List all configured Prometheus tenants")
async def list_tenants() -> Dict[str, Any]:
    """List all configured Prometheus tenants.
    
    Returns:
        Dictionary with tenant information including names, URLs, and default tenant
    """
    logger.info("Listing configured tenants")
    
    tenant_info = []
    for tenant in config.tenants:
        info = {
            "name": tenant.name,
            "url": tenant.url,
            "has_auth": bool(tenant.username or tenant.token),
            "org_id": tenant.org_id
        }
        tenant_info.append(info)
    
    result = {
        "tenants": tenant_info,
        "default_tenant": config.default_tenant,
        "total_count": len(config.tenants)
    }
    
    logger.info("Tenants listed", tenant_count=len(config.tenants), default_tenant=config.default_tenant)
    return result

@mcp.tool(description="Execute a PromQL instant query against Prometheus")
async def execute_query(query: str, time: Optional[str] = None, tenant: Optional[str] = None) -> Dict[str, Any]:
    """Execute an instant query against Prometheus.
    
    Args:
        query: PromQL query string
        time: Optional RFC3339 or Unix timestamp (default: current time)
        tenant: Optional tenant name (default: use default tenant)
        
    Returns:
        Query result with type (vector, matrix, scalar, string) and values
    """
    params = {"query": query}
    if time:
        params["time"] = time
    
    tenant_name = tenant or config.default_tenant
    logger.info("Executing instant query", query=query, time=time, tenant=tenant_name)
    data = make_prometheus_request("query", params=params, tenant_name=tenant_name)
    
    result = {
        "resultType": data["resultType"],
        "result": data["result"],
        "tenant": tenant_name
    }
    
    logger.info("Instant query completed", 
                query=query, 
                result_type=data["resultType"], 
                result_count=len(data["result"]) if isinstance(data["result"], list) else 1,
                tenant=tenant_name)
    
    return result

@mcp.tool(description="Execute a PromQL range query with start time, end time, and step interval")
async def execute_range_query(query: str, start: str, end: str, step: str, tenant: Optional[str] = None) -> Dict[str, Any]:
    """Execute a range query against Prometheus.
    
    Args:
        query: PromQL query string
        start: Start time as RFC3339 or Unix timestamp
        end: End time as RFC3339 or Unix timestamp
        step: Query resolution step width (e.g., '15s', '1m', '1h')
        tenant: Optional tenant name (default: use default tenant)
        
    Returns:
        Range query result with type (usually matrix) and values over time
    """
    params = {
        "query": query,
        "start": start,
        "end": end,
        "step": step
    }
    
    tenant_name = tenant or config.default_tenant
    logger.info("Executing range query", query=query, start=start, end=end, step=step, tenant=tenant_name)
    data = make_prometheus_request("query_range", params=params, tenant_name=tenant_name)
    
    result = {
        "resultType": data["resultType"],
        "result": data["result"],
        "tenant": tenant_name
    }
    
    logger.info("Range query completed", 
                query=query, 
                result_type=data["resultType"], 
                result_count=len(data["result"]) if isinstance(data["result"], list) else 1,
                tenant=tenant_name)
    
    return result

@mcp.tool(description="List all available metrics in Prometheus")
async def list_metrics(limit: Optional[int] = None, tenant: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve a list of all metric names available in Prometheus.
    
    Args:
        limit: Optional maximum number of metrics to return
        tenant: Optional tenant name (default: use default tenant)
    
    Returns:
        Dictionary with metrics list and tenant information
    """
    params = {}
    if limit is not None:
        params = {"limit": limit}
        
    tenant_name = tenant or config.default_tenant
    logger.info("Listing available metrics", tenant=tenant_name)
    data = make_prometheus_request("label/__name__/values", params=params if params else None, tenant_name=tenant_name)
    
    result = {
        "metrics": data,
        "tenant": tenant_name,
        "count": len(data)
    }
    
    logger.info("Metrics list retrieved", metric_count=len(data), tenant=tenant_name)
    return result

@mcp.tool(description="Get metadata for a specific metric")
async def get_metric_metadata(metric: str, limit: Optional[int] = None, tenant: Optional[str] = None) -> Dict[str, Any]:
    """Get metadata about a specific metric.
    
    Args:
        metric: The name of the metric to retrieve metadata for
        limit: Optional maximum number of metadata entries to return
        tenant: Optional tenant name (default: use default tenant)
        
    Returns:
        Dictionary with metadata and tenant information
    """
    params = {"metric": metric}
    if limit is not None:
        params["limit"] = limit

    tenant_name = tenant or config.default_tenant
    logger.info("Retrieving metric metadata", metric=metric, tenant=tenant_name)
    data = make_prometheus_request("metadata", params=params, tenant_name=tenant_name)
    
    result = {
        "metadata": data["metadata"],
        "metric": metric,
        "tenant": tenant_name,
        "count": len(data["metadata"])
    }
    
    logger.info("Metric metadata retrieved", metric=metric, metadata_count=len(data["metadata"]), tenant=tenant_name)
    return result

@mcp.tool(description="Get information about all scrape targets")
async def get_targets(tenant: Optional[str] = None) -> Dict[str, Any]:
    """Get information about all Prometheus scrape targets.
    
    Args:
        tenant: Optional tenant name (default: use default tenant)
    
    Returns:
        Dictionary with active and dropped targets information
    """
    tenant_name = tenant or config.default_tenant
    logger.info("Retrieving scrape targets information", tenant=tenant_name)
    data = make_prometheus_request("targets", tenant_name=tenant_name)
    
    result = {
        "activeTargets": data["activeTargets"],
        "droppedTargets": data["droppedTargets"],
        "tenant": tenant_name,
        "active_count": len(data["activeTargets"]),
        "dropped_count": len(data["droppedTargets"])
    }
    
    logger.info("Scrape targets retrieved", 
                active_targets=len(data["activeTargets"]), 
                dropped_targets=len(data["droppedTargets"]),
                tenant=tenant_name)
    
    return result

@mcp.tool(description="Execute a query across all configured tenants")
async def execute_query_all_tenants(query: str, time: Optional[str] = None) -> Dict[str, Any]:
    """Execute an instant query against all configured Prometheus tenants.
    
    Args:
        query: PromQL query string
        time: Optional RFC3339 or Unix timestamp (default: current time)
        
    Returns:
        Dictionary with results from all tenants
    """
    params = {"query": query}
    if time:
        params["time"] = time
    
    logger.info("Executing query across all tenants", query=query, time=time, tenant_count=len(config.tenants))
    
    results = {}
    errors = {}
    
    for tenant in config.tenants:
        try:
            data = make_prometheus_request("query", params=params, tenant_name=tenant.name)
            results[tenant.name] = {
                "resultType": data["resultType"],
                "result": data["result"],
                "success": True
            }
        except Exception as e:
            logger.warning("Query failed for tenant", tenant=tenant.name, error=str(e))
            errors[tenant.name] = {
                "error": str(e),
                "success": False
            }
    
    result = {
        "query": query,
        "time": time,
        "results": results,
        "errors": errors,
        "successful_tenants": len(results),
        "failed_tenants": len(errors),
        "total_tenants": len(config.tenants)
    }
    
    logger.info("Multi-tenant query completed", 
                query=query,
                successful_tenants=len(results),
                failed_tenants=len(errors),
                total_tenants=len(config.tenants))
    
    return result

@mcp.tool(description="List all available label names in Prometheus")
async def list_labels(limit: Optional[int] = None, tenant: Optional[str] = None) -> List[str]:
    """Retrieve a list of all label names available in Prometheus.
    
    Args:
        limit: Optional maximum number of label names to return
    
    Returns:
        List of label names as strings
    """
    tenant_name = tenant or config.default_tenant
    params = {}
    if limit is not None:
        params["limit"] = limit
    
    logger.info("Listing available labels", limit=limit, tenant=tenant_name)
    data = make_prometheus_request("labels", params=params if params else None, tenant_name=tenant_name)
    logger.info("Labels list retrieved", label_count=len(data), limit=limit, tenant_name=tenant_name)
    return data

@mcp.tool(description="Get all values for a specific label")
async def get_label_values(label_name: str, limit: Optional[int] = None, tenant: Optional[str] = None) -> List[str]:
    """Get all possible values for a specific label.
    
    Args:
        label_name: The name of the label to retrieve values for
        limit: Optional maximum number of label values to return
        
    Returns:
        List of label values as strings
    """
    tenant_name = tenant or config.default_tenant
    params = {}
    if limit is not None:
        params["limit"] = limit
    
    logger.info("Retrieving label values", label_name=label_name, limit=limit, tenant_name=tenant_name)
    data = make_prometheus_request(f"label/{label_name}/values", params=params if params else None, tenant_name=tenant_name)
    logger.info("Label values retrieved", label_name=label_name, values_count=len(data), limit=limit, tenant_name=tenant_name)
    return data

@mcp.tool(description="Find time series by label matchers")
async def find_series(match: List[str], limit: Optional[int] = None, start: Optional[str] = None, end: Optional[str] = None, tenant: Optional[str] = None) -> List[Dict[str, str]]:
    """Find time series by label matchers.
    
    Args:
        match: List of series selector expressions (e.g., ['up', 'process_start_time_seconds{job="prometheus"}'])
        limit: Optional maximum number of series to return
        start: Optional start time as RFC3339 or Unix timestamp
        end: Optional end time as RFC3339 or Unix timestamp
        
    Returns:
        List of label sets representing the series
    """
    tenant_name = tenant or config.default_tenant
    params = {}
    # Add match parameters - requests library handles list values for 'match[]' automatically
    if match:
        params['match[]'] = match
    
    if limit is not None:
        params["limit"] = limit
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end
    
    logger.info("Finding series", match=match, limit=limit, start=start, end=end, tenant_name=tenant_name)
    data = make_prometheus_request("series", params=params, tenant_name=tenant_name)
    logger.info("Series found", series_count=len(data), limit=limit, tenant_name=tenant_name)
    return data

if __name__ == "__main__":
    logger.info("Starting Prometheus MCP Server", mode="direct", tenant_count=len(config.tenants))
    mcp.run()
