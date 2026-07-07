# MyFitnessPal MCP Server
#
# Build: docker build -t mfp-mcp .
#
# Auth (recommended): log in once into a persistent volume, then run the server
# with that volume mounted -- no credentials in the run command:
#   docker run -it --rm -v mfp-tokens:/home/mcp/.mfp-mcp mfp-mcp mfp-mcp-auth
#   docker run -i --rm -v mfp-tokens:/home/mcp/.mfp-mcp mfp-mcp
#
# Fallback: docker run -i --rm -e MFP_USERNAME=... -e MFP_PASSWORD=... mfp-mcp

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

# Default command runs the MCP server with stdio transport; pass `mfp-mcp-auth`
# as the command instead for the one-time interactive login.
ENTRYPOINT ["uv", "run"]
CMD ["mfp-mcp"]
