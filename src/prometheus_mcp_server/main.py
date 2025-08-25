#!/usr/bin/env python
import sys
import dotenv
from prometheus_mcp_server.server import mcp, config, TransportType
from prometheus_mcp_server.logging_config import setup_logging

# Initialize structured logging
logger = setup_logging()

def setup_environment():
    if dotenv.load_dotenv():
        logger.info("Environment configuration loaded", source=".env file")
    else:
        logger.info("Environment configuration loaded", source="environment variables", note="No .env file found")


    # Validate tenant configuration
    if not config.tenants:
        # Validate single tenant configuration
        logger.error(
            "Missing required configuration",
            error="No tenants configured",
            suggestion="Please set either PROMETHEUS_URL (single tenant) or PROMETHEUS_TENANTS (multi-tenant) environment variable"
        )
        return False
    
    # Log tenant configuration summary
    tenant_summary = []
    for tenant in config.tenants:
        auth_method = "none"
        if tenant.username and tenant.password:
            auth_method = "basic_auth"
        elif tenant.token:
            auth_method = "bearer_token"
        
        tenant_summary.append({
            "name": tenant.name,
            "url": tenant.url,
            "authentication": auth_method,
            "org_id": tenant.org_id if tenant.org_id else None
        })
    
    logger.info(
        "Multi-tenant Prometheus configuration validated",
        tenant_count=len(config.tenants),
        default_tenant=config.default_tenant,
        tenants=tenant_summary
    )

    # Validate MCP Server configuration
    mcp_config = config.mcp_server_config
    if mcp_config:
        if str(mcp_config.mcp_server_transport).lower() not in TransportType.values():
            logger.error(
                "Invalid mcp transport",
                error="PROMETHEUS_MCP_SERVER_TRANSPORT environment variable is invalid",
                suggestion="Please define one of these acceptable transports (http/sse/stdio)",
                example="http"
            )
            return False

        try:
            if mcp_config.mcp_bind_port:
                int(mcp_config.mcp_bind_port)
        except (TypeError, ValueError):
            logger.error(
                "Invalid mcp port",
                error="PROMETHEUS_MCP_BIND_PORT environment variable is invalid",
                suggestion="Please define an integer",
                example="8080"
            )
            return False
        
        logger.info(
            "MCP server configuration validated",
            transport=mcp_config.mcp_server_transport,
            host=mcp_config.mcp_bind_host,
            port=mcp_config.mcp_bind_port
        )

    else:
        logger.info(
            "MCP server configuration validated",
            mcp_server_config=mcp_config
        )
    
    return True

def run_server():
    """Main entry point for the Prometheus MCP Server"""
    # Setup environment
    if not setup_environment():
        logger.error("Environment setup failed, exiting")
        sys.exit(1)
    
    mcp_config = config.mcp_server_config
    transport = mcp_config.mcp_server_transport

    http_transports = [TransportType.HTTP.value, TransportType.SSE.value]
    if transport in http_transports:
        mcp.run(transport=transport, host=mcp_config.mcp_bind_host, port=mcp_config.mcp_bind_port)
        logger.info("Starting Prometheus MCP Server", 
                transport=transport, 
                host=mcp_config.mcp_bind_host,
                port=mcp_config.mcp_bind_port)
    else:
        mcp.run(transport=transport)
        logger.info("Starting Prometheus MCP Server", transport=transport)

if __name__ == "__main__":
    run_server()
