"""
MyFitnessPal MCP Server

A Model Context Protocol (MCP) server that provides tools for interacting
with MyFitnessPal data including food diary, exercises, measurements, goals,
water intake, and food search.

Backed by `mfp_native`, a client for MyFitnessPal's native mobile-app API
(OAuth + REST v2), reverse-engineered from the Android app. This replaces
the previous website-HTML-scraping backend (`python-myfitnesspal`).

Authentication: set MFP_USERNAME and MFP_PASSWORD environment variables to
your MyFitnessPal account credentials.
"""

import json
import logging
import os
import sys
import threading
from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum
from collections import OrderedDict

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

from mfp_api import MfpClient, MfpApiError

# Configure logging to stderr (required for stdio transport)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("mfp_mcp")

# Initialize MCP server
mcp = FastMCP("myfitnesspal_mcp")


# ============================================================================
# Authentication
# ============================================================================

_client: Optional[MfpClient] = None
_client_lock = threading.Lock()


def get_mfp_client() -> MfpClient:
    """
    Get an authenticated MfpClient, logging in once and reusing the session
    (which refreshes its own access token as needed) for subsequent calls.

    Raises:
        RuntimeError: If MFP_USERNAME/MFP_PASSWORD aren't set or login fails.
    """
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        username = os.environ.get("MFP_USERNAME")
        password = os.environ.get("MFP_PASSWORD")
        if not username or not password:
            raise RuntimeError(
                "MFP_USERNAME and MFP_PASSWORD environment variables must be set "
                "to your MyFitnessPal account credentials."
            )

        logger.info("Logging into MyFitnessPal native API")
        _client = MfpClient.login(username, password)
        return _client


# ============================================================================
# Data Formatting Helper Functions
# ============================================================================


def parse_date(date_str: Optional[str] = None) -> date:
    """Parse a date string or return today's date."""
    if date_str is None:
        return date.today()
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def _energy_value(value: Any) -> Any:
    """nutritional_contents['energy'] is {'value','unit'}; everything else is a plain number."""
    if isinstance(value, dict):
        return value.get("value")
    return value


def _flatten_nutrition(nutrition: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    flat = dict(nutrition or {})
    if "energy" in flat:
        flat["energy"] = _energy_value(flat["energy"])
    return flat


def _flatten_default_goal(default_goal: Dict[str, Any]) -> Dict[str, Any]:
    flat = {k: v for k, v in default_goal.items()}
    energy = flat.pop("energy", None)
    flat["calories"] = _energy_value(energy)
    return flat


def ordered_dict_to_dict(od) -> Dict[str, Any]:
    """Convert OrderedDict (possibly with date keys) to a plain str-keyed dict."""
    return {str(k): v for k, v in od.items()}


class ResponseFormat(str, Enum):
    """Output format for tool responses."""

    MARKDOWN = "markdown"
    JSON = "json"


def format_response(data: Any, format_type: ResponseFormat, title: str = "") -> str:
    """Format response data based on requested format."""
    if format_type == ResponseFormat.JSON:
        return json.dumps(data, indent=2, default=str)

    lines = []
    if title:
        lines.append(f"## {title}\n")

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"### {key}")
                for k, v in value.items():
                    lines.append(f"- **{k}**: {v}")
            elif isinstance(value, list):
                lines.append(f"### {key}")
                for item in value:
                    if isinstance(item, dict):
                        lines.append(f"- {item.get('name', str(item))}")
                        for k, v in item.items():
                            if k != "name":
                                lines.append(f"  - {k}: {v}")
                    else:
                        lines.append(f"- {item}")
            else:
                lines.append(f"- **{key}**: {value}")
    else:
        lines.append(str(data))

    return "\n".join(lines)


# ============================================================================
# Pydantic Input Models
# ============================================================================


class GetDiaryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: Optional[str] = Field(
        default=None,
        description="Date in YYYY-MM-DD format. Defaults to today if not specified.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for human-readable or 'json' for structured data",
    )


class SearchFoodInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(
        ...,
        description="Search query for food items (e.g., 'chicken breast', 'apple')",
        min_length=1,
        max_length=200,
    )
    limit: int = Field(default=10, description="Maximum number of results to return", ge=1, le=50)
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for human-readable or 'json' for structured data",
    )


class GetFoodDetailsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mfp_id: str = Field(
        ..., description="MyFitnessPal food item ID (obtained from search results)", min_length=1
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for human-readable or 'json' for structured data",
    )


class GetMeasurementsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    measurement: str = Field(
        default="Weight",
        description="Type of measurement to retrieve, e.g. 'Weight' (capitalized -- this is the server's canonical form).",
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Start date in YYYY-MM-DD format. Defaults to 30 days ago.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    end_date: Optional[str] = Field(
        default=None,
        description="End date in YYYY-MM-DD format. Defaults to today.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for human-readable or 'json' for structured data",
    )


class SetMeasurementInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    measurement: str = Field(default="Weight", description="Type of measurement to set, e.g. 'Weight'.")
    value: float = Field(..., description="Measurement value (e.g., 185.5 for weight in lbs)", gt=0)


class GetExercisesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: Optional[str] = Field(
        default=None,
        description="Date in YYYY-MM-DD format. Defaults to today if not specified.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for human-readable or 'json' for structured data",
    )


class GetGoalsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: Optional[str] = Field(
        default=None,
        description="Date in YYYY-MM-DD format. Goals are account-wide, not per-day, so this is accepted for compatibility but doesn't change the result.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for human-readable or 'json' for structured data",
    )


class SetGoalsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    calories: Optional[int] = Field(default=None, description="Daily calorie goal (e.g., 2000)", ge=500, le=10000)
    protein: Optional[int] = Field(default=None, description="Daily protein goal in grams", ge=0, le=1000)
    carbohydrates: Optional[int] = Field(
        default=None, description="Daily carbohydrate goal in grams", ge=0, le=2000
    )
    fat: Optional[int] = Field(default=None, description="Daily fat goal in grams", ge=0, le=500)


class GetWaterInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: Optional[str] = Field(
        default=None,
        description="Date in YYYY-MM-DD format. Defaults to today if not specified.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )


class GetReportInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    report_name: str = Field(
        default="Net Calories",
        description="Report name (e.g., 'Net Calories', 'Protein', 'Fat', 'Carbs'). Unrecognized names fall back to calories.",
    )
    start_date: Optional[str] = Field(
        default=None, description="Start date in YYYY-MM-DD format. Defaults to 7 days ago.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    end_date: Optional[str] = Field(
        default=None, description="End date in YYYY-MM-DD format. Defaults to today.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' for human-readable or 'json' for structured data",
    )


class AddFoodToDiaryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    mfp_id: str = Field(..., description="MyFitnessPal food item ID (obtained from mfp_search_food)", min_length=1)
    meal: str = Field(default="Breakfast", description="Meal name (e.g., 'Breakfast', 'Lunch', 'Dinner', 'Snacks')")
    date: Optional[str] = Field(
        default=None,
        description="Date in YYYY-MM-DD format. Defaults to today if not specified.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    quantity: float = Field(default=1.0, description="Quantity/servings (e.g., 1.5 for 1.5 servings)", gt=0, le=100)
    unit: Optional[str] = Field(
        default=None,
        description="Unit/serving size to log (e.g., 'g', 'oz', 'cup'). Must match one of the food's available "
        "serving size units (see mfp_get_food_details). If not provided, uses the food's default serving size.",
    )


class SetWaterInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    cups: float = Field(
        ..., description="Number of cups of water (e.g., 2.5 for 2.5 cups).", ge=0, le=50
    )
    date: Optional[str] = Field(
        default=None,
        description="Date in YYYY-MM-DD format. Defaults to today if not specified.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )


REPORT_NAME_TO_NUTRIENT = {
    "net calories": "energy",
    "total calories": "energy",
    "calories": "energy",
    "protein": "protein",
    "fat": "fat",
    "carbs": "carbohydrates",
    "carbohydrates": "carbohydrates",
    "sodium": "sodium",
    "sugar": "sugar",
    "fiber": "fiber",
}


# ============================================================================
# MCP Tools
# ============================================================================


@mcp.tool(
    name="mfp_get_diary",
    annotations={
        "title": "Get Food Diary",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mfp_get_diary(params: GetDiaryInput) -> str:
    """
    Get the food diary for a specific date including all meals and their nutritional information.

    Returns meals (Breakfast, Lunch, Dinner, Snacks, etc.) with each food entry's name,
    quantity, and complete nutrition breakdown (calories, protein, carbs, fat, etc.).
    Also includes daily totals, goals, and water intake.
    """
    try:
        client = get_mfp_client()
        target_date = parse_date(params.date)
        entries = client.get_food_diary(target_date)

        meals: Dict[str, Any] = {}
        daily_totals: Dict[str, float] = {}
        for entry in entries:
            meal_name = entry.get("meal_name", "Other")
            food = entry.get("food") or {}
            nutrition = _flatten_nutrition(entry.get("nutritional_contents"))
            serving = entry.get("serving_size") or {}
            meals.setdefault(meal_name, {"entries": [], "totals": {}})
            meals[meal_name]["entries"].append(
                {
                    "name": food.get("description"),
                    "brand": food.get("brand_name") or None,
                    "servings": entry.get("servings"),
                    "unit": serving.get("unit"),
                    "nutrition": nutrition,
                }
            )
            for key, value in nutrition.items():
                if isinstance(value, (int, float)):
                    meals[meal_name]["totals"][key] = meals[meal_name]["totals"].get(key, 0.0) + value
                    daily_totals[key] = daily_totals.get(key, 0.0) + value

        goals = client.get_goals()
        water_ml = client.get_water(target_date)

        data = {
            "date": str(target_date),
            "meals": meals,
            "daily_totals": daily_totals,
            "daily_goals": _flatten_default_goal(goals["default_goal"]),
            "water_ml": water_ml if water_ml is not None else 0.0,
        }

        return format_response(data, params.response_format, f"Food Diary for {target_date}")

    except Exception as e:
        return f"Error retrieving diary: {str(e)}"


@mcp.tool(
    name="mfp_search_food",
    annotations={
        "title": "Search Food Database",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mfp_search_food(params: SearchFoodInput) -> str:
    """
    Search the MyFitnessPal food database for food items.

    Returns a list of matching foods with their name, brand, default serving size,
    calories, and MFP ID (which can be used with mfp_get_food_details / mfp_add_food_to_diary).
    """
    try:
        client = get_mfp_client()
        results = client.search_food(params.query, limit=params.limit)

        data = {"query": params.query, "count": len(results), "results": []}
        for wrapped in results:
            item = wrapped.get("item", wrapped)
            nutrition = item.get("nutritional_contents") or {}
            servings = item.get("serving_sizes") or []
            default_serving = next((s for s in servings if s.get("index") == 0), servings[0] if servings else None)
            data["results"].append(
                {
                    "name": item.get("description"),
                    "brand": item.get("brand_name") or None,
                    "serving": f"{default_serving['value']} {default_serving['unit']}" if default_serving else None,
                    "calories": _energy_value(nutrition.get("energy")),
                    "mfp_id": item.get("id"),
                }
            )

        return format_response(data, params.response_format, f"Food Search Results for '{params.query}'")

    except Exception as e:
        return f"Error searching foods: {str(e)}"


@mcp.tool(
    name="mfp_get_food_details",
    annotations={
        "title": "Get Food Item Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mfp_get_food_details(params: GetFoodDetailsInput) -> str:
    """
    Get detailed nutritional information for a specific food item by its MFP ID.

    Returns complete nutrition breakdown including calories, macros, fiber, sugar,
    sodium, cholesterol, vitamins, minerals, and available serving sizes.
    """
    try:
        client = get_mfp_client()
        item = client.get_food(params.mfp_id)
        nutrition = _flatten_nutrition(item.get("nutritional_contents"))
        calories = nutrition.pop("energy", None)

        data = {
            "mfp_id": params.mfp_id,
            "description": item.get("description", "N/A"),
            "brand_name": item.get("brand_name") or None,
            "verified": item.get("verified", False),
            "calories": calories,
            "nutrition": nutrition,
            "servings": [f"{s['value']} {s['unit']}" for s in item.get("serving_sizes") or []],
        }

        return format_response(data, params.response_format, "Food Item Details")

    except Exception as e:
        return f"Error getting food details: {str(e)}"


@mcp.tool(
    name="mfp_get_measurements",
    annotations={
        "title": "Get Body Measurements",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mfp_get_measurements(params: GetMeasurementsInput) -> str:
    """
    Get body measurements (weight, body fat, etc.) over a date range.

    Returns historical measurement data with dates and values. Useful for
    tracking weight loss progress and body composition changes.
    """
    try:
        client = get_mfp_client()

        end = parse_date(params.end_date)
        start = parse_date(params.start_date) if params.start_date else end - timedelta(days=30)

        items = client.get_measurements(params.measurement, start_date=start, end_date=end)
        values = OrderedDict(
            (item["date"], item["value"]) for item in sorted(items, key=lambda i: i["date"])
        )

        data = {
            "measurement_type": params.measurement,
            "start_date": str(start),
            "end_date": str(end),
            "count": len(values),
            "values": ordered_dict_to_dict(values),
        }

        if values:
            vals = list(values.values())
            data["summary"] = {
                "latest": vals[-1],
                "earliest": vals[0],
                "change": round(vals[-1] - vals[0], 2) if len(vals) >= 2 else 0,
                "min": min(vals),
                "max": max(vals),
                "average": round(sum(vals) / len(vals), 2),
            }

        return format_response(data, params.response_format, f"{params.measurement} History")

    except Exception as e:
        return f"Error getting measurements: {str(e)}"


@mcp.tool(
    name="mfp_set_measurement",
    annotations={
        "title": "Log Body Measurement",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def mfp_set_measurement(params: SetMeasurementInput) -> str:
    """
    Log a new body measurement (weight, body fat, etc.) for today.

    Upserts by date -- logging again for today updates today's entry rather
    than creating a duplicate.
    """
    try:
        client = get_mfp_client()
        result = client.set_measurement(params.value, measurement_type=params.measurement, target_date=date.today())

        return json.dumps(
            {
                "success": True,
                "message": f"Successfully logged {params.measurement}: {params.value}",
                "measurement": params.measurement,
                "value": params.value,
                "date": result.get("date", str(date.today())),
            },
            indent=2,
        )

    except Exception as e:
        return f"Error setting measurement: {str(e)}"


@mcp.tool(
    name="mfp_get_exercises",
    annotations={
        "title": "Get Exercise Log",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mfp_get_exercises(params: GetExercisesInput) -> str:
    """
    Get logged exercises for a specific date.

    Returns exercises with their details (duration, calories burned, start time).
    """
    try:
        client = get_mfp_client()
        target_date = parse_date(params.date)
        entries = client.get_exercise_diary(target_date)

        exercises = []
        total_burned = 0.0
        for entry in entries:
            ex = entry.get("exercise") or {}
            calories = _energy_value(entry.get("energy"))
            if isinstance(calories, (int, float)):
                total_burned += calories
            exercises.append(
                {
                    "name": ex.get("description"),
                    "type": ex.get("type"),
                    "duration_seconds": entry.get("duration"),
                    "calories_burned": calories,
                    "start_time": entry.get("start_time"),
                    "entry_id": entry.get("id"),
                }
            )

        data = {
            "date": str(target_date),
            "exercises": exercises,
            "total_calories_burned": total_burned,
        }

        return format_response(data, params.response_format, f"Exercise Log for {target_date}")

    except Exception as e:
        return f"Error getting exercises: {str(e)}"


@mcp.tool(
    name="mfp_get_goals",
    annotations={
        "title": "Get Nutrition Goals",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mfp_get_goals(params: GetGoalsInput) -> str:
    """
    Get the user's daily nutrition goals (calories, protein, carbs, fat, etc.).

    Goals are a single account-wide record in MyFitnessPal, not per-day.
    """
    try:
        client = get_mfp_client()
        goals = client.get_goals()

        data = {"date": str(parse_date(params.date)), "goals": _flatten_default_goal(goals["default_goal"])}

        return format_response(data, params.response_format, "Daily Nutrition Goals")

    except Exception as e:
        return f"Error getting goals: {str(e)}"


@mcp.tool(
    name="mfp_set_goals",
    annotations={
        "title": "Update Nutrition Goals",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mfp_set_goals(params: SetGoalsInput) -> str:
    """
    Update daily nutrition goals (calories, protein, carbs, fat).

    Only updates the values that are provided; others remain unchanged.
    """
    try:
        if not any([params.calories, params.protein, params.carbohydrates, params.fat]):
            return "Error: Please provide at least one goal to update (calories, protein, carbohydrates, or fat)"

        client = get_mfp_client()
        current = client.get_goals()
        default_goal = dict(current["default_goal"])

        if params.calories is not None:
            default_goal["energy"] = {**default_goal["energy"], "value": params.calories}
        if params.protein is not None:
            default_goal["protein"] = params.protein
        if params.carbohydrates is not None:
            default_goal["carbohydrates"] = params.carbohydrates
        if params.fat is not None:
            default_goal["fat"] = params.fat

        client.set_goals(default_goal, current["daily_goals"], valid_from=current["valid_from"])

        return json.dumps(
            {
                "success": True,
                "message": "Successfully updated nutrition goals",
                "updated_goals": {
                    "calories": params.calories,
                    "protein": params.protein,
                    "carbohydrates": params.carbohydrates,
                    "fat": params.fat,
                },
            },
            indent=2,
        )

    except Exception as e:
        return f"Error setting goals: {str(e)}"


@mcp.tool(
    name="mfp_get_water",
    annotations={
        "title": "Get Water Intake",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mfp_get_water(params: GetWaterInput) -> str:
    """
    Get water intake for a specific date.

    Returns the amount of water logged for the day, in both milliliters and cups.
    """
    try:
        client = get_mfp_client()
        target_date = parse_date(params.date)
        ml = client.get_water(target_date)
        ml = ml if ml is not None else 0.0

        data = {
            "date": str(target_date),
            "water_ml": ml,
            "water_cups": round(ml / 236.588, 3),
        }

        return json.dumps(data, indent=2)

    except Exception as e:
        return f"Error getting water intake: {str(e)}"


@mcp.tool(
    name="mfp_add_food_to_diary",
    annotations={
        "title": "Add Food to Diary",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def mfp_add_food_to_diary(params: AddFoodToDiaryInput) -> str:
    """
    Add a food item to your MyFitnessPal food diary for a specific date and meal.

    Search for foods using mfp_search_food to find the food ID (mfp_id) needed for this tool.
    """
    try:
        client = get_mfp_client()
        target_date = parse_date(params.date)

        meal = params.meal.strip().capitalize()
        if meal.lower() == "snack":
            meal = "Snacks"

        food = client.get_food(params.mfp_id)
        servings_list = food.get("serving_sizes") or []
        if not servings_list:
            return f"Error adding food to diary: food {params.mfp_id} has no serving sizes available"

        serving_size = None
        if params.unit:
            unit_lower = params.unit.strip().lower()
            serving_size = next((s for s in servings_list if s.get("unit", "").lower() == unit_lower), None)
        if serving_size is None:
            serving_size = next((s for s in servings_list if s.get("index") == 0), servings_list[0])

        entry = client.add_food_entry(
            params.mfp_id,
            serving_size=serving_size,
            meal_name=meal,
            target_date=target_date,
            servings=params.quantity,
        )

        return json.dumps(
            {
                "success": True,
                "message": f"Successfully added {food.get('description', 'food item')} to {meal}",
                "date": str(target_date),
                "meal": meal,
                "food_id": params.mfp_id,
                "food_name": food.get("description"),
                "quantity": params.quantity,
                "unit": serving_size.get("unit"),
                "entry_id": entry.get("id"),
            },
            indent=2,
        )

    except Exception as e:
        return f"Error adding food to diary: {str(e)}"


@mcp.tool(
    name="mfp_set_water",
    annotations={
        "title": "Log Water Intake",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def mfp_set_water(params: SetWaterInput) -> str:
    """
    Log water intake for a specific date.

    Sets the total cups of water for the day (replaces, not additive -- this
    matches how MyFitnessPal's own water endpoint behaves).
    """
    try:
        client = get_mfp_client()
        target_date = parse_date(params.date)

        # Posting units="cups" truncates to whole cups server-side before converting
        # (1.5 cups -> 1 cup -> 240ml, confirmed live) -- convert to milliliters
        # ourselves and post that instead so fractional cups aren't lost.
        milliliters = round(params.cups * 236.588, 2)
        client.set_water(target_date=target_date, milliliters=milliliters)

        return json.dumps(
            {
                "success": True,
                "message": f"Successfully logged {params.cups} cups of water",
                "date": str(target_date),
                "cups": params.cups,
                "milliliters": milliliters,
            },
            indent=2,
        )

    except Exception as e:
        return f"Error setting water intake: {str(e)}"


@mcp.tool(
    name="mfp_get_report",
    annotations={
        "title": "Get Nutrition Report",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def mfp_get_report(params: GetReportInput) -> str:
    """
    Get a nutrition report over a date range.

    Returns daily values for the specified nutrient/metric over the date range.
    Computed client-side by aggregating each day's food diary -- MyFitnessPal's
    server has no report endpoint of its own.
    """
    try:
        client = get_mfp_client()

        end = parse_date(params.end_date)
        start = parse_date(params.start_date) if params.start_date else end - timedelta(days=7)

        nutrient_key = REPORT_NAME_TO_NUTRIENT.get(params.report_name.strip().lower(), "energy")
        daily_totals = client.get_report(start, end)
        values = OrderedDict(
            (day, totals.get(nutrient_key, 0.0)) for day, totals in sorted(daily_totals.items())
        )

        data = {
            "report_name": params.report_name,
            "start_date": str(start),
            "end_date": str(end),
            "values": ordered_dict_to_dict(values),
        }

        numeric_values = list(values.values())
        if numeric_values:
            data["summary"] = {
                "total": sum(numeric_values),
                "average": round(sum(numeric_values) / len(numeric_values), 2),
                "min": min(numeric_values),
                "max": max(numeric_values),
            }

        return format_response(data, params.response_format, f"{params.report_name} Report")

    except Exception as e:
        return f"Error getting report: {str(e)}"


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
