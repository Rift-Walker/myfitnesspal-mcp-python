# MyFitnessPal MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that enables AI
assistants like Claude to interact with your MyFitnessPal data: food diary, exercises, body
measurements, nutrition goals, and water intake.

Backed by [`mfp-api`](https://github.com/Rift-Walker/mfp-api), a client for MyFitnessPal's
**native mobile-app API** (the same JSON API the Android/iOS apps use), not website scraping.

## Features

| Tool | Type | Description |
|------|------|-------------|
| `mfp_get_diary` | Read | Get food diary entries for any date |
| `mfp_search_food` | Read | Search the MyFitnessPal food database |
| `mfp_get_food_details` | Read | Get detailed nutrition info for a food item |
| `mfp_add_food_to_diary` | Write | Add a food item to your diary for a specific meal and date |
| `mfp_get_measurements` | Read | Get weight/body measurement history |
| `mfp_set_measurement` | Write | Log a new weight or body measurement |
| `mfp_get_exercises` | Read | Get logged exercises (cardio & strength) |
| `mfp_get_goals` | Read | Get daily nutrition goals |
| `mfp_set_goals` | Write | Update daily nutrition goals |
| `mfp_get_water` | Read | Get water intake for a date |
| `mfp_set_water` | Write | Log water intake for a date |
| `mfp_get_report` | Read | Get nutrition reports over a date range |

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) installed
- A MyFitnessPal account (username/email + password)

## Configuration for Claude Desktop / Claude Code

Add this to your MCP client config (`claude_desktop_config.json` or `.mcp.json`):

```json
{
  "mcpServers": {
    "myfitnesspal": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Rift-Walker/myfitnesspal-mcp-python", "mfp-mcp"],
      "env": {
        "MFP_USERNAME": "your_email@example.com",
        "MFP_PASSWORD": "your_password"
      }
    }
  }
}
```

`uvx` fetches the server (and its `mfp-api` dependency) straight from GitHub and runs it — no
local clone or virtualenv needed. Restart your MCP client after saving the config.

To run from a local clone instead (e.g. for development):

```bash
git clone https://github.com/Rift-Walker/myfitnesspal-mcp-python
cd myfitnesspal-mcp-python
uv sync
uv run mfp-mcp
```

and point `command`/`args` at `uv run --directory /path/to/mfp-mcp mfp-mcp` instead.

## Authentication

Set `MFP_USERNAME` and `MFP_PASSWORD` in the `env` block of your MCP client config, as shown
above. That's the only supported method — credentials live solely in that local config file
(never committed, never logged) and are read once via `os.environ.get(...)` to log in. The server
keeps the resulting access token in memory and refreshes it automatically; there are no cookies,
no browser dependency, and nothing written to disk.

## Usage Examples

Once configured, you can interact with your MyFitnessPal data through Claude:

```
"Show me what I ate today"
"Search MyFitnessPal for chicken breast"
"Log my weight as 180 pounds"
"What exercises did I log today?"
"Compare my nutrition goals to what I actually ate today"
"Show my calorie intake over the past week"
```

## Development

```bash
git clone https://github.com/Rift-Walker/myfitnesspal-mcp-python
cd myfitnesspal-mcp-python
uv sync --extra dev
```

### Run tests

Live tests hit a real MyFitnessPal account via a local `creds.json`
(`{"username": "...", "password": "..."}`, gitignored, **never commit this file**). They're
marked `@pytest.mark.live` and skip automatically if no creds file is found.

```bash
uv run pytest
```

### Code quality

```bash
uv run black src/ tests/
uv run isort src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
```

## Troubleshooting

**"MFP_USERNAME and MFP_PASSWORD environment variables must be set"** — add them to the `env`
block in your MCP client config (see above) and restart the client.

**Tools not appearing** — check your config file is valid JSON, restart the client completely,
and check its logs (macOS: `~/Library/Logs/Claude/`; Windows: `%APPDATA%\Claude\logs\`).

**Empty responses** — verify you have data logged in MyFitnessPal for the requested date, and
that dates are `YYYY-MM-DD`.

## API Reference

### mfp_get_diary
Get food diary for a specific date.
- `date` (optional): YYYY-MM-DD format, defaults to today
- `response_format`: "markdown" or "json"

### mfp_search_food
Search the MyFitnessPal food database.
- `query` (required): Search term
- `limit` (optional): Max results (default 10, max 50)
- `response_format`: "markdown" or "json"

### mfp_get_food_details
Get detailed nutrition for a food item.
- `mfp_id` (required): MyFitnessPal food ID from search results
- `response_format`: "markdown" or "json"

### mfp_add_food_to_diary
Add a food item to your diary for a specific meal and date.
- `mfp_id` (required): MyFitnessPal food ID from search results (use `mfp_search_food` first)
- `meal` (optional): Meal name - "Breakfast", "Lunch", "Dinner", or "Snacks" (default: "Breakfast")
- `date` (optional): YYYY-MM-DD format (default: today)
- `quantity` (optional): Number of servings (default: 1.0)
- `unit` (optional): Serving size unit to log (e.g. "g", "oz", "cup") -- must match one of the
  food's available serving sizes (see `mfp_get_food_details`); defaults to the food's default
  serving size if omitted

**Example workflow:** use `mfp_search_food` to find a food item and get its `mfp_id`, then
`mfp_add_food_to_diary` with that `mfp_id` to add it to your diary.

### mfp_get_measurements
Get body measurement history.
- `measurement` (optional): e.g. "Weight" (default; this is the server's canonical capitalized form)
- `start_date` (optional): YYYY-MM-DD (default 30 days ago)
- `end_date` (optional): YYYY-MM-DD (default today)
- `response_format`: "markdown" or "json"

### mfp_set_measurement
Log a body measurement for today.
- `measurement` (optional): Type (default "Weight")
- `value` (required): Numeric value

### mfp_get_exercises
Get exercise log for a date.
- `date` (optional): YYYY-MM-DD (default today)
- `response_format`: "markdown" or "json"

### mfp_get_goals
Get daily nutrition goals. Goals are a single account-wide record in MyFitnessPal, not per-day.
- `date` (optional): accepted for compatibility but doesn't change the result
- `response_format`: "markdown" or "json"

### mfp_set_goals
Update nutrition goals. Only updates the values provided; others remain unchanged.
- `calories` (optional): Daily calorie goal
- `protein` (optional): Daily protein in grams
- `carbohydrates` (optional): Daily carbs in grams
- `fat` (optional): Daily fat in grams

### mfp_get_water
Get water intake for a date.
- `date` (optional): YYYY-MM-DD (default today)

### mfp_set_water
Log water intake for a date. Replaces the day's total, not additive (matches MyFitnessPal's own
water endpoint behavior).
- `cups` (required): Number of cups of water (e.g., 2.5 for 2.5 cups)
- `date` (optional): YYYY-MM-DD format (default: today)

### mfp_get_report
Get a nutrition report over a date range, computed client-side from daily diary totals.
- `report_name` (optional): "Net Calories", "Protein", "Fat", "Carbs" (unrecognized names fall back to calories)
- `start_date` (optional): YYYY-MM-DD (default 7 days ago)
- `end_date` (optional): YYYY-MM-DD (default today)
- `response_format`: "markdown" or "json"

## Security & Privacy

- Credentials live only in your local MCP client config file, read via environment variables.
  Nothing is written to disk by this server, and credentials are never logged.
- The server runs locally via stdio transport. Your data is only transmitted between your machine
  and MyFitnessPal's own servers — nothing goes to any third party.

## License

MIT License - See [LICENSE](LICENSE) file for details.

## Acknowledgments

- [mfp-api](https://github.com/Rift-Walker/mfp-api) - native MyFitnessPal API client backing this server
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) - Model Context Protocol framework
- [Anthropic](https://anthropic.com) - Claude and the MCP specification
