"""Main entry point for the Nearest Open Restaurants & Food Ordering Apps Scraper Actor."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List

import httpx

from .scraper import geocode, scrape_swiggy, scrape_ubereats

# Safe import for Apify SDK with standalone fallback
try:
    from apify import Actor, Event
    HAS_APIFY = True
except ImportError:
    HAS_APIFY = False


class StandaloneLogger:
    """Fallback logger when running locally outside of the Apify platform."""

    @staticmethod
    def info(msg: str) -> None:
        print(f"[INFO] {msg}", flush=True)

    @staticmethod
    def warning(msg: str) -> None:
        print(f"[WARN] {msg}", flush=True)

    @staticmethod
    def error(msg: str) -> None:
        print(f"[ERROR] {msg}", file=sys.stderr, flush=True)


async def save_standalone_dataset(items: List[Dict[str, Any]]) -> None:
    """Save items to local Apify-compatible dataset storage."""
    dataset_dir = Path("storage/datasets/default")
    dataset_dir.mkdir(parents=True, exist_ok=True)
    for idx, item in enumerate(items, start=1):
        item_path = dataset_dir / f"{idx:09d}.json"
        with open(item_path, "w", encoding="utf-8") as f:
            json.dump(item, f, indent=2, ensure_ascii=False)


async def load_standalone_input() -> Dict[str, Any]:
    """Read input from local key-value store if present."""
    input_path = Path("storage/key_value_stores/default/INPUT.json")
    if input_path.exists():
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


async def run_scraper(
    actor_input: Dict[str, Any],
    log: Any,
    push_data_fn: Any,
) -> None:
    """Core orchestrator for fetching nearest restaurants and detecting food ordering apps."""
    location_str = actor_input.get("location", "Times Square, New York, NY").strip()
    lat = actor_input.get("latitude")
    lng = actor_input.get("longitude")
    only_open = bool(actor_input.get("only_open", True))
    max_restaurants = int(actor_input.get("max_restaurants", 20))
    detect_apps = bool(actor_input.get("detect_ordering_apps", True))
    search_query = actor_input.get("search_query", "").strip()

    log.info(
        f"Starting search for nearest restaurants near '{location_str}' "
        f"(only_open={only_open}, max={max_restaurants}, query='{search_query}', detect_apps={detect_apps})"
    )

    resolved_country = None

    # Step 1: Geocoding
    if lat is None or lng is None:
        log.info(f"Geocoding location '{location_str}'...")
        async with httpx.AsyncClient() as client:
            geo_res = await geocode(location_str, client)

        if not geo_res:
            log.error(f"Could not resolve geocoordinates for location '{location_str}'.")
            return

        lat, lng, display_name, resolved_country = geo_res
        log.info(f"Resolved coordinates: ({lat:.4f}, {lng:.4f}) - '{display_name}'")
    else:
        lat = float(lat)
        lng = float(lng)
        log.info(f"Using provided coordinates: ({lat:.4f}, {lng:.4f})")

    # Step 2: Determine appropriate data provider
    # If India coordinates or country code is IN, use Swiggy; otherwise use Uber Eats
    is_india = (
        resolved_country == "IN"
        or (8.0 <= lat <= 37.5 and 68.0 <= lng <= 97.5)
        or "india" in location_str.lower()
    )

    restaurants: List[Dict[str, Any]] = []

    if is_india:
        log.info(f"Location is in India, querying Swiggy provider at ({lat:.4f}, {lng:.4f})...")
        restaurants = await scrape_swiggy(
            lat=lat,
            lng=lng,
            location_label=location_str,
            search_query=search_query,
            only_open=only_open,
            max_restaurants=max_restaurants,
            detect_apps=detect_apps,
        )

    # If not India or Swiggy returned empty, query Uber Eats
    if not restaurants:
        log.info(f"Querying Uber Eats provider at ({lat:.4f}, {lng:.4f})...")
        restaurants = await scrape_ubereats(
            lat=lat,
            lng=lng,
            location_label=location_str,
            search_query=search_query,
            only_open=only_open,
            max_restaurants=max_restaurants,
            detect_apps=detect_apps,
        )

    if not restaurants:
        log.warning(f"No restaurants found matching criteria at ({lat}, {lng}).")
        return

    # Step 3: Push items to dataset with tracking count
    pushed_tally = 0
    for r in restaurants:
        await push_data_fn(r)
        pushed_tally += 1

    log.info(f"Successfully scraped and pushed {pushed_tally} nearest restaurants to dataset.")


async def main() -> None:
    """Apify Actor main execution flow."""
    if HAS_APIFY:
        async with Actor:
            # Handle graceful abort
            async def on_aborting() -> None:
                Actor.log.info("Actor is aborting. Finalizing state...")
                await asyncio.sleep(1)
                await Actor.exit()

            Actor.on(Event.ABORTING, on_aborting)

            # Retrieve Actor input
            actor_input = await Actor.get_input() or {}
            await run_scraper(
                actor_input=actor_input,
                log=Actor.log,
                push_data_fn=Actor.push_data,
            )
    else:
        # Standalone execution fallback
        log = StandaloneLogger()
        log.info("Running in standalone mode (Apify SDK not in environment).")
        actor_input = await load_standalone_input()
        if not actor_input:
            actor_input = {
                "location": "Times Square, New York, NY",
                "only_open": True,
                "max_restaurants": 10,
                "detect_ordering_apps": True,
            }

        collected_items: List[Dict[str, Any]] = []

        async def standalone_push(item: Dict[str, Any]) -> None:
            collected_items.append(item)

        await run_scraper(
            actor_input=actor_input,
            log=log,
            push_data_fn=standalone_push,
        )

        await save_standalone_dataset(collected_items)
        log.info(f"Saved {len(collected_items)} items to storage/datasets/default/")


if __name__ == "__main__":
    asyncio.run(main())
