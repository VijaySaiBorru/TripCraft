# agentic_trip/agents/attractionagent.py

import json
import re
import os
import csv
import ast
from typing import List, Dict

class AttractionAgent:

    def __init__(self, llm):
        self.llm = llm
    @staticmethod
    def normalize_attractions(raw_list, city):
        normalized = []

        for block in raw_list:
            if not isinstance(block, str):
                continue

            for line in block.splitlines():
                line = line.strip()
                if not line:
                    continue

                # skip header
                if line.lower().startswith("name"):
                    continue

                # remove emojis / non-ascii
                line = re.sub(r"[^\x00-\x7F]+", " ", line)

                parts = line.split()
                if len(parts) < 7:
                    continue

                try:
                    # -----------------------------
                    # LAST TOKENS: lat, lon, website
                    # -----------------------------
                    lon = float(parts[-2])
                    lat = float(parts[-3])
                    website = parts[-1] if parts[-1].startswith("http") else "Unknown"

                    # Everything before lat/lon
                    prefix = parts[:-3]

                    # -----------------------------
                    # Find categories list [ ... ]
                    # -----------------------------
                    start = None
                    end = None
                    for i, tok in enumerate(prefix):
                        if tok.startswith("["):
                            start = i
                        if tok.endswith("]"):
                            end = i
                            break

                    if start is None or end is None:
                        continue

                    # -----------------------------
                    # Parse categories
                    # -----------------------------
                    categories_raw = " ".join(prefix[start:end + 1])
                    categories = [
                        c.strip().lower()
                        for c in eval(categories_raw)
                        if isinstance(c, str)
                    ]

                    # -----------------------------
                    # Name = before categories
                    # -----------------------------
                    name = " ".join(prefix[:start]).strip()

                    # -----------------------------
                    # Address = after visit_duration till lat
                    # layout: name [cats] duration address...
                    # -----------------------------
                    address = " ".join(prefix[end + 2:]).strip()
                    if not address:
                        address = "Unknown"

                    normalized.append({
                        "name": name,
                        "categories": categories,     # ✅ IMPORTANT
                        "latitude": lat,
                        "longitude": lon,
                        "address": address,
                        # "phone": "Unknown",
                        "website": website,
                        "city": city
                    })

                except Exception:
                    continue

        return normalized

    # ----------------------------------------------------------
    # ROBUST JSON EXTRACTION
    # ----------------------------------------------------------
    def extract_json(self, text):
        if not text or not isinstance(text, str):
            return {}

        # Try simple block extraction
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except Exception:
            pass

        # Fallback scanner
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
                        block = text[start:i + 1]
                        try:
                            return json.loads(block)
                        except Exception:
                            start = None
        return {}

    def get_attractions_for_city(
        self,
        city: str
    ) -> List[Dict]:
        """
        Retrieve and normalize attractions for a given city from CSV.

        Responsibilities:
        - Read from CSV
        - Filter by city
        - Normalize categories, visit duration, coordinates, address
        - Return structured attraction objects

        NO LLM
        NO persona logic
        NO ranking
        """

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        CSV_PATH = os.path.abspath(
            os.path.join(
                BASE_DIR,
                "../../TripCraft_database/attraction/cleaned_attractions_final.csv"
            )
        )

        results = []
        city = city.strip().lower()

        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:

                # ---- City filter ----
                if not row.get("City"):
                    continue

                if row["City"].strip().lower() != city:
                    continue

                # ---- Categories ----
                categories = []
                try:
                    raw_cats = row.get("subcategories") or row.get("subtype")
                    if raw_cats:
                        categories = [
                            c.strip().lower()
                            for c in ast.literal_eval(raw_cats)
                            if isinstance(c, str)
                        ]
                except Exception:
                    categories = []

                # ---- Visit duration (hours) ----
                try:
                    visit_duration = float(row.get("visit_duration"))
                except Exception:
                    visit_duration = None  # optional but preserved

                # ---- Coordinates (mandatory) ----
                try:
                    latitude = float(row.get("latitude"))
                    longitude = float(row.get("longitude"))
                except Exception:
                    continue

                # ---- Address ----
                address = (
                    row.get("address")
                    or row.get("localAddress")
                    or "Unknown"
                )

                # ---- Website ----
                website = row.get("website")
                if not website or not website.startswith("http"):
                    website = "Unknown"

                results.append({
                    "name": row.get("name"),
                    "categories": categories,
                    "description": row.get("description") or "",
                    "visit_duration": visit_duration,
                    "latitude": latitude,
                    "longitude": longitude,
                    "address": address,
                    "website": website,
                    "city": row.get("City"),
                })

        return results[:30]
    # ----------------------------------------------------------
    # Build simplified prompt (NAMES ONLY)
    # ----------------------------------------------------------
    def build_prompt(self, attraction_ref, persona, trip_json, local_constraints):

        attraction_cards = []

        for a in attraction_ref:
            card = {
                "name": a.get("name"),
                "categories": a.get("categories"),
                "description": a.get("description") or "",
                "visit_duration": a.get("visit_duration"),
            }
            attraction_cards.append(card)

        prompt = f"""
You are an ATTRACTION SELECTION AGENT.

TASK:
Select 8–12 attractions and ORDER them by how well they match
the persona preferences and local constraints.

- Select UP TO all available attractions.
- If fewer than 8 exist, select ALL of them.


IMPORTANT:
- Ranking means RELATIVE PERSONA RELEVANCE only
- Do NOT use popularity, ratings, reviews, or external knowledge
- Do NOT assume any attraction is globally better


RULES:
----------------------------------------------------------
✔ Return ONLY attraction NAMES (no objects)
✔ Names MUST come from the provided reference list
✔ NO hallucinations
✔ NO markdown, NO ```
----------------------------------------------------------

ATTRACTIONS (USE CATEGORIES FOR MATCHING):
{json.dumps(attraction_cards, indent=2)}


PERSONA:
{json.dumps(persona, indent=2)}

IMPORTANT INTERPRETATION NOTE (ATTRACTIONS):
----------------------------------------------------------
Attraction categories mentioned in:
- persona
- local_constraints
- user query

represent the TYPES of attractions the user WANTS TO EXPERIENCE.

DATA-ALIGNED RULES (STRICT):
- Treat attraction categories as POSITIVE PREFERENCES only
- Categories MUST influence ranking
- Attractions matching these categories should be ranked higher
- Attractions with other categories MUST NOT be excluded
- Attraction categories are NEVER hard filters in this dataset

Attractions should ONLY be excluded if they:
- clearly violate safety constraints
- are unsuitable for the persona (e.g., kids, physical difficulty)
- conflict with explicit query intent


EXAMPLES (IMPORTANT — FOLLOW EXACTLY):
----------------------------------------------------
Example 1:
local_constraints:
{{ "attraction": ["Museums", "Sights & Landmarks"] }}

→ Rank Museums and Landmarks HIGHER.
→ Do NOT exclude Nature, Shopping, or other attractions.

----------------------------------------------------
Example 2:
persona:
"I enjoy Outdoor Activities and Nature"

→ Rank Nature & Parks and Outdoor Activities higher.
→ Other attractions may still appear lower.

----------------------------------------------------
Example 3:
local_constraints:
{{ "attraction": ["Zoos & Aquariums"] }}

→ Prefer Zoos & Aquariums if available.
→ Do NOT assume other attractions are forbidden.

----------------------------------------------------
Example 4:
No attraction preference mentioned

→ Rank purely by persona themes and suitability.

----------------------------------------------------
Example 5 (IMPORTANT):
local_constraints:
{{ "attraction": ["Food & Drink"] }}

→ Prefer Food & Drink experiences.
→ This does NOT mean “only Food & Drink attractions”.


LOCAL CONSTRAINTS:
{json.dumps(local_constraints, indent=2)}

PERSONA PREFERENCES (GUIDANCE):
----------------------------------------------------
Luxury → iconic & famous
Adventure → outdoor, nature, hiking, beaches
Cultural → museums, temples, historical monuments
Family → kid-friendly & safe
Budget → free / cheap attractions
Nightlife → lively / waterfront
Nature Lover → gardens, viewpoints, scenic areas

====================================================
STRICT OUTPUT FORMAT (JSON ONLY)
====================================================
{{
  "attractions_ranked": [
    "Attraction Name 1",
    "Attraction Name 2",
    ...
  ]
}}

ONLY return the JSON above.
"""
        return prompt

    # ----------------------------------------------------------
    # MAIN LOGIC (NO FALLBACK)
    # ----------------------------------------------------------
    def choose_attractions(self, reference_json, persona, trip_json, local_constraints,city):

        raw_attractions = reference_json.get("attractions", [])
        # print("Raw Attractions:",raw_attractions)
        attraction_ref = self.normalize_attractions(raw_attractions,city)
        csv_attractions = self.get_attractions_for_city(city)
        attraction_ref=csv_attractions
        # print("CSV Attractions:",csv_attractions)
        # print("After Normalization:",attraction_ref)

        if not attraction_ref:
            raise Exception("AttractionAgent: No attractions available")
        # print("Attraction Ref:",attraction_ref)

        # Build LLM prompt
        prompt = self.build_prompt(
            attraction_ref=attraction_ref,
            persona=persona,
            trip_json=trip_json,
            local_constraints=local_constraints,
        )

        # Call LLM
        try:
            # print("Attraction Prompt:",prompt)
            response = self.llm.generate(prompt)
            # print("The response:",response)
        except Exception as e:
            raise Exception(f"AttractionAgent: LLM call failed: {e}")

        if not response:
            raise Exception("AttractionAgent: Empty LLM response")

        # Extract JSON
        data = self.extract_json(response)
        if not data or "attractions_ranked" not in data:
            raise Exception("AttractionAgent: Invalid JSON or missing 'attractions_ranked'")

        ranked_names = data["attractions_ranked"]
        if not isinstance(ranked_names, list):
            raise Exception("AttractionAgent: 'attractions_ranked' must be a list")

        # ------------------------------------------------------
        # Convert names → attraction objects
        # ------------------------------------------------------
        final_list = []
        for name in ranked_names:
            nm = name.strip().lower()
            match = next((a for a in attraction_ref if a.get("name", "").strip().lower() == nm), None)
            if match:
                final_list.append(match)

        # require minimum count
        # ------------------------------------------------------
        # Dynamic minimum enforcement
        # ------------------------------------------------------
        available_count = len(attraction_ref)
        # print("Available Count:",available_count)
        min_required = min(4, available_count)

        if len(final_list) < min_required:
            raise Exception(
                f"AttractionAgent: Too few valid attractions matched "
                f"({len(final_list)} < {min_required})"
            )


        return {"attractions_ranked": final_list}
