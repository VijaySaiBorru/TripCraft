# agentic_trip/agents/attractionagent.py

import json
import re
import os
import csv
import ast
from typing import List, Dict,Optional,Any
from itertools import product

location_types = [
"beach locations",
"city locations",
"forest and wildlife locations",
"mountain locations"
]

travel_purposes = [
"adventure travel",
"cultural exploration",
"nature exploration",
"relaxation travel"
]

spending_types = [
"economical stays",
"luxury stays"
]

traveler_types = [
"adventure traveler",
"laidback traveler"
]


def build_persona_index():

    personas = []

    for loc, purpose, spend, traveler in product(
        location_types,
        travel_purposes,
        spending_types,
        traveler_types
    ):
        personas.append((traveler, purpose, spend, loc))

    return personas


def persona_json_to_text(persona):

    if isinstance(persona, dict):

        vals = []

        for v in persona.values():

            if isinstance(v, list):
                vals.extend([str(x) for x in v])

            else:
                vals.append(str(v))

        return " ".join(vals).lower()

    return str(persona).lower()


def parse_json_persona(persona):

    p = persona_json_to_text(persona)

    # traveler
    if "laidback" in p:
        traveler = "laidback traveler"
    else:
        traveler = "adventure traveler"

    # purpose
    if "cultural" in p:
        purpose = "cultural exploration"

    elif "nature" in p:
        purpose = "nature exploration"

    elif "relax" in p:
        purpose = "relaxation travel"

    elif "adventure" in p:
        purpose = "adventure travel"

    else:
        purpose = "adventure travel"

    # spending
    if "luxury" in p:
        spend = "luxury stays"

    elif "economical" in p or "budget" in p:
        spend = "economical stays"

    else:
        spend = "economical stays"

    # location
    if "beach" in p:
        location = "beach locations"

    elif "mountain" in p:
        location = "mountain locations"

    elif "forest" in p or "wildlife" in p:
        location = "forest and wildlife locations"

    elif "city" in p:
        location = "city locations"

    else:
        location = "city locations"

    return traveler, purpose, spend, location


def get_persona_index(persona):

    traveler, purpose, spend, location = parse_json_persona(persona)

    personas = build_persona_index()

    target = (traveler, purpose, spend, location)

    for i, p in enumerate(personas):

        if p == target:
            return i + 1

    return 1

class AttractionAgent:

    def __init__(self, llm):

        self.llm = llm

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))

        review_path = os.path.abspath(
            os.path.join(
                BASE_DIR,
                "../../TripCraft_database/review_pro_cons/attraction_review_pro_cons_fixed.csv"
            )
        )

        self.review_by_index = {}
        self.review_by_name = {}

        if os.path.exists(review_path):

            with open(review_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                for row in reader:

                    try:
                        idx = int(float(row["attraction_index"]))
                        self.review_by_index[idx] = row
                    except:
                        pass

                    key = (
                        row["City"].strip().lower(),
                        row["Name"].strip().lower()
                    )

                    self.review_by_name.setdefault(key, []).append(row)

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
        city: str,
        persona: Optional[Dict[str, Any]] = None,
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
        persona_idx = get_persona_index(persona) if persona else 1

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
                # ------------------------------------------------
                # REVIEW LOOKUP
                # ------------------------------------------------

                review_rows = []
                try:
                    idx = int(float(row.get("attraction_index")))
                    r = self.review_by_index.get(idx)
                    if r:
                        review_rows = [r]
                except Exception:
                    pass

                if not review_rows:

                    key = (
                        row.get("City", "").strip().lower(),
                        row.get("name", "").strip().lower()
                    )

                    review_rows = self.review_by_name.get(key, [])

                # ------------------------------------------------
                # AGGREGATE REVIEW SIGNALS
                # ------------------------------------------------

                pros = []
                cons = []

                if review_rows:
                    r0 = review_rows[0]
                    pros = self.parse_pipe(r0.get("pros"))
                    cons = self.parse_pipe(r0.get("cons"))

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

                    # review signals
                    "pros": pros,
                    "cons": cons,
                    "pros_count": len(pros),
                    "cons_count": len(cons)
                })

        results.sort(
                key=lambda a: (
                    -(a.get("pros_count") or 0),
                    (a.get("cons_count") or 0) * 3,
                )
            )
        return results
    # ----------------------------------------------------------
    # Build simplified prompt (NAMES ONLY)
    # ----------------------------------------------------------
    def build_prompt(self, attraction_ref, persona, trip_json, local_constraints):

        attraction_cards = []

        for a in attraction_ref:
            card = {
                "name": a.get("name"),
                "categories": a.get("categories"),
                "visit_duration": a.get("visit_duration"),
                "pros": a.get("pros"),
                "cons": a.get("cons"),
            }
            attraction_cards.append(card)

        prompt = f"""
You are an ATTRACTION SELECTION AGENT.

TASK:
Select 8–12 attractions and ORDER them by how well they match
the persona preferences and local constraints.

- Select UP TO all available attractions.
- If fewer than 8 exist, select ALL of them.

Ranking MUST be based on:
- category match with persona and local_constraints
- pros: positive aspects visitors liked
- cons: negative aspects visitors reported

Use the following factors for ranking:
- Category and type match with persona and local_constraints.
- Visit_duration suitability for the trip (avoid extremely long activities if not reasonable).

SELECTION LOGIC:
- Prefer attractions whose categories match persona and local constraints.
- Prefer attractions with strong relevant pros.
- Strongly avoid attractions with severe cons (e.g., overcrowding, safety issues, poor experience).
- If multiple options are similar, prefer more pros and fewer serious cons.

IMPORTANT:
- If no pros and no cons → low-information
- If pros but no cons → neutral (not perfect)

Do NOT use any external knowledge beyond the data provided in the attraction list.

SPECIAL PRIORITY:
- The FIRST 3–4 attractions SHOULD satisfy explicit attraction-type preferences from local_constraints when possible.
- If not enough such attractions exist, include as many as possible at the top, then fill remaining positions with the next best matches.

IMPORTANT:
- Ranking means RELATIVE PERSONA RELEVANCE only.
- Use ONLY the fields provided in the attraction list (no external knowledge).
- Do NOT assume any attraction is globally better outside this dataset.

This is a RELATIVE ranking:
Earlier items = better match.
Later items = weaker match.

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
        csv_attractions = self.get_attractions_for_city(city,persona)
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
            print("Attraction Prompt:",prompt)
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
