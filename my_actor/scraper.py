"""Core scraping and data extraction module for restaurants and food ordering apps."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

APP_DOMAINS = {
    "DoorDash": ["doordash.com"],
    "Grubhub": ["grubhub.com"],
    "Uber Eats": ["ubereats.com"],
    "Seamless": ["seamless.com"],
    "Postmates": ["postmates.com"],
    "Swiggy": ["swiggy.com"],
    "Zomato": ["zomato.com"],
    "Deliveroo": ["deliveroo.co.uk", "deliveroo.fr", "deliveroo.com"],
    "Just Eat": ["just-eat.co.uk", "just-eat.fr", "just-eat.com", "justeat.it", "justeat.es"],
}


async def geocode(
    location_str: str, client: httpx.AsyncClient
) -> Optional[Tuple[float, float, str, Optional[str]]]:
    """Geocode a text location or address to (latitude, longitude, display_name, country_code)."""
    # Check if input is already "lat, lng" coordinates
    coord_match = re.match(
        r"^\s*([-+]?\d{1,2}(?:\.\d+)?)\s*,\s*([-+]?\d{1,3}(?:\.\d+)?)\s*$",
        location_str,
    )
    if coord_match:
        lat = float(coord_match.group(1))
        lng = float(coord_match.group(2))
        return lat, lng, f"{lat}, {lng}", None

    # Use OpenStreetMap Nominatim geocoding service
    url = (
        f"https://nominatim.openstreetmap.org/search?"
        f"q={urllib.parse.quote(location_str)}&format=json&addressdetails=1&limit=1"
    )
    geo_headers = {
        "User-Agent": "NearestRestaurantsFoodAppsScraper/1.0 (info@apify.com)"
    }
    try:
        resp = await client.get(url, headers=geo_headers, timeout=12.0)
        if resp.status_code == 200 and resp.json():
            item = resp.json()[0]
            lat = float(item["lat"])
            lon = float(item["lon"])
            display_name = item.get("display_name", location_str)
            country_code = item.get("address", {}).get("country_code", "").upper()
            return lat, lon, display_name, country_code
    except Exception:
        pass

    return None


async def fetch_ubereats_store_details(
    client: httpx.AsyncClient,
    store_uuid: str,
    cookie_header: str,
    semaphore: asyncio.Semaphore,
) -> Dict[str, Any]:
    """Fetch extended store details (exact address, phone, cuisines, hours) from Uber Eats."""
    async with semaphore:
        headers = {
            **HEADERS,
            "x-csrf-token": "x",
            "content-type": "application/json",
            "cookie": cookie_header,
        }
        try:
            resp = await client.post(
                "https://www.ubereats.com/api/getStoreV1",
                json={"storeUuid": store_uuid},
                headers=headers,
                timeout=12.0,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                loc = data.get("location") or {}
                raw_cuisines = data.get("cuisineList") or []
                cuisines: List[str] = []
                for c in raw_cuisines:
                    if isinstance(c, str):
                        cuisines.append(c)
                    elif isinstance(c, dict) and c.get("name"):
                        cuisines.append(str(c["name"]))

                return {
                    "full_address": loc.get("address"),
                    "street_address": loc.get("streetAddress"),
                    "city": loc.get("city"),
                    "state_region": loc.get("region"),
                    "postal_code": loc.get("postalCode"),
                    "country": loc.get("country"),
                    "phone_number": data.get("phoneNumber"),
                    "cuisines": cuisines,
                    "is_open": data.get("isOpen"),
                    "price_bucket": data.get("priceBucket"),
                }
        except Exception:
            pass
        return {}


async def detect_supported_food_apps(
    client: httpx.AsyncClient,
    restaurant_name: str,
    city_or_address: str,
    primary_source: str,
    primary_url: str,
    semaphore: asyncio.Semaphore,
) -> Tuple[List[str], Dict[str, str]]:
    """Scan search engine for food ordering platforms supporting this restaurant."""
    supported_apps: Dict[str, bool] = {primary_source: True}
    ordering_links: Dict[str, str] = {primary_source: primary_url}

    if primary_source == "Uber Eats":
        # Postmates shares the Uber Eats merchant directory and logistics network
        supported_apps["Postmates"] = True

    async with semaphore:
        query = (
            f'"{restaurant_name}" "{city_or_address}" '
            f'doordash OR grubhub OR "uber eats" OR swiggy OR zomato OR deliveroo'
        )
        search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        ddg_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        }
        try:
            resp = await client.get(search_url, headers=ddg_headers, timeout=10.0)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.find_all("a", class_="result__snippet") + soup.find_all(
                    "a", class_="result__url"
                )
                for a in links:
                    href = a.get("href", "")
                    if "uddg=" in href:
                        try:
                            encoded_target = href.split("uddg=")[1].split("&")[0]
                            href = urllib.parse.unquote(encoded_target)
                        except Exception:
                            pass

                    href_lower = href.lower()
                    for app_name, domains in APP_DOMAINS.items():
                        if any(dom in href_lower for dom in domains):
                            supported_apps[app_name] = True
                            if app_name not in ordering_links and href.startswith(
                                "http"
                            ):
                                ordering_links[app_name] = href
        except Exception:
            pass

    return list(supported_apps.keys()), ordering_links


async def scrape_ubereats(
    lat: float,
    lng: float,
    location_label: str,
    search_query: str = "",
    only_open: bool = True,
    max_restaurants: int = 20,
    detect_apps: bool = True,
) -> List[Dict[str, Any]]:
    """Scrape nearest opened restaurants from Uber Eats API."""
    loc_payload = {
        "address": {"address1": location_label},
        "latitude": lat,
        "longitude": lng,
    }
    loc_cookie = urllib.parse.quote(json.dumps(loc_payload))
    cookie_header = f"uev2.loc={loc_cookie}"

    headers = {
        **HEADERS,
        "x-csrf-token": "x",
        "content-type": "application/json",
        "cookie": cookie_header,
    }

    feed_payload = {
        "feedType": "SEARCH" if search_query.strip() else "STORE",
        "userQuery": search_query.strip(),
    }

    results: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
        try:
            resp = await client.post(
                "https://www.ubereats.com/api/getFeedV1",
                json=feed_payload,
                timeout=15.0,
            )
            if resp.status_code != 200:
                return []
            data = resp.json().get("data", {})
        except Exception:
            return []

        # Extract stores across all item types (carousels, single stores, search mini-stores)
        raw_stores: List[Dict[str, Any]] = []
        seen_uuids = set()

        for item in data.get("feedItems", []):
            # 1. Carousel stores
            carousel = item.get("carousel", {})
            for s in carousel.get("stores", []):
                uuid = s.get("storeUuid")
                if uuid and uuid not in seen_uuids:
                    seen_uuids.add(uuid)
                    raw_stores.append(s)

            # 2. Direct store card
            if "store" in item:
                s = item["store"]
                uuid = s.get("storeUuid")
                if uuid and uuid not in seen_uuids:
                    seen_uuids.add(uuid)
                    raw_stores.append(s)

            # 3. Mini store with items (used in search results)
            mini_store = item.get("miniStoreWithItems", {}).get("store")
            if mini_store:
                uuid = mini_store.get("storeUuid")
                if uuid and uuid not in seen_uuids:
                    seen_uuids.add(uuid)
                    raw_stores.append(mini_store)

        # Filter stores
        candidates = []
        for s in raw_stores:
            store_payload = s.get("tracking", {}).get("storePayload", {})
            is_orderable = store_payload.get("isOrderable", False)
            avail_state = store_payload.get("storeAvailablityState", "")

            # Open check: accepting orders or orderable
            is_open = is_orderable or avail_state in ("OPEN", "ACCEPTING_ORDERS")
            if only_open and not is_open:
                continue

            candidates.append((s, is_open, avail_state))
            if len(candidates) >= max_restaurants:
                break

        # Semaphore for concurrent store detail and app detection calls
        detail_sem = asyncio.Semaphore(8)
        app_sem = asyncio.Semaphore(5)

        async def process_store(candidate_tuple):
            s, is_open, avail_state = candidate_tuple
            uuid = s.get("storeUuid", "")
            title = s.get("title", {}).get("text", "")
            action_url = s.get("actionUrl", "")
            full_url = f"https://www.ubereats.com{action_url}" if action_url else ""

            # Coordinates
            map_marker = s.get("mapMarker") or {}
            store_lat = map_marker.get("latitude", lat)
            store_lng = map_marker.get("longitude", lng)

            # Rating
            rating_text = s.get("rating", {}).get("text")
            try:
                rating_val = float(rating_text) if rating_text else None
            except ValueError:
                rating_val = None

            rating_count = (
                s.get("tracking", {})
                .get("storePayload", {})
                .get("ratingInfo", {})
                .get("ratingCount")
            )

            # Delivery time
            etd_text = ""
            for m in s.get("meta", []):
                if m.get("badgeType") == "ETD":
                    etd_text = m.get("text", "")
                    break

            # Fetch extended store details
            details = await fetch_ubereats_store_details(
                client, uuid, cookie_header, detail_sem
            )

            addr = details.get("full_address") or location_label
            city = details.get("city") or ""
            search_addr = f"{title} {addr}"

            # Detect supported food ordering platforms
            if detect_apps:
                supported_apps, ordering_links = await detect_supported_food_apps(
                    client, title, search_addr, "Uber Eats", full_url, app_sem
                )
            else:
                supported_apps = ["Uber Eats", "Postmates"]
                ordering_links = {"Uber Eats": full_url}

            status_str = (
                "Open now • Accepting orders"
                if is_open
                else (avail_state or "Currently closed")
            )

            return {
                "name": title,
                "is_open": is_open,
                "status_text": status_str,
                "supported_apps": supported_apps,
                "ordering_links": ordering_links,
                "address": addr,
                "street_address": details.get("street_address") or "",
                "city": city,
                "state_region": details.get("state_region") or "",
                "postal_code": details.get("postal_code") or "",
                "country": details.get("country") or "",
                "latitude": store_lat,
                "longitude": store_lng,
                "distance_or_delivery_time": etd_text,
                "rating": rating_val,
                "rating_count": rating_count or "",
                "cuisines": details.get("cuisines") or [],
                "price_range": details.get("price_bucket") or "",
                "phone_number": details.get("phone_number") or "",
                "primary_source": "Uber Eats",
                "primary_url": full_url,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }

        tasks = [process_store(c) for c in candidates]
        results = await asyncio.gather(*tasks)

    return list(results)


async def scrape_swiggy(
    lat: float,
    lng: float,
    location_label: str,
    search_query: str = "",
    only_open: bool = True,
    max_restaurants: int = 20,
    detect_apps: bool = True,
) -> List[Dict[str, Any]]:
    """Scrape nearest opened restaurants from Swiggy API (India)."""
    headers = {
        **HEADERS,
        "Referer": "https://www.swiggy.com/",
    }

    url = (
        f"https://www.swiggy.com/dapi/restaurants/list/v5?"
        f"lat={lat}&lng={lng}&is-seo-homepage-enabled=true&page_type=DESKTOP_WEB_LISTING"
    )

    results: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
        try:
            resp = await client.get(url, timeout=15.0)
            if resp.status_code != 200:
                return []
            data = resp.json().get("data", {})
        except Exception:
            return []

        raw_stores: List[Dict[str, Any]] = []
        for c in data.get("cards", []):
            card = c.get("card", {}).get("card", {})
            grid = card.get("gridElements", {}).get("infoWithStyle", {}).get("restaurants", [])
            for r_item in grid:
                info = r_item.get("info")
                if info and info.get("name"):
                    raw_stores.append(info)

        candidates = []
        for info in raw_stores:
            is_open = info.get("isOpen", True)
            if only_open and not is_open:
                continue
            if search_query:
                q = search_query.lower()
                name_match = q in info.get("name", "").lower()
                cuisines = [c.lower() for c in info.get("cuisines", [])]
                cuisine_match = any(q in c for c in cuisines)
                if not (name_match or cuisine_match):
                    continue

            candidates.append(info)
            if len(candidates) >= max_restaurants:
                break

        app_sem = asyncio.Semaphore(5)

        async def process_swiggy_store(info: Dict[str, Any]):
            name = info.get("name", "")
            locality = info.get("locality", "")
            area_name = info.get("areaName", "")
            city = info.get("city", "") or location_label
            address = f"{locality}, {area_name}, {city}".strip(", ")
            sla = info.get("sla", {})
            sla_str = sla.get("slaString", "")

            # Swiggy store URL
            swiggy_slug = info.get("slugString") or info.get("id")
            swiggy_url = (
                f"https://www.swiggy.com/restaurants/{swiggy_slug}"
                if swiggy_slug
                else "https://www.swiggy.com"
            )

            # Rating
            try:
                avg_rating = float(info.get("avgRating", 0))
            except (ValueError, TypeError):
                avg_rating = None

            # Detect supported apps
            if detect_apps:
                supported_apps, ordering_links = await detect_supported_food_apps(
                    client, name, address, "Swiggy", swiggy_url, app_sem
                )
            else:
                supported_apps = ["Swiggy"]
                ordering_links = {"Swiggy": swiggy_url}

            # Coordinates
            lat_long = info.get("latLong", "")
            store_lat, store_lng = lat, lng
            if lat_long and "," in lat_long:
                try:
                    parts = lat_long.split(",")
                    store_lat = float(parts[0])
                    store_lng = float(parts[1])
                except Exception:
                    pass

            return {
                "name": name,
                "is_open": info.get("isOpen", True),
                "status_text": (
                    "Open now • Accepting orders"
                    if info.get("isOpen", True)
                    else "Closed"
                ),
                "supported_apps": supported_apps,
                "ordering_links": ordering_links,
                "address": address,
                "street_address": locality,
                "city": city,
                "state_region": "",
                "postal_code": "",
                "country": "IN",
                "latitude": store_lat,
                "longitude": store_lng,
                "distance_or_delivery_time": sla_str,
                "rating": avg_rating,
                "rating_count": info.get("totalRatingsString", ""),
                "cuisines": info.get("cuisines") or [],
                "price_range": info.get("costForTwo", ""),
                "phone_number": "",
                "primary_source": "Swiggy",
                "primary_url": swiggy_url,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }

        tasks = [process_swiggy_store(info) for info in candidates]
        results = await asyncio.gather(*tasks)

    return list(results)
