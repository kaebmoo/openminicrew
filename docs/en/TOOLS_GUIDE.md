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

    async def execute(self, user_id: str, args: str = "") -> str:
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

from tools.base import BaseTool
from core.logger import get_logger

log = get_logger(__name__)


class MyTool(BaseTool):
    name = "my_tool"
    description = "Description that LLM uses to decide when to call this tool"
    commands = ["/mytool"]

    async def execute(self, user_id: str, args: str = "") -> str:
        """
        Main function — called when user uses /command or LLM selects this tool.

        Parameters:
            user_id: Telegram chat ID of the user (string)
            args: text after the command, e.g. "/mytool hello" → args = "hello"

        Returns:
            string to send back to user (or passed to LLM for summarization)
        """
        if not args:
            return "Please specify... e.g. /mytool xxx"

        try:
            # === Main logic ===
            result = f"Result for: {args}"
            return result

        except Exception as e:
            log.error(f"MyTool failed: {e}")
            return f"Error: {e}"

    def get_tool_spec(self) -> dict:
        """
        Tell LLM what parameters this tool accepts.
        LLM Router auto-converts format to match provider (Claude/Gemini).
        """
        return {
            "name": "my_tool",
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
Input:
  user_id  → Telegram chat ID (string), e.g. "25340254"
  args     → Text after command, e.g. "/email force 7d" → args = "force 7d"
             Or string sent by LLM via function calling

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
        "name": "tool_name",           # must match self.name
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

**If tool has no parameters** — don't override `get_tool_spec()` (BaseTool has a default).

### 5. Error Handling

```python
async def execute(self, user_id: str, args: str = "") -> str:
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

---

## Pre-Deploy Checklist

- [ ] File is in the `tools/` directory
- [ ] Class inherits from `BaseTool`
- [ ] `name`, `description`, `commands` are all set
- [ ] `execute()` always returns a string (never returns None)
- [ ] `execute()` catches all exceptions — no unhandled errors
- [ ] `get_tool_spec()` has a clear description (LLM uses it to decide)
- [ ] If using an API key → added to `.env`, `.env.example`, `core/config.py`
- [ ] If using a new library → added to `requirements.txt`
- [ ] Tested via direct `/command`
- [ ] Tested via free text (LLM selects correct tool)
- [ ] Updated README.md (commands table)

---

## Tool Ideas

| Tool | Command | API | Difficulty |
|---|---|---|---|
| Weather Forecast | `/weather` | Open-Meteo (free) | Easy |
| Translation | `/translate` | Use LLM (no extra API) | Easy |
| News Summary | `/news` | RSS + LLM | Easy |
| Notes / Reminders | `/note` | SQLite (already available) | Easy |
| Web Search | `/search` | Google Custom Search / SerpAPI | Medium |
| Route / Traffic | `/traffic` | Google Maps Directions API | Medium |
| Exchange Rates | `/fx` | exchangerate-api (free) | Easy |
| Package Tracking | `/track` | Carrier APIs | Medium |
| Google Calendar | `/cal` | Google Calendar API | Hard |
| Email Attachments | `/attachment` | Gmail API + PDF parser | Hard |
| YouTube Summary | `/yt` | YouTube Transcript API + LLM | Medium |

---

## Tips

1. **Description matters a lot** — LLM uses the description to decide which tool to call when users type free text. If the description is unclear, LLM will pick the wrong tool.

2. **Use LLM as a formatter** — Let your tool fetch raw data, then pass it to LLM for natural language summarization. The results will be much better than manual formatting (see email_summary for this pattern).

3. **Multiple commands are supported** — `commands = ["/weather", "/w"]` lets users type shorter commands.

4. **Test /command first** — Test via direct `/command` before free text, since it bypasses LLM and shows raw output for easier debugging.

5. **Always keep API keys in .env** — Never hardcode them in tool files.
