# Adding New Tools — OpenMiniCrew Guide

> 🇹🇭 [อ่านเป็นภาษาไทย](../../TOOLS_GUIDE.md)

## Table of Contents

- [Overview](#overview)
- [Steps to Add a New Tool](#steps-to-add-a-new-tool)
- [Basic Template](#basic-template)
- [Example 1: Simple Tool — Weather](#example-1-simple-tool--weather)
- [Example 2: API Tool — Google Maps Traffic](#example-2-api-tool--google-maps-traffic)
- [Example 3: LLM Tool — News Summary](#example-3-llm-tool--news-summary)
- [Important Details](#important-details)
- [Pre-Deploy Checklist](#pre-deploy-checklist)
- [Tool Ideas](#tool-ideas)

---

## Overview

OpenMiniCrew's tool system is designed for easy extension:

```
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
    direct_output = True   # True = send result directly, False = let LLM summarize

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

            # === Log usage (mandatory) ===
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                input_summary=args[:100],
                output_summary=result[:200],
                status="success",
            )

            return result

        except Exception as e:
            log.error(f"MyTool failed for {user_id}: {e}")
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                input_summary=args[:100],
                status="failed",
                error_message=str(e),
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
            "name": "weather",
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
```
/weather bangkok
/weather tokyo
Or type: "What's the weather like today?"
```

---

## Example 2: API Tool — Google Maps Traffic

Check routes + real-time traffic via Google Maps Directions API.

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

```python
# tools/traffic.py
"""Traffic Tool — Check routes + traffic via Google Maps"""

import re
import requests
from tools.base import BaseTool
from core.config import GOOGLE_MAPS_API_KEY
from core.logger import get_logger

log = get_logger(__name__)


class TrafficTool(BaseTool):
    name = "traffic"
    description = "Check routes and traffic conditions between two locations via Google Maps"
    commands = ["/traffic"]

    async def execute(self, user_id: str, args: str = "") -> str:
        if not GOOGLE_MAPS_API_KEY:
            return "GOOGLE_MAPS_API_KEY not configured in .env"

        if not args:
            return (
                "Please specify origin and destination:\n"
                "/traffic Siam to Silom\n"
                "/traffic Home to Airport"
            )

        # Parse origin and destination
        separators = [" to ", " → ", " -> ", " ไป "]
        parts = None
        for sep in separators:
            if sep in args.lower() if sep == " to " else sep in args:
                parts = args.split(sep, 1) if sep == " to " else args.split(sep, 1)
                break

        if not parts or len(parts) < 2:
            return "Please use format: /traffic [origin] to [destination]"

        origin = parts[0].strip()
        destination = parts[1].strip()

        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/directions/json",
                params={
                    "origin": origin,
                    "destination": destination,
                    "mode": "driving",
                    "departure_time": "now",
                    "language": "en",
                    "key": GOOGLE_MAPS_API_KEY,
                },
                timeout=10,
            )
            data = resp.json()

            if data["status"] != "OK":
                return f"Could not find route: {data['status']}"

            route = data["routes"][0]
            leg = route["legs"][0]

            distance = leg["distance"]["text"]
            duration = leg["duration"]["text"]

            traffic_duration = leg.get("duration_in_traffic", {}).get("text", "")
            traffic_info = f"\n🚦 With traffic: {traffic_duration}" if traffic_duration else ""

            # Route summary (first 5 steps)
            steps_summary = []
            for i, step in enumerate(leg["steps"][:5], 1):
                instruction = re.sub(r"<[^>]+>", "", step["html_instructions"])
                step_dist = step["distance"]["text"]
                steps_summary.append(f"  {i}. {instruction} ({step_dist})")

            steps_text = "\n".join(steps_summary)
            if len(leg["steps"]) > 5:
                steps_text += f"\n  ... and {len(leg['steps']) - 5} more steps"

            return (
                f"🗺 From: {leg['start_address']}\n"
                f"➡️ To: {leg['end_address']}\n\n"
                f"📏 Distance: {distance}\n"
                f"⏱ Normal time: {duration}"
                f"{traffic_info}\n\n"
                f"📍 Route:\n{steps_text}"
            )

        except Exception as e:
            log.error(f"Traffic API error: {e}")
            return f"Error: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": "traffic",
            "description": (
                "Check route and traffic between two locations, e.g. "
                "'Siam to Silom', 'Home to Airport'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "Origin and destination separated by 'to', e.g. 'Siam to Silom'",
                    }
                },
                "required": ["args"],
            },
        }
```

**Usage:**
```
/traffic Siam to Silom
/traffic Home to Airport
Or type: "How long from Siam to Silom? Is there traffic?"
```

---

## Google Maps API Requirements & Alternatives

### 📋 Required Google Maps APIs

If you want to add Google Maps functionality, here are the APIs you need to enable:

#### For Routes & Traffic (like the example above)

- **Directions API** — Calculate routes between locations (supports driving, walking, biking, transit)
- **Distance Matrix API** — Calculate distance/time between multiple points
- **Geolocation API** — Get user's current location
- **Maps JavaScript API** (if showing maps on web) — Includes Traffic Layer for real-time traffic

#### For Places Search (cafes, restaurants, etc.)

- **Places API (New)** or **Places API** — Search for places nearby
  - Nearby Search — Find places around a location
  - Text Search — Search with text queries
  - Place Details — Get details (reviews, photos, phone, hours)
- **Geocoding API** — Convert addresses to coordinates or vice versa
- **Geolocation API** — Detect current location

### 💳 Billing Requirements

**Important:** Google Maps APIs require a **Billing Account** (credit card) to be enabled, even though they offer a generous free tier.

| Aspect          | Details                                                   |
|-----------------|-----------------------------------------------------------|
| **Billing Account** | **Required** — Must add credit card to Google Cloud  |
| **Free Tier**       | $200/month credit (enough for ~40,000 requests)      |
| **Personal Use**    | Won't exceed free tier for personal bots             |
| **Cost**            | No charges if you stay within free tier              |

**Comparison with Current Tools:**

- ✅ Gmail API — OAuth only, **no billing required**
- ✅ Google News RSS — **No API key needed**, completely free
- ❌ Google Maps APIs — **Billing account required** (but has free tier)

### 🆓 Free Alternatives (No Billing Required)

If you don't want to add a credit card, here are **completely free alternatives**:

#### For Routes & Traffic

| API                  | Free Tier             | Traffic Data                     | Notes                |
|----------------------|-----------------------|----------------------------------|----------------------|
| **OpenRouteService** | 2,500 requests/day    | Traffic patterns (not real-time) | No billing required  |
| **Mapbox Directions** | 100,000 requests/month | Traffic patterns                 | No credit card needed |
| **OSRM** (self-hosted) | Unlimited             | No traffic data                  | Requires hosting      |

#### For Places Search

| API                   | Free Tier            | Features                                | Notes                 |
|-----------------------|----------------------|-----------------------------------------|-----------------------|
| **Foursquare Places** | 100,000 requests/day | Rich POI data, wifi, power outlets      | **Best free option**  |
| **Overpass API**      | Unlimited            | OpenStreetMap data                      | Raw data, needs processing |
| **Mapbox Search**     | 100,000 requests/month | Good for addresses                    | Limited POI data      |

### 🤔 Which Should You Choose?

**Use Google Maps if:**

- ✅ You have a credit card and are okay with billing setup
- ✅ You want the most accurate data and best Thai language support
- ✅ You need real-time traffic data

**Use Free Alternatives if:**

- ✅ You don't want to add a credit card
- ✅ You're okay with slightly less accurate data
- ✅ You don't need real-time traffic (traffic patterns are enough)

**Recommended Free Combo:**

- **Foursquare** for places search (has `wifi`, `power_outlets` attributes!)
- **OpenRouteService** for routes/directions (good accuracy, traffic patterns)

---

## Example 2.1: Places Search Tool — Using Foursquare (Free)

Search for nearby places without billing requirements using Foursquare Places API.

### Step 1: Get Free API Key

1. Go to [Foursquare Developers](https://foursquare.com/developers/signup)
2. Create a free account
3. Create a new project
4. Copy your API Key

### Step 2: Configure

```bash
# Add to .env
FOURSQUARE_API_KEY=fsq3xxx
```

```python
# Add to core/config.py
FOURSQUARE_API_KEY = _optional("FOURSQUARE_API_KEY", "")
```

### Step 3: Create the Tool

```python
# tools/places.py
"""Places Search Tool — Find nearby places using Foursquare API"""

import requests
from tools.base import BaseTool
from core.config import FOURSQUARE_API_KEY
from core.logger import get_logger

log = get_logger(__name__)


class PlacesTool(BaseTool):
    name = "places"
    description = (
        "Search for nearby places like cafes, restaurants, shops. "
        "Can filter by features like wifi, power outlets, etc."
    )
    commands = ["/places", "/nearby"]

    async def execute(self, user_id: str, args: str = "") -> str:
        if not FOURSQUARE_API_KEY:
            return "FOURSQUARE_API_KEY not configured in .env"

        if not args:
            return (
                "Please specify what you're looking for:\n"
                "/places cafe with wifi near Siam\n"
                "/places restaurants near me\n"
                "/places coworking spaces with power outlets"
            )

        try:
            # Use Foursquare Places API
            headers = {
                "Accept": "application/json",
                "Authorization": FOURSQUARE_API_KEY,
            }

            params = {
                "query": args,
                "limit": 10,
            }

            # If user says "near me", you could add user's location here
            # For now, default to a common location (e.g., Bangkok city center)
            # In production, you'd get user's location via Geolocation API

            resp = requests.get(
                "https://api.foursquare.com/v3/places/search",
                headers=headers,
                params=params,
                timeout=10,
            )
            data = resp.json()

            results = data.get("results", [])
            if not results:
                return f"No places found for: {args}"

            # Format results
            output = f"📍 Found {len(results)} places:\n\n"

            for i, place in enumerate(results[:5], 1):  # Show top 5
                name = place.get("name", "Unknown")
                location = place.get("location", {})
                address = location.get("formatted_address", "Address not available")
                distance = place.get("distance", 0)

                # Categories
                categories = place.get("categories", [])
                category_names = [cat.get("name") for cat in categories[:2]]
                category_str = ", ".join(category_names) if category_names else "N/A"

                output += f"{i}. **{name}**\n"
                output += f"   📂 {category_str}\n"
                output += f"   📍 {address}\n"
                output += f"   📏 {distance}m away\n\n"

            if len(results) > 5:
                output += f"... and {len(results) - 5} more\n"

            return output

        except Exception as e:
            log.error(f"Places API error: {e}")
            return f"Error: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": "places",
            "description": (
                "Search for nearby places, e.g. 'cafe with wifi near Siam', "
                "'restaurants with outdoor seating', 'coworking spaces near me'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "Search query describing what to find, e.g. "
                            "'cafe with power outlets near Siam', 'restaurants near Central World'"
                        ),
                    }
                },
                "required": ["args"],
            },
        }
```

**Usage:**
```
/places cafe with wifi near Siam
/places restaurants with outdoor seating
/places coworking spaces near me
Or type: "Find cafes with power outlets near here"
```

**Features of Foursquare:**

- ✅ 100,000 free requests/day
- ✅ Rich place data (photos, ratings, hours, phone)
- ✅ Attributes like `wifi`, `outdoor_seating`, `delivery`
- ✅ No billing account required
- ✅ Good international coverage

---

## Example 3: LLM Tool — News Summary

Fetch news from RSS feeds and let LLM summarize.

```python
# tools/news_summary.py
"""News Summary Tool — Summarize latest news from RSS feeds"""

import feedparser
from tools.base import BaseTool
from core.config import DEFAULT_LLM
from core.llm import llm_router
from core.logger import get_logger

log = get_logger(__name__)

FEEDS = {
    "tech": {
        "label": "Technology",
        "url": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    },
    "world": {
        "label": "World News",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
    },
}


class NewsSummaryTool(BaseTool):
    name = "news_summary"
    description = "Summarize latest news from various sources"
    commands = ["/news"]

    async def execute(self, user_id: str, args: str = "") -> str:
        category = args.strip().lower() if args else "tech"

        feed_info = FEEDS.get(category)
        if not feed_info:
            categories = ", ".join(f"{k} ({v['label']})" for k, v in FEEDS.items())
            return f"Available categories: {categories}"

        try:
            # 1. Fetch news from RSS
            feed = feedparser.parse(feed_info["url"])
            entries = feed.entries[:10]

            if not entries:
                return f"No recent {feed_info['label']} news found"

            # 2. Prepare data for LLM
            news_text = ""
            for i, entry in enumerate(entries, 1):
                title = entry.get("title", "")
                summary = entry.get("summary", "")[:300]
                news_text += f"\n--- Article #{i} ---\n"
                news_text += f"Title: {title}\n"
                news_text += f"Content: {summary}\n"

            # 3. Let LLM summarize
            system = (
                "You are a news summarizer. Be concise and clear. "
                "Group related articles. Highlight key points. "
                "Use emoji for readability."
            )
            resp = await llm_router.chat(
                messages=[{"role": "user", "content": f"Summarize these {feed_info['label']} articles:\n{news_text}"}],
                provider=DEFAULT_LLM,
                tier="cheap",
                system=system,
            )

            return f"📰 Latest {feed_info['label']}:\n\n{resp['content']}"

        except Exception as e:
            log.error(f"News fetch error: {e}")
            return f"Failed to fetch news: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": "news_summary",
            "description": "Summarize latest news, choose category: tech, world",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "News category: tech (Technology), world (World News)",
                    }
                },
                "required": [],
            },
        }
```

**Usage:**
```
/news tech
/news world
Or type: "What's the latest tech news?"
```

---

## Important Details

### 1. `execute()` Input/Output

```
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

```
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
Result is sent back to LLM for natural language summary
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
from core.config import DEFAULT_LLM
resp = await llm_router.chat(messages=[...], provider=DEFAULT_LLM, tier="cheap")

# Config
from core.config import SOME_CONFIG

# Security (Gmail)
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
|---|---|---|
| `True` (default) | tool formats output nicely on its own | lotto, traffic, news |
| `False` | you want LLM to summarize raw data | email_summary |

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
- [ ] `db.log_tool_usage()` for both success and failed
- [ ] `direct_output` set appropriately (see `direct_output` section above)

### Recommended (skipping = works but not great)

- [ ] `get_tool_spec()` has a clear description (LLM uses it to decide)
- [ ] If using enum parameter → use `"enum": [...]` in properties
- [ ] If using an API key → added to `.env`, `.env.example`, `core/config.py`
- [ ] If using a new library → added to `requirements.txt`
- [ ] Tested via direct `/command`
- [ ] Tested via free text (LLM selects correct tool)
- [ ] Updated README.md (commands table)
- [ ] Output fits within Telegram limit (~4096 chars)

---

## Tool Ideas

| Tool | Command | API | Difficulty |
|---|---|---|---|
| Weather Forecast | `/weather` | Open-Meteo (free) | Easy |
| Translation | `/translate` | Use LLM (no extra API) | Easy |
| News Summary | `/news` | RSS + LLM | **Done ✅** |
| Route / Traffic | `/traffic` | Google Maps Directions API | **Done ✅** |
| Place Search | `/places` | Foursquare / Google Places | **Done ✅** |
| Gmail Summary | `/email` | Gmail API + LLM | **Done ✅** |
| Work Email (IMAP) | `/wm` | IMAP + pdfplumber/docx/openpyxl | **Done ✅** |
| Thai Lottery Check | `/lotto` | lotto.api.rayriffy.com | **Done ✅** |
| Notes / Reminders | `/note` | SQLite (already available) | Easy |
| Web Search | `/search` | Google Custom Search / SerpAPI | Medium |
| Exchange Rates | `/fx` | exchangerate-api (free) | Easy |
| Package Tracking | `/track` | Carrier APIs | Medium |
| Google Calendar | `/cal` | Google Calendar API | Hard |
| YouTube Summary | `/yt` | YouTube Transcript API + LLM | Medium |

---

## Tips

1. **Description matters a lot** — LLM uses the description to decide which tool to call when users type free text. If the description is unclear, LLM will pick the wrong tool.

2. **Use LLM as a formatter** — Let your tool fetch raw data, then pass it to LLM for natural language summarization. The results will be much better than manual formatting (see email_summary for this pattern).

3. **Multiple commands are supported** — `commands = ["/weather", "/w"]` lets users type shorter commands.

4. **Test /command first** — Test via direct `/command` before free text, since it bypasses LLM and shows raw output for easier debugging.

5. **Always keep API keys in .env** — Never hardcode them in tool files.
