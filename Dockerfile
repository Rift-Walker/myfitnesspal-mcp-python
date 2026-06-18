# MyFitnessPal MCP Server
#
# Auth is via MFP_USERNAME/MFP_PASSWORD environment variables only -- pass them
# with `docker run -e`, no cookie mounting needed.
#
# Build: docker build -t mfp-mcp .
# Run:   docker run -it --rm -e MFP_USERNAME=... -e MFP_PASSWORD=... mfp-mcp

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Resolve and install the package (including the mfp-api git dependency) via uv
RUN uv sync --no-dev

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash mcp
USER mcp

# Default command runs the MCP server with stdio transport
ENTRYPOINT ["uv", "run", "mfp-mcp"]
