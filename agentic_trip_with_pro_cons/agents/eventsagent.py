import json
from typing import List, Dict, Any, Optional
from data_manager.events_loader import EventsLoader
import os
import csv
from datetime import datetime

class EventAgent:

    def __init__(self, llm):
        self.llm = llm
        self.events_loader = EventsLoader()

    # ----------------------------------------------------------
    # ADAPT EVENTS (FROM EventsLoader → Agent format)
    # ----------------------------------------------------------
    @staticmethod
    def adapt_events(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert EventsLoader rows into EventAgent format.
        NO parsing. NO guessing. NO heuristics.
        """
        events = []

        for r in rows:
            if not r.get("name") or not r.get("dateTitle"):
                continue

            try:
                date_str = r["dateTitle"].strftime("%Y-%m-%d")
            except Exception:
                continue

            categories = []
            for k in ("segmentName", "genre"):
                if r.get(k):
                    categories.append(str(r[k]).lower())

            events.append({
                "name": r["name"],
                "date": date_str,
                "categories": categories,
                "address": r.get("streetAddress", ""),
                "city": r.get("city", ""),
                "url": r.get("url", "")
            })

        return events

    # ----------------------------------------------------------
    # JSON extraction (robust)
    # ----------------------------------------------------------
    def extract_json(self, text: str) -> Dict[str, Any]:
        if not text or not isinstance(text, str):
            return {}

        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except Exception:
            pass

        stack = []
        start = None
        for i, ch in enumerate(text):
            if ch == "{":
                if start is None:
                    start = i
                stack.append("{")
            elif ch == "}":
                if stack:
                    stack.pop()
                    if not stack:
                        try:
                            return json.loads(text[start:i + 1])
                        except Exception:
                            start = None
        return {}

    def get_events_for_city(
        self,
        city: str,
        event_dates: Optional[List[str]] = None,
        max_results: int = 25
    ) -> List[Dict]:
        """
        Retrieve and normalize events for a given city from CSV.

        Responsibilities:
        - Read from CSV
        - Filter by city
        - Support single-date and date-range events
        - Match strictly against allowed trip dates
        - Normalize name, date, categories, address, url
        - Apply hard result limit

        NO LLM
        NO persona logic
        NO ranking
        """

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        CSV_PATH = os.path.abspath(
            os.path.join(
                BASE_DIR,
                "../../TripCraft_database/events/events_cleaned.csv"
            )
        )

        results = []
        city = city.strip().lower()

        # Convert allowed dates to date objects for comparison
        allowed_date_objs = set()
        if event_dates:
            for d in event_dates:
                try:
                    allowed_date_objs.add(datetime.strptime(d, "%Y-%m-%d").date())
                except Exception:
                    pass

        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:

                # ---- City filter ----
                if not row.get("city"):
                    continue
                if row["city"].strip().lower() != city:
                    continue

                # ---- Date parsing (single OR range) ----
                raw_date = row.get("dateTitle")
                if not raw_date:
                    continue

                start_date = end_date = None

                try:
                    if "to" in raw_date:
                        start_str, end_str = [p.strip() for p in raw_date.split("to")]
                        start_date = datetime.strptime(start_str, "%d-%m-%Y").date()
                        end_date = datetime.strptime(end_str, "%d-%m-%Y").date()
                    else:
                        start_date = end_date = datetime.strptime(
                            raw_date.strip(), "%d-%m-%Y"
                        ).date()
                except Exception:
                    continue

                # ---- Categories ----
                categories = []
                if row.get("segmentName"):
                    categories.append(row["segmentName"].lower())
                if row.get("genreName"):
                    categories.append(row["genreName"].lower())

                # ---- Name ----
                name = row.get("name")
                if not name:
                    continue

                # ---- Expand per allowed date ----
                for d in allowed_date_objs:
                    if start_date <= d <= end_date:
                        results.append({
                            "name": name,
                            "date": d.strftime("%Y-%m-%d"),
                            "categories": categories,
                            "address": row.get("streetAddress", ""),
                            "city": row.get("city"),
                            "url": row.get("url", "")
                        })

                        if len(results) >= max_results:
                            return results

        return results

    # ----------------------------------------------------------
    # BUILD PROMPT (ONE EVENT PER DATE)
    # ----------------------------------------------------------
    def build_prompt(self, events, persona, local_constraints):

        event_cards = [
            {
                "name": e["name"],
                "date": e["date"],
                "categories": e.get("categories", []),
                "city": e["city"]
            }
            for e in events
        ]

        return f"""
You are an EVENT SELECTION AGENT.

TASK:
- Events are DATE-BOUND.
- Select AT MOST ONE event per DATE.
- Events are OPTIONAL (null is allowed).

====================================================
CORE RULES (STRICT)
====================================================
✔ Use ONLY the provided event list
✔ One event MAX per date
✔ Events are OPTIONAL — returning null is valid
✔ Do NOT hallucinate events
✔ Output JSON ONLY

====================================================
EVENT SELECTION LOGIC
====================================================
Event categories mentioned in:
- persona
- local_constraints
- user query

represent event TYPES the user is INTERESTED IN.

DATA-ALIGNED RULES (STRICT):
- Treat event category mentions as POSITIVE PREFERENCES only
- Event categories MUST influence selection when events exist
- Prefer events whose categories match these preferences
- Do NOT exclude events solely because they belong to other categories
- Event categories are NEVER hard filters in this dataset

====================================================
EVENTS:
====================================================
{json.dumps(event_cards, indent=2)}

====================================================
PERSONA:
====================================================
{json.dumps(persona, indent=2)}

====================================================
LOCAL CONSTRAINTS:
====================================================
{json.dumps(local_constraints, indent=2)}

====================================================
EXAMPLES (IMPORTANT — FOLLOW EXACTLY)
====================================================
Example 1:
local_constraints:
{{ "event": ["Music"] }}

→ If a Music event exists on a date, select it.
→ If multiple Music events exist on the same date, pick ONE best match.
→ If no Music event exists, you MAY return null.

----------------------------------------------------
Example 2:
persona mentions:
"I enjoy Arts & Theatre"

→ Prefer Arts & Theatre events when available.
→ Do NOT exclude Sports or Music events automatically.

----------------------------------------------------
Example 3:
local_constraints:
{{ "event": ["Sports", "Music"] }}

→ Prefer Sports or Music events.
→ Choose only ONE event per date.

----------------------------------------------------
Example 4:
No event preference mentioned

→ You may choose ANY suitable event OR return null.

----------------------------------------------------
Example 5 (IMPORTANT):
No events available on a date

→ Return null for that date.

====================================================
STRICT OUTPUT FORMAT (JSON ONLY)
====================================================
{{
  "events_by_date": {{
    "YYYY-MM-DD": "Event Name",
    "YYYY-MM-DD": null
  }}
}}

NO markdown.
NO explanations.
ONLY pure JSON.
"""

    # ----------------------------------------------------------
    # MAIN LOGIC (CLEAN, DATE-FILTERED)
    # ----------------------------------------------------------
    def choose_events(
        self,
        reference_city_block: Dict[str, Any],
        persona: Dict[str, Any],
        trip_json: Dict[str, Any],
        local_constraints: Dict[str, Any],
        city: str,
        event_dates: Optional[List[str]] = None
    ) -> Dict[str, Any]:

        # ----------------------------------------
        # Load events ONCE
        # ----------------------------------------
        self.events_loader.load()

        # date range from trip
        if not event_dates:
            return {"events": []}

        start_date = min(event_dates)
        end_date = max(event_dates)

        # ----------------------------------------
        # Fetch structured events
        # ----------------------------------------
        rows = self.events_loader.run(
            city=city,
            date_range=[start_date, end_date]
        )

        # if not rows:
        #     return {"events": []}

        # ----------------------------------------
        # Adapt (NO parsing)
        # ----------------------------------------
        csv_events = self.get_events_for_city(
            city=city,
            event_dates=event_dates,
            max_results=25
        )
        # print(csv_events)
        # all_events = self.adapt_events(rows)

        # ----------------------------------------
        # Strict date filter
        # ----------------------------------------
        allowed_dates = set(event_dates)
        # events = [e for e in all_events if e["date"] in allowed_dates]
        # print("Filtered events:",events)
        # print("CSV events:",csv_events)
        events = csv_events

        if not events:
            return {"events": []}
        
        

        # ----------------------------------------
        # LLM selection
        # ----------------------------------------
        prompt = self.build_prompt(events, persona, local_constraints)

        try:
            response = self.llm.generate(prompt)
            # print("EventAgent LLM response:",response)
        except Exception as e:
            raise Exception(f"EventAgent: LLM call failed: {e}")

        data = self.extract_json(response)
        if not data or "events_by_date" not in data:
            return {"events": []}

        chosen = data["events_by_date"]

        # ----------------------------------------
        # One event per date (hard guarantee)
        # ----------------------------------------
        selected = []
        for e in events:
            if chosen.get(e["date"]) == e["name"]:
                selected.append(e)
        
        # print("Selected events:",selected)

        return {"events": selected}
