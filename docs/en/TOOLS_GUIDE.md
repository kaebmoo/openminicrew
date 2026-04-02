# Adding New Tools — OpenMiniCrew Guide

> 🇹🇭 [อ่านเป็นภาษาไทย](../../TOOLS_GUIDE.md)

## Table of Contents

- [Overview](#overview)
- [Steps to Add a New Tool](#steps-to-add-a-new-tool)
- [Basic Template](#basic-template)
- [Example 1: Simple Tool — Weather](#example-1-simple-tool--weather)
- [Example 2: API Tool — Google Maps Traffic](#example-2-api-tool--google-maps-traffic)
- [Example 3: Places Search Tool — Google Places](#example-3-places-search-tool--google-places)
- [Example 4: LLM Tool — News Summary](#example-4-llm-tool--news-summary)
- [Example 5: Advanced LLM Tool (Using Mid-Tier Model)](#example-5-advanced-llm-tool-using-mid-tier-model)
- [Important Details](#important-details)
- [Pre-Deploy Checklist](#pre-deploy-checklist)
- [Current Tools Reference](#current-tools-reference)
- [Tool Ideas](#tool-ideas)

---

## Overview

OpenMiniCrew's tool system is designed for easy extension:

```text
Create a new .py file in tools/
         │
         ▼
Registry auto-discovers → registers automatically
         │
         ▼
Immediately available in 2 ways:
  1. /command → calls tool directly (zero LLM token cost)
  2. Free text → LLM selects tool via function calling
```

**No core files need to be modified** — just create a single file in `tools/`.

---

## Steps to Add a New Tool

### Step 1: Create a file in `tools/`

```bash
touch tools/my_tool.py
```

> ⚠️ Filename must not conflict with `base.py`, `registry.py`, or `__init__.py`

### Step 2: Write a class that inherits `BaseTool`

```python
from tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"           # tool name (must be unique)
    description = "Description" # LLM uses this to decide when to call the tool
    commands = ["/mytool"]     # direct command (zero token cost)
    direct_output = True       # True = send result directly, False = let LLM summarize
    preferred_tier = "cheap"   # cheap = Haiku/Flash, mid = Sonnet/Pro

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        # main logic
        return "Result"
```

### Step 3: (Optional) Add dependencies

```bash
# If the tool needs a new library
pip install some-library
echo "some-library" >> requirements.txt
```

### Step 4: (Optional) Add new config to `.env`

```bash
# Add to .env
GOOGLE_MAPS_API_KEY=xxx

# Add to core/config.py
GOOGLE_MAPS_API_KEY = _optional("GOOGLE_MAPS_API_KEY", "")

# Also add to .env.example
```

### Step 5: Restart the bot

```bash
# Ctrl+C then restart
python main.py
# You'll see: Registered tool: my_tool (commands: ['/mytool'])
```

---

## Basic Template

```python
"""My Tool — Brief description"""

import requests          # if calling external API
from tools.base import BaseTool
from core import db
from core.logger import get_logger

log = get_logger(__name__)


class MyTool(BaseTool):
    name = "my_tool"
    description = "Description that LLM uses to decide when to call this tool"
    commands = ["/mytool"]
    direct_output = True       # True = send result directly, False = let LLM summarize
    preferred_tier = "cheap"   # cheap = Haiku/Flash, mid = Sonnet/Pro (used when tool calls LLM internally)

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        """
        Main function — called when user uses /command or LLM selects this tool.

        Parameters:
            user_id: Telegram chat ID of the user (string)
            args: text after the command, e.g. "/mytool hello" → args = "hello"
            **kwargs: extra parameters from LLM

        Returns:
            string to send back to user
        """
        if not args:
            return "Please specify... e.g. /mytool xxx"

        try:
            # === Main logic ===
            result = f"Result for: {args}"

            # === Log usage (recommended) ===
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="success",
                **db.make_log_field("input", args, kind="tool_command"),
                **db.make_log_field("output", result, kind="tool_result"),
            )

            return result

        except Exception as e:
            log.error(f"MyTool failed for {user_id}: {e}")
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                **db.make_log_field("input", args, kind="tool_command"),
                **db.make_error_fields(str(e)),
            )
            return f"Error: {e}"

    def get_tool_spec(self) -> dict:
        """
        Tell LLM what parameters this tool accepts.
        LLM Router auto-converts format to match provider (Claude/Gemini).
        """
        return {
            "name": self.name,               # ❗ always use self.name, never hardcode
            "description": "Description that LLM uses to decide",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "Describe what this parameter is",
                    }
                },
                "required": [],
            },
        }
```

Structured logging notes:

- prefer `db.make_log_field(...)` for input and output metadata instead of raw `input_summary` and `output_summary`
- prefer `db.make_error_fields(...)` so failures store redacted error metadata instead of raw exception text
- choose stable `kind` values such as `tool_command`, `tool_result`, `search_query`, or `media_image` so logs stay analyzable after minimization

---

## Example 1: Simple Tool — Weather

Uses Open-Meteo API (free, no API key required).

```python
# tools/weather.py
"""Weather Tool — Today's weather forecast"""

import requests
from tools.base import BaseTool
from core.logger import get_logger

log = get_logger(__name__)

CITIES = {
    "bangkok": (13.75, 100.50),
    "chiang mai": (18.79, 98.98),
    "phuket": (7.88, 98.39),
    "london": (51.51, -0.13),
    "tokyo": (35.68, 139.69),
}


class WeatherTool(BaseTool):
    name = "weather"
    description = "Get today's weather forecast for a given city"
    commands = ["/weather"]

    async def execute(self, user_id: str, args: str = "") -> str:
        city = args.strip().lower() if args else "bangkok"

        coords = CITIES.get(city)
        if not coords:
            # Try partial match
            for name, c in CITIES.items():
                if city in name:
                    coords = c
                    city = name
                    break

        if not coords:
            cities_list = ", ".join(CITIES.keys())
            return f"Unknown city '{args}'\nSupported: {cities_list}"

        lat, lon = coords

        try:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
                    "timezone": "auto",
                },
                timeout=10,
            )
            data = resp.json().get("current", {})

            temp = data.get("temperature_2m", "?")
            humidity = data.get("relative_humidity_2m", "?")
            wind = data.get("wind_speed_10m", "?")

            return (
                f"🌤 Weather in {city.title()}:\n"
                f"🌡 Temperature: {temp}°C\n"
                f"💧 Humidity: {humidity}%\n"
                f"💨 Wind: {wind} km/h"
            )

        except Exception as e:
            log.error(f"Weather API error: {e}")
            return f"Failed to fetch weather: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "Get today's weather forecast for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "City name, e.g. Bangkok, London, Tokyo",
                    }
                },
                "required": [],
            },
        }
```

**Usage:**

```text
/weather bangkok
/weather tokyo
Or type: "What's the weather like today?"
```

---

## Example 2: API Tool — Google Maps Traffic

Check routes + real-time traffic + travel time via Google Maps Directions API and Routes API.

### Step 1: Configure

```bash
# Add to .env
GOOGLE_MAPS_API_KEY=AIzaSyXxx
```

```python
# Add to core/config.py
GOOGLE_MAPS_API_KEY = _optional("GOOGLE_MAPS_API_KEY", "")
```

### Step 2: Create the Tool

> This example is simplified from the actual `tools/traffic.py` to show the key structure.

```python
# tools/traffic.py
"""Traffic Tool — Check routes, traffic conditions, and travel time via Google Maps"""

import re
import urllib.parse

import requests

from tools.base import BaseTool
from core.config import GOOGLE_MAPS_API_KEY
from core import db
from core.logger import get_logger

log = get_logger(__name__)

# Separators for splitting origin and destination
SEPARATORS = [" ไป ", " to ", "→", "➡", " ถึง ", "|"]

# Regex patterns for detecting travel mode from Thai text
_MODE_FALLBACK = [
    (re.compile(r"มอเตอร์ไซค์|มอไซค์|motorcycle|motorbike", re.IGNORECASE), "two_wheeler"),
    (re.compile(r"เดินเท้า|เดิน(?!ทาง)|walking|on\s+foot", re.IGNORECASE), "walking"),
    (re.compile(r"รถโดยสาร|ขนส่งสาธารณะ|รถเมล์|รถไฟฟ้า|transit|bus|bts|mrt", re.IGNORECASE), "transit"),
]


class TrafficTool(BaseTool):
    name = "traffic"
    description = "Check routes, traffic conditions, and travel time between two locations via Google Maps"
    commands = ["/traffic", "/route"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "", mode: str = "driving", **kwargs) -> str:
        if not GOOGLE_MAPS_API_KEY:
            return "GOOGLE_MAPS_API_KEY not configured in .env"

        if not args:
            return (
                "Please specify origin and destination:\n"
                "/traffic Siam to Silom\n"
                "/traffic Home to Airport walking\n"
                "/traffic Siam to Asok motorcycle"
            )

        # Split origin and destination (supports multiple separators)
        origin, destination = None, None
        for sep in SEPARATORS:
            if sep in args:
                parts = args.split(sep, 1)
                origin, destination = parts[0].strip(), parts[1].strip()
                break

        if not origin or not destination:
            return "Please use format: /traffic [origin] to [destination]"

        # Detect mode from text (e.g. "motorcycle", "walking")
        for pattern, detected_mode in _MODE_FALLBACK:
            if pattern.search(args):
                mode = detected_mode
                break

        try:
            # Call appropriate API based on mode
            if mode == "two_wheeler":
                # Use Routes API (New) for motorcycle
                result = self._call_routes_api(origin, destination)
            else:
                # Use Directions API for driving/walking/transit
                result = self._call_directions_api(origin, destination, mode)

            db.log_tool_usage(user_id, self.name, args[:100], result[:200], "success")
            return result

        except Exception as e:
            log.error(f"Traffic API error: {e}")
            db.log_tool_usage(user_id, self.name, args[:100], status="failed", error_message=str(e))
            return f"Error: {e}"

    def _call_directions_api(self, origin, destination, mode):
        """Call Google Maps Directions API"""
        params = {
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "departure_time": "now",
            "alternatives": "true",
            "language": "th",
            "region": "th",
            "key": GOOGLE_MAPS_API_KEY,
        }
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/directions/json",
            params=params, timeout=15,
        )
        data = resp.json()
        if data["status"] != "OK":
            return f"Could not find route: {data['status']}"

        # Format result (route, distance, duration, traffic, Google Maps link)
        # ... (abbreviated — see full source in tools/traffic.py)
        route = data["routes"][0]
        leg = route["legs"][0]
        return f"🗺 {leg['start_address']} → {leg['end_address']}\n📏 {leg['distance']['text']} ⏱ {leg['duration']['text']}"

    def _call_routes_api(self, origin, destination):
        """Call Routes API (New) for two_wheeler mode"""
        # POST https://routes.googleapis.com/directions/v2:computeRoutes
        # ... (abbreviated — see full source in tools/traffic.py)
        return "🏍 Motorcycle route..."

    def get_tool_spec(self) -> dict:
        return {
            "name": "traffic",
            "description": (
                "Check route, distance, travel time, and real-time traffic "
                "between two locations via Google Maps"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "Origin and destination separated by 'to' or 'ไป', e.g. "
                            "'Siam to Silom', 'Central World ไป Suvarnabhumi'"
                        ),
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["driving", "walking", "transit", "two_wheeler"],
                        "description": (
                            "Travel mode: driving=car, walking=on foot, "
                            "transit=public transport, two_wheeler=motorcycle"
                        ),
                    },
                },
                "required": ["args"],
            },
        }
```

**Key features of the actual Traffic Tool:**

- **Travel modes**: driving, walking, transit, motorcycle (two_wheeler)
- **Toll avoidance**: detects "avoid tolls" or specific toll road names
- **GPS location**: detects "near me/here" keywords and uses user's GPS
- **Alternative routes**: shows up to 3 route options
- **Google Maps URL**: clickable link to open in Maps app
- Uses **Directions API** (driving/walking/transit) + **Routes API New** (two_wheeler)

**Usage:**

```text
/traffic Siam to Silom
/traffic Siam to Asok motorcycle
/traffic Siam to Silom walking
/route Home to Airport
Or type: "How long from Siam to Silom? Is there traffic?"
```

---

## Google Maps API Requirements & Alternatives

### 📋 Google Maps APIs Used in This Project

The current project uses these APIs (must be enabled in Google Cloud Console):

- **Directions API** — Calculate routes (driving, walking, transit)
- **Routes API** — Motorcycle routes (two_wheeler)
- **Places API (New)** — Search for places (Text Search)
- **Geocoding API** — Convert place names to coordinates

#### For Additional Features

- **Distance Matrix API** — Calculate distance/time between multiple points
- **Geolocation API** — Get user's current location
- **Maps JavaScript API** (if showing maps on web) — Includes Traffic Layer for real-time traffic

### 💳 Billing Requirements

**Important:** Google Maps APIs require a **Billing Account** (credit card) to be enabled, even though they offer a generous free tier.

| Aspect | Details |
| --- | --- |
| **Billing Account** | **Required** — Must add credit card to Google Cloud |
| **Free Tier** | $200/month credit (enough for ~40,000 requests) |
| **Personal Use** | Won't exceed free tier for personal bots |
| **Cost** | No charges if you stay within free tier |

**Comparison with Current Tools:**

- ✅ Gmail API — OAuth only, **no billing required**
- ✅ Google News RSS — **No API key needed**, completely free
- ✅ Bank of Thailand API — **No billing required**, uses free token
- ✅ Rayriffy Lotto API — **No API key needed**, completely free
- ❌ Google Maps/Places APIs — **Billing account required** (but has free tier)

### 🆓 Free Alternatives (No Billing Required)

If you don't want to add a credit card, here are **completely free alternatives**:

#### For Routes & Traffic

| API | Free Tier | Traffic Data | Notes |
| --- | --- | --- | --- |
| **OpenRouteService** | 2,500 requests/day | Traffic patterns (not real-time) | No billing required |
| **Mapbox Directions** | 100,000 requests/month | Traffic patterns | No credit card needed |
| **OSRM** (self-hosted) | Unlimited | No traffic data | Requires hosting |

#### For Places Search

| API | Free Tier | Features | Notes |
| --- | --- | --- | --- |
| **Foursquare Places** | 100,000 requests/day | Rich POI data, wifi, power outlets | Good free option |
| **Overpass API** | Unlimited | OpenStreetMap data | Raw data, needs processing |
| **Mapbox Search** | 100,000 requests/month | Good for addresses | Limited POI data |

---

## Example 3: Places Search Tool — Google Places

Search for nearby places using Google Places API (New) — Text Search endpoint.

> This example is simplified from the actual `tools/places.py`.

```python
# tools/places.py
"""Places Tool — Search for nearby places via Google Places API (New)"""

import re

import requests

from tools.base import BaseTool
from core.config import GOOGLE_MAPS_API_KEY
from core import db
from core.logger import get_logger

log = get_logger(__name__)

# Price level mapping from Places API (New)
PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": "Free",
    "PRICE_LEVEL_INEXPENSIVE": "💰 Inexpensive",
    "PRICE_LEVEL_MODERATE": "💰💰 Moderate",
    "PRICE_LEVEL_EXPENSIVE": "💰💰💰 Expensive",
    "PRICE_LEVEL_VERY_EXPENSIVE": "💰💰💰💰 Very Expensive",
}


class PlacesTool(BaseTool):
    name = "places"
    description = "Search for nearby places like cafes, restaurants, hospitals, convenience stores"
    commands = ["/places", "/nearby", "/search"]
    direct_output = True

    # Keywords indicating user means "near me" (requires GPS)
    _NEARBY_KEYWORDS = re.compile(r"(แถวนี้|ใกล้นี้|ตรงนี้|nearby|near me)")
    _OPEN_NOW_KEYWORDS = re.compile(r"(เปิดอยู่|เปิดตอนนี้|open now|ยังเปิด|เปิดไหม)")
    _BANGKOK_CENTER = {"latitude": 13.7563, "longitude": 100.5018}

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        if not GOOGLE_MAPS_API_KEY:
            return "GOOGLE_MAPS_API_KEY not configured in .env"

        if not args:
            return (
                "Please specify what you're looking for:\n"
                "/places cafe near Siam\n"
                "/places restaurant open now nearby"
            )

        try:
            # Detect "open now" → filter
            open_now = bool(self._OPEN_NOW_KEYWORDS.search(args))

            # Build location bias (circle around user or Bangkok center)
            location_bias = {
                "circle": {
                    "center": self._BANGKOK_CENTER,
                    "radius": 30000.0,  # 30km
                }
            }

            # Call Google Places API (New) — Text Search
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": (
                    "places.displayName,places.formattedAddress,places.rating,"
                    "places.userRatingCount,places.currentOpeningHours,"
                    "places.priceLevel,places.googleMapsUri"
                ),
            }

            body = {
                "textQuery": args,
                "languageCode": "th",
                "locationBias": location_bias,
                "maxResultCount": 10,
            }
            if open_now:
                body["openNow"] = True

            resp = requests.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers=headers,
                json=body,
                timeout=10,
            )
            data = resp.json()
            results = data.get("places", [])

            if not results:
                return f"No places found for: {args}"

            # Format results
            output = f"📍 Found {len(results)} places:\n\n"
            for i, place in enumerate(results[:5], 1):
                name = place.get("displayName", {}).get("text", "Unknown")
                address = place.get("formattedAddress", "")
                rating = place.get("rating")
                stars = "⭐" * int(rating) if rating else ""
                maps_url = place.get("googleMapsUri", "")

                output += f"{i}. {name} {stars}\n"
                output += f"   📍 {address}\n"
                if maps_url:
                    output += f"   🔗 {maps_url}\n"
                output += "\n"

            db.log_tool_usage(user_id, self.name, args[:100], status="success")
            return output

        except Exception as e:
            log.error(f"Places API error: {e}")
            db.log_tool_usage(user_id, self.name, args[:100], status="failed", error_message=str(e))
            return f"Error: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": "places",
            "description": (
                "Search for nearby places, e.g. 'cafe near Siam', "
                "'restaurant near Sukhumvit', 'hospital near Ladprao'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "Search query with location, e.g. "
                            "'cafe near Siam', 'restaurant near Sukhumvit'"
                        ),
                    }
                },
                "required": ["args"],
            },
        }
```

**Key features of the actual Places Tool:**

- Uses **Google Places API (New)** — Text Search endpoint
- **Location Bias**: uses user's GPS (if available) or falls back to Bangkok 30km radius
- **Open Now Filter**: detects "open now" / "เปิดอยู่" keywords and filters accordingly
- Displays: name, star rating, address, open/closed status, price level, phone, website, Google Maps link

**Usage:**

```text
/places cafe near Siam
/places restaurant open now nearby
/search ATM near MBK
/nearby hospital near Ladprao
Or type: "Find cafes with power outlets near here"
```

---

## Example 4: LLM Tool — News Summary

Fetch news from Google News RSS and let LLM summarize.

> This example is simplified from the actual `tools/news_summary.py`.

```python
# tools/news_summary.py
"""News Summary Tool — Fetch news from Google News RSS + summarize with LLM"""

import urllib.parse
import xml.etree.ElementTree as ET

import requests

from tools.base import BaseTool
from core.llm import llm_router
from core.user_manager import get_user, get_preference
from core.logger import get_logger

log = get_logger(__name__)


class NewsSummaryTool(BaseTool):
    name = "news_summary"
    description = "Summarize today's top news or search for news by topic from Google News"
    commands = ["/news"]
    # direct_output = True (default) — tool summarizes with LLM internally, sends result directly

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "Search and summarize latest news from Google News by keyword or general headlines",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "News topic to search for, e.g. 'technology', 'politics', 'stocks', or leave empty for top news",
                    }
                },
            },
        }

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        topic = (args or "").strip()

        # 1. Choose RSS URL based on search query
        if topic:
            query = urllib.parse.quote(topic)
            rss_url = f"https://news.google.com/rss/search?q={query}&hl=th&gl=TH&ceid=TH:th"
            display_label = f"Topic: {topic}"
        else:
            rss_url = "https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th"
            display_label = "Top headlines"

        # 2. Fetch RSS data
        try:
            resp = requests.get(rss_url, timeout=10)
            resp.raise_for_status()

            root = ET.fromstring(resp.content)
            items = root.findall("./channel/item")

            if not items:
                return f"No news found for {display_label}"

            # 3. Extract top 10 headlines + strip source name
            max_news = 10
            headlines = []
            references = []

            for i, item in enumerate(items[:max_news], 1):
                title = item.findtext("title")
                link = item.findtext("link")

                if title and " - " in title:
                    clean_title = title.rsplit(" - ", 1)[0]
                    source = title.rsplit(" - ", 1)[1].strip()
                else:
                    clean_title = title or ""
                    source = "Read more"

                headlines.append(f"[{i}] {clean_title}")
                references.append(f"{i}. [{source}]({link})")

            headlines_text = "\n".join(headlines)

        except Exception as e:
            log.error(f"Failed to fetch Google News: {e}")
            return "❌ Failed to fetch news. Please try again."

        # 4. Summarize with LLM (send only headlines, not URLs)
        user = get_user(user_id) or {}
        provider = get_preference(user, "default_llm")

        system_prompt = (
            "You are a smart news anchor. Tone: concise, friendly, easy to understand.\n"
            "1. Group related news together\n"
            "2. Summarize key points concisely\n"
            "3. Add reference numbers [1] [2] at the end of each story\n"
            "4. Do not add URLs — the system appends them automatically"
        )

        chat_resp = await llm_router.chat(
            messages=[{"role": "user", "content": f"Summarize these news ({display_label}):\n{headlines_text}"}],
            provider=provider,
            tier=self.preferred_tier,
            system=system_prompt,
        )

        # 5. Combine: summary + clickable reference links
        summary = chat_resp.get("content", "")
        refs_text = "\n".join(references)

        return f"📰 News Summary: {display_label}\n\n{summary}\n\n🔗 References:\n{refs_text}"
```

**Key points:**

- Uses **Google News RSS** (free, no API key required)
- **Keyword search** supported (not category-based)
- Tool calls **LLM internally** to summarize → uses `direct_output = True` (default) so dispatcher doesn't re-summarize
- Uses `self.preferred_tier` instead of hardcoding `tier="cheap"`

**Usage:**

```text
/news
/news technology
/news politics
/news stocks
Or type: "What's the latest tech news?"
```

---

## Example 5: Advanced LLM Tool (Using Mid-Tier Model)

Sometimes you may build a complex tool (deep data analysis, long document summarization, code generation) where the default cheap model might struggle.

**Method 1: Set `preferred_tier` at class level** (recommended — all LLM calls in the tool use the same tier)

```python
class MySmartTool(BaseTool):
    preferred_tier = "mid"  # ← all llm_router.chat() calls using self.preferred_tier get Sonnet/Pro

    async def execute(self, ...):
        resp = await llm_router.chat(..., tier=self.preferred_tier, ...)
```

**Method 2: Specify `tier` per call** (for mixing tiers within the same tool)

```python
# First call: use cheap for simple tasks
resp1 = await llm_router.chat(..., tier="cheap", ...)

# Second call: use mid for complex analysis
resp2 = await llm_router.chat(..., tier="mid", ...)
```

**Full example:**

```python
# tools/research_tool.py
"""Research Tool — In-depth data analysis using an advanced LLM"""

from tools.base import BaseTool
from core.llm import llm_router
from core.user_manager import get_user, get_preference
from core.logger import get_logger

log = get_logger(__name__)

class ResearchSummaryTool(BaseTool):
    name = "research_summary"
    description = "Conducts deep and comprehensive analysis on a given topic"
    commands = ["/research"]
    direct_output = True
    preferred_tier = "mid"  # ← always use the advanced model

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        if not args:
            return "Please provide a topic: /research [topic]"

        try:
            user = get_user(user_id) or {}
            provider = get_preference(user, "default_llm")

            system_prompt = (
                "You are a Senior Data Analyst. "
                "Analyze data using rigorous logic. State impacts and recommendations."
            )

            resp = await llm_router.chat(
                messages=[{"role": "user", "content": f"Analyze this topic:\n{args}"}],
                provider=provider,
                tier=self.preferred_tier,  # ← uses "mid" from class attribute
                system=system_prompt,
            )

            return f"🔬 **Deep Analysis: {args}**\n\n{resp['content']}"

        except Exception as e:
            log.error(f"Research failed: {e}")
            return f"Analysis failed: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "Brainstorm and analyze deeply on difficult or complex topics",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "The particular topic for in-depth analysis",
                    }
                },
                "required": [],
            },
        }
```

**What happens here:**

1. The dispatcher routes the request to this tool (using the cheap model as usual).
2. Once inside the tool, it launches an internal chat session with the advanced (Mid) tier model.
3. The highly analytical result is returned to the user.
(With `direct_output=True`, the dispatcher skips re-summarizing with the cheap model, preserving 100% of the advanced model's output.)

**Tools using `preferred_tier = "mid"` currently:**

- `gmail_summary` — Gmail summarization needs deep comprehension
- `work_email` — IMAP + attachment summarization needs deep comprehension

---

## Important Details

### 1. `execute()` Input/Output

```text
Signature:
  async def execute(self, user_id: str, args: str = "", **kwargs) -> str

Input:
  user_id  → Telegram chat ID (string), e.g. "25340254"
  args     → Text after command, e.g. "/email force 7d" → args = "force 7d"
             Or string sent by LLM via function calling
  **kwargs → Extra parameters from LLM according to tool spec
             e.g. mode="walking", category="tech"
             Always include **kwargs — dispatcher passes the full dict via **tool_args

Output:
  return string → Message sent back to user via Telegram
```

### 2. How it Works with LLM (Function Calling)

```text
User types: "What's the weather like today?"
         │
         ▼
LLM sees all tool specs
         │
         ▼
LLM selects: weather tool (because description matches)
         │
         ▼
Dispatcher calls WeatherTool.execute(user_id, args)
         │
         ▼
If direct_output=True → send result directly to user
If direct_output=False → pass result to LLM for summarization
         │
         ▼
Sent to user via Telegram
```

> **Important:** The `description` in both the class and `get_tool_spec()` must be clear —
> LLM uses the description to decide which tool to call.

### 3. Available Core Modules

```python
# Database
from core import db
db.log_tool_usage(user_id, "my_tool", status="success")

# LLM
from core.llm import llm_router
resp = await llm_router.chat(messages=[...], provider=provider, tier="cheap")

# User preference (get user's LLM provider)
from core.user_manager import get_user, get_preference
user = get_user(user_id) or {}
provider = get_preference(user, "default_llm")

# Config
from core.config import SOME_CONFIG

# Gmail credentials
from core.security import get_gmail_credentials

# Logger
from core.logger import get_logger
log = get_logger(__name__)
```

### 4. Writing `get_tool_spec()`

The tool spec uses a **generic format** — LLM Router auto-converts to match the provider:

```python
def get_tool_spec(self) -> dict:
    return {
        "name": self.name,             # ❗ always use self.name, never hardcode
        "description": "Description",  # LLM uses this to decide — clearer is better
        "parameters": {
            "type": "object",
            "properties": {
                "args": {              # parameter name
                    "type": "string",  # type: string, integer, boolean
                    "description": "Describe what this parameter is",
                }
            },
            "required": [],            # list of required parameters
        },
    }
```

**Adding an enum parameter** — lets LLM select a value directly instead of parsing text:

```python
"properties": {
    "args": {
        "type": "string",
        "description": "Origin and destination separated by 'to'",
    },
    "mode": {
        "type": "string",
        "enum": ["driving", "walking", "transit", "two_wheeler"],
        "description": "Travel mode: driving=car, walking=on foot, transit=public transport, two_wheeler=motorcycle",
    },
},
```

LLM sends `mode="walking"` directly → `execute()` receives it via `**kwargs` or as a named param:

```python
async def execute(self, user_id: str, args: str = "", mode: str = "driving", **kwargs) -> str:
    # mode is extracted from kwargs automatically
    ...
```

**If tool has no parameters** — don't override `get_tool_spec()` (BaseTool has a default).

### 5. Error Handling

```python
async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
    try:
        result = do_something()
        return result

    except Exception as e:
        log.error(f"MyTool failed for {user_id}: {e}")

        # (optional) Log to DB
        db.log_tool_usage(
            user_id=user_id,
            tool_name=self.name,
            status="failed",
            error_message=str(e),
        )

        # Return user-friendly error message
        return f"Error: {e}"
```

> ⚠️ **Never let exceptions escape `execute()`** — the dispatcher will catch them,
> but the user will get an ugly error message. Always catch and return a friendly message.

### 6. `direct_output` — Direct vs LLM-summarized

```python
class MyTool(BaseTool):
    direct_output = True   # send result directly, no LLM re-summarization
    # direct_output = False  # pass result to LLM for natural language summary
```

| Value | Use when | Examples |
| --- | --- | --- |
| `True` (default) | tool formats output nicely, or tool summarizes with LLM internally | traffic, places, lotto, gmail_summary, news_summary |
| `False` | you want the dispatcher to pass raw data to LLM for summarization | (no current tools use this — but the framework supports it) |

> **Note:** Tools that call LLM internally (e.g. gmail_summary, news_summary)
> use `direct_output = True` because their output is already summarized — no need for the dispatcher to re-summarize.

### 7. `preferred_tier` — Choosing LLM Quality Level

```python
class MyTool(BaseTool):
    preferred_tier = "cheap"   # Haiku/Flash — fast, inexpensive (default)
    # preferred_tier = "mid"   # Sonnet/Pro — smarter, but slower and more expensive
```

| Tier | Models | Use when | Tools using it |
| --- | --- | --- | --- |
| `"cheap"` (default) | Haiku / Gemini Flash | General summarization, simple tasks | news_summary |
| `"mid"` | Sonnet / Gemini Pro | Tasks requiring deep comprehension | gmail_summary, work_email |

Use in `execute()` via `self.preferred_tier`:

```python
resp = await llm_router.chat(
    messages=[...],
    provider=provider,
    tier=self.preferred_tier,  # ← uses value from class attribute
    system=system_prompt,
)
```

### 8. Asyncio Safety in Tools

Tools are called from **two different contexts**:

1. **Webhook/polling** — runs inside FastAPI/uvicorn's asyncio event loop
2. **Scheduler** — `asyncio.run()` creates a new event loop inside a `BackgroundScheduler` thread pool thread

When the scheduler reuses a thread from its pool, a previous `asyncio.run()` call may have left a closed event loop reference on that thread. This causes `asyncio.get_event_loop()` to return the **closed** loop instead of the currently running one → `"Event loop is closed"` error.

**Rules:**

- **Never** use `asyncio.get_event_loop()` — always use `asyncio.get_running_loop()`
- Pure `await` calls (e.g. `await llm_router.chat()`) are safe — they use the running loop implicitly
- If you need to wrap sync/blocking code (IMAP, heavy file I/O), use:

```python
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(None, sync_function, arg1, arg2)
```

- **Never** create `asyncio.new_event_loop()` inside a tool
- Symptom of violation: intermittent errors **only** when scheduler runs the tool (manual `/command` works fine)

---

## Pre-Deploy Checklist

### Mandatory (missing any = bug)

- [ ] File is in the `tools/` directory
- [ ] Class inherits from `BaseTool`
- [ ] `name`, `description`, `commands` are all set
- [ ] `execute()` has signature: `async def execute(self, user_id: str, args: str = "", **kwargs) -> str`
- [ ] `execute()` always returns a string (never returns None)
- [ ] `execute()` wrapped in `try/except` — no unhandled exceptions
- [ ] `get_tool_spec()` uses `self.name` (**never hardcode** the tool name)
- [ ] `direct_output` set appropriately

### Recommended (skipping = works but not great)

- [ ] `db.log_tool_usage()` for both success and failed (dispatcher handles failed cases, but success must be logged by the tool)
- [ ] Set `preferred_tier` if tool calls LLM internally (`"mid"` for complex tasks)
- [ ] `get_tool_spec()` has a clear description (LLM uses it to decide)
- [ ] If using enum parameter → use `"enum": [...]` in properties
- [ ] If using an API key → added to `.env`, `.env.example`, `core/config.py`
- [ ] If using a new library → added to `requirements.txt`
- [ ] Tested via direct `/command`
- [ ] Tested via free text (LLM selects correct tool)
- [ ] Output fits within Telegram limit (~4096 chars)

---

## Current Tools Reference

| Tool | Commands | API/Source | preferred_tier | Required API Keys |
| --- | --- | --- | --- | --- |
| **gmail_summary** — Gmail summary | `/email` | Gmail API (OAuth2) + LLM | mid | `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` |
| **work_email** — Work email (IMAP) | `/wm`, `/workmail` | IMAP + LLM | mid | `WORK_IMAP_HOST`, `WORK_IMAP_PORT`, `WORK_IMAP_USER`, `WORK_IMAP_PASSWORD` |
| **traffic** — Routes/traffic | `/traffic`, `/route` | Google Maps Directions + Routes API | cheap | `GOOGLE_MAPS_API_KEY` |
| **places** — Place search | `/places`, `/nearby`, `/search` | Google Places API (New) | cheap | `GOOGLE_MAPS_API_KEY` |
| **exchange_rate** — Exchange rates | `/fx`, `/rate`, `/exchange` | Bank of Thailand API | cheap | `BOT_API_EXCHANGE_TOKEN`, `BOT_API_HOLIDAY_TOKEN` |
| **news_summary** — News summary | `/news` | Google News RSS + LLM | cheap | None (RSS is free) |
| **lotto** — Thai lottery results | `/lotto` | lotto.api.rayriffy.com | cheap | None (API is free) |
| **settings** — Personal settings + email accounts | `/setname`, `/setphone`, `/setid`, `/myemail` | SQLite + Gmail API (profile) | cheap | None |
| **apikeys** — API key management | `/setkey`, `/mykeys`, `/removekey` | SQLite (encrypted) | cheap | None |

> **Note:** All tools use `direct_output = True` (default) — tools that use LLM (gmail_summary, work_email, news_summary) handle summarization internally.

---

## Tool Ideas

| Tool | Command | API | Difficulty |
| --- | --- | --- | --- |
| Weather Forecast | `/weather` | Open-Meteo (free) | Easy |
| Translation | `/translate` | Use LLM (no extra API) | Easy |
| Notes / Reminders | `/note` | SQLite (already available) | Easy |
| Web Search | `/search` | Google Custom Search / SerpAPI | Medium |
| Package Tracking | `/track` | Thailand Post API / Kerry API | Medium |
| YouTube Summary | `/yt` | YouTube Transcript API + LLM | Medium |
| Google Calendar | `/cal` | Google Calendar API | Hard |

---

## Tips

1. **Description matters a lot** — LLM uses the description to decide which tool to call when users type free text. If the description is unclear, LLM will pick the wrong tool.

2. **Use LLM as a formatter** — Let your tool fetch raw data, then pass it to LLM for natural language summarization. The results will be much better than manual formatting (see gmail_summary, news_summary for this pattern).

3. **Multiple commands are supported** — `commands = ["/weather", "/w"]` lets users type shorter commands.

4. **Test /command first** — Test via direct `/command` before free text, since it bypasses LLM and shows raw output for easier debugging.

5. **Always keep API keys in .env** — Never hardcode them in tool files.

6. **Use `preferred_tier` instead of hardcoding** — Set `preferred_tier = "mid"` at class level instead of writing `tier="mid"` directly in code. This makes it easy to change later.
