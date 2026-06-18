"""
Live integration tests for the MCP tool functions in mfp_mcp.server.

Calls the @mcp.tool-decorated functions directly as plain async functions
(FastMCP doesn't wrap them, so this works without spinning up a transport).
Requires creds.json (see conftest.py) -- skipped automatically if it's absent.
Every test cleans up the data it creates.
"""

import json

import pytest

from mfp_mcp import server

pytestmark = pytest.mark.live

TEST_DATE = "2030-01-01"  # far-future date, won't collide with real diary/measurement data


@pytest.fixture
def mfp_client():
    return server.get_mfp_client()


async def test_search_and_food_details():
    out = await server.mfp_search_food(server.SearchFoodInput(query="banana", limit=2, response_format="json"))
    parsed = json.loads(out)
    assert parsed["results"]
    mfp_id = parsed["results"][0]["mfp_id"]

    out = await server.mfp_get_food_details(server.GetFoodDetailsInput(mfp_id=mfp_id, response_format="json"))
    details = json.loads(out)
    assert details["description"]


async def test_add_food_to_diary_and_get_diary(mfp_client):
    out = await server.mfp_search_food(server.SearchFoodInput(query="banana", limit=1, response_format="json"))
    mfp_id = json.loads(out)["results"][0]["mfp_id"]

    out = await server.mfp_add_food_to_diary(
        server.AddFoodToDiaryInput(mfp_id=mfp_id, meal="Snacks", date=TEST_DATE, quantity=1.0)
    )
    added = json.loads(out)
    assert added["success"]
    entry_id = added["entry_id"]

    try:
        out = await server.mfp_get_diary(server.GetDiaryInput(date=TEST_DATE, response_format="json"))
        diary = json.loads(out)
        assert "Snacks" in diary["meals"]
    finally:
        mfp_client.delete_diary_entry(entry_id)


async def test_get_exercises_today():
    out = await server.mfp_get_exercises(server.GetExercisesInput(response_format="json"))
    parsed = json.loads(out)
    assert "exercises" in parsed


async def test_get_measurements():
    out = await server.mfp_get_measurements(server.GetMeasurementsInput(response_format="json"))
    parsed = json.loads(out)
    assert "values" in parsed


async def test_goals_round_trip():
    out = await server.mfp_get_goals(server.GetGoalsInput(response_format="json"))
    original_calories = int(json.loads(out)["goals"]["calories"])

    try:
        out = await server.mfp_set_goals(server.SetGoalsInput(calories=original_calories + 1))
        assert json.loads(out)["success"]

        out = await server.mfp_get_goals(server.GetGoalsInput(response_format="json"))
        assert json.loads(out)["goals"]["calories"] == original_calories + 1
    finally:
        await server.mfp_set_goals(server.SetGoalsInput(calories=original_calories))

    out = await server.mfp_get_goals(server.GetGoalsInput(response_format="json"))
    assert json.loads(out)["goals"]["calories"] == original_calories


async def test_water_round_trip():
    out = await server.mfp_get_water(server.GetWaterInput())
    original_ml = json.loads(out)["water_ml"]
    original_cups = round(original_ml / 236.588, 4)

    try:
        out = await server.mfp_set_water(server.SetWaterInput(cups=1.5))
        assert json.loads(out)["success"]

        out = await server.mfp_get_water(server.GetWaterInput())
        assert json.loads(out)["water_ml"] > 0
    finally:
        await server.mfp_set_water(server.SetWaterInput(cups=original_cups))

    out = await server.mfp_get_water(server.GetWaterInput())
    # rounding through cups<->ml is lossy -- assert "close enough", not exact
    assert abs(json.loads(out)["water_ml"] - original_ml) < 2.0


async def test_report_today():
    out = await server.mfp_get_report(server.GetReportInput(response_format="json"))
    parsed = json.loads(out)
    assert "values" in parsed
