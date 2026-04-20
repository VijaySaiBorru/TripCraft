# agentic_trip/agents/mealsagent.py

import json
import re
from typing import Any, Dict, List, Optional
import os
import csv
import ast
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


class MealsAgent:
    def __init__(self, llm):

        self.llm = llm

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))

        review_path = os.path.abspath(
            os.path.join(
                BASE_DIR,
                "../../TripCraft_database/review_pro_cons/restaurant_review_pro_cons_clean.csv"
            )
        )

        self.review_by_index = {}
        self.review_by_name = {}

        if os.path.exists(review_path):

            with open(review_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                for row in reader:

                    # ---- index lookup ----
                    try:
                        idx = int(float(row["restaurant_index"]))
                        self.review_by_index[idx] = row
                    except:
                        pass

                    # ---- name + city lookup ----
                    key = (
                        row["City"].strip().lower(),
                        row["Name"].strip().lower()
                    )

                    self.review_by_name.setdefault(key, []).append(row)

    # ----------------------------------------------------------
    # Robust JSON extractor
    # ----------------------------------------------------------
    @staticmethod
    def normalize_restaurants(raw_list: List[str], city: str) -> List[Dict]:
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
                if len(parts) < 6:
                    continue

                try:
                    # RIGHT SIDE (stable)
                    rating = float(parts[-1])
                    avg_cost = float(parts[-2])

                    # cuisines are EVERYTHING between name and cost
                    cuisines_tokens = parts[:-2]

                    # find the cuisine list boundaries
                    start = None
                    end = None
                    for i, tok in enumerate(cuisines_tokens):
                        if tok.startswith("["):
                            start = i
                        if tok.endswith("]"):
                            end = i
                            break

                    cuisines = []
                    if start is not None and end is not None and end >= start:
                        cuisines_raw = " ".join(cuisines_tokens[start:end + 1])
                        cuisines = [
                            c.strip().lower()
                            for c in eval(cuisines_raw)
                            if isinstance(c, str)
                        ]

                        name = " ".join(cuisines_tokens[:start]).strip()
                    else:
                        continue

                except Exception:
                    continue

                normalized.append({
                    "name": name,
                    "avg_cost": avg_cost,
                    "cuisines": cuisines,          # ✅ LIST OF STRINGS
                    "aggregate_rating": rating,
                    "city": city                   # ✅ injected
                })

        return normalized

    def extract_json(self, text: Optional[str]) -> Dict[str, Any]:
        if not text or not isinstance(text, str):
            return {}

        # Try naive block extraction
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        except Exception:
            pass

        # Fallback scanning for the first balanced JSON object
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
                    if not stack and start is not None:
                        block = text[start:i + 1]
                        try:
                            return json.loads(block)
                        except Exception:
                            # continue scanning for another balanced block
                            start = None
                            continue
        # final fallback: try to find outermost {...}
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {}
        return {}

    def parse_pipe(self, text):
        if not text or str(text).strip() == "" or str(text).lower() == "nan":
            return []
        return [x.strip() for x in str(text).split("|") if x.strip()]

    def get_restaurants_for_city(
        self,
        city: str,
        persona: Optional[Dict[str, Any]] = None,
        max_results: int = 40
    ) -> List[Dict]:
        """
        Retrieve and normalize restaurants for a given city from CSV.

        Responsibilities:
        - Read from CSV
        - Filter by city
        - Normalize cuisines, avg_cost, rating, description
        - Return top-N restaurants (cheapest first)

        NO LLM
        NO persona logic
        NO ranking decisions
        """

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        CSV_PATH = os.path.abspath(
            os.path.join(
                BASE_DIR,
                "../../TripCraft_database/restaurants/cleaned_restaurant_details_2024.csv"
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

                # ---- Name (mandatory) ----
                name = row.get("name")
                if not name:
                    continue

                # ---- Avg cost (mandatory) ----
                try:
                    avg_cost = float(row.get("avg_cost"))
                    if avg_cost <= 0:
                        continue
                except Exception:
                    continue

                # ---- Rating (optional) ----
                try:
                    rating = float(row.get("rating"))
                except Exception:
                    rating = None

                # ---- Cuisines ----
                cuisines = []
                try:
                    raw_cuisines = row.get("cuisines")
                    if raw_cuisines:
                        cuisines = [
                            c.strip().lower()
                            for c in ast.literal_eval(raw_cuisines)
                            if isinstance(c, str)
                        ]
                except Exception:
                    cuisines = []

                # ---- Description ----
                description = row.get("description") or ""
                # ----------------------------------
                # REVIEW LOOKUP
                # ----------------------------------

                review_rows = []

                # 1️⃣ try index
                try:
                    idx = int(float(row.get("restaurant_index")))
                    r = self.review_by_index.get(idx)
                    if r:
                        review_rows = [r]
                except:
                    pass

                # 2️⃣ fallback name + city
                if not review_rows:

                    key = (
                        row.get("City", "").strip().lower(),
                        name.strip().lower()
                    )

                    review_rows = self.review_by_name.get(key, [])

                # ----------------------------------
                # AGGREGATE REVIEW SIGNALS
                # ----------------------------------

                pros = []
                cons = []

                if review_rows:
                    # take first row (or aggregate if you want later)
                    r0 = review_rows[0]
                    pros = self.parse_pipe(r0.get("pros"))
                    cons = self.parse_pipe(r0.get("cons"))

                results.append({
                    "name": name,
                    "avg_cost": avg_cost,
                    "cuisines": cuisines,
                    "aggregate_rating": rating,

                    "pros": pros,
                    "cons": cons,
                    "pros_count": len(pros),
                    "cons_count": len(cons)
                })

        # ---- Sort cheapest first (stable baseline) ----
        results.sort(
            key=lambda r: (
                # strongest positives first
                -(r.get("pros_count") or 0),

                # penalize negatives heavily
                (r.get("cons_count") or 0) * 3,

                # base quality
                -(r.get("aggregate_rating") or 0),

                # cheapest last tie-break
                r.get("avg_cost", float("inf"))
            )
        )

        return results[:max_results]

    # ----------------------------------------------------------
    # Build Prompt (budget-aware version)
    # ----------------------------------------------------------
    def build_prompt(
        self,
        restaurant_ref: List[Dict[str, Any]],
        persona: Dict[str, Any],
        trip_json: Dict[str, Any],
        local_constraints: Dict[str, Any],
        caps: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        We pass meals_cap_total from AgenticPlanner so LLM can respect budget.
        """

        restaurant_cards: List[Dict[str, Any]] = []

        for r in (restaurant_ref or []):
            if not isinstance(r, dict):
                continue

            restaurant_cards.append({
                "name": r.get("name"),
                "avg_cost": r.get("avg_cost"),
                "cuisines": r.get("cuisines"),
                "aggregate_rating": r.get("aggregate_rating"),
                "pros": r.get("pros"),
                "cons": r.get("cons"),
                "pros_count": r.get("pros_count"),
                "cons_count": r.get("cons_count"),
            })

        persona_text = json.dumps(persona or {}, indent=2, ensure_ascii=False)
        constraint_text = json.dumps(local_constraints or {}, indent=2, ensure_ascii=False)

        meals_cap = None
        if caps and isinstance(caps, dict):
            meals_cap = caps.get("meals_cap_total", None)

        prompt = f"""
You are the MEAL SELECTION AGENT.

Your task:
ORDER restaurants by how well they match the user's persona
and local constraints.

SPECIAL PRIORITY (IMPORTANT):
- The FIRST 3–4 restaurants in the ranking MUST satisfy all explicit food-related local constraints whenever possible.
- If there are not enough restaurants that satisfy these constraints, then include as many as possible in the top positions and fill the remaining positions with the next best options.

Ranking MUST be based on:
- cuisine match with persona AND local constraints
- pros: positive aspects guests liked
- cons: negative aspects guests reported
- aggregate_rating
- budget-friendliness (lower avg_cost preferred)

SELECTION LOGIC:
- Prefer restaurants whose pros align with user needs and cuisine preferences.
- Strongly avoid restaurants with severe cons (e.g., bad service, poor food quality, hygiene concerns).
- Prefer higher aggregate_rating when options are similar.
- Prefer lower avg_cost when quality is similar.

IMPORTANT:
- If a restaurant has no pros and no cons → treat as low-information.
- If a restaurant has pros but no cons → treat as neutral (NOT perfect).

This is a RELATIVE ordering only.
Earlier items = better persona fit.
Later items = worse persona fit.

"BEST" means:
- better cuisine match with persona
- stronger relevant pros
- fewer serious cons
- higher aggregate_rating when options are similar
- more budget-friendly (lower avg_cost)

RANKING RULES (STRICT):
----------------------------------------------------
✔ Restaurants matching required cuisines MUST rank ABOVE non-matching ones.
✔ Prefer HIGHER aggregate_rating.
✔ Prefer LOWER avg_cost when ratings/cuisines are similar.
✔ Ranking is based on cuisine preference, pros/cons, aggregate_rating, and price.
✔ Do NOT calculate total cost, people count, or meal counts.

IMPORTANT RULES:
----------------------------------------------------
✔ Do NOT repeat restaurant names.
✔ Each restaurant name must appear only once.
✔ ONLY return restaurant NAMES in a JSON list.
✔ NO descriptions, NO objects, NO extra fields.
✔ NO hallucinations — names MUST come from the provided list.
✔ You MUST return AT LEAST 12 restaurant names.
✔ If fewer than 12 restaurants exist, return ALL available restaurants.
✔ Output exactly a JSON list of names, no explanations.

----------------------------------------------------

MEAL BUDGET CAP (for entire trip):
→ meals_cap_total = {meals_cap}

RESTAURANTS (USE THESE FIELDS FOR RANKING):
{json.dumps(restaurant_cards, indent=2, ensure_ascii=False)}


PERSONA:
{persona_text}
- DO NOT take budget from persona


IMPORTANT INTERPRETATION NOTE (CUISINES):
----------------------------------------------------
Cuisines mentioned in:
- persona
- local_constraints
- user query

represent cuisines the user WANTS TO EXPERIENCE.

DATA-ALIGNED RULES (STRICT):
- Treat all cuisine mentions as POSITIVE PREFERENCES only
- Cuisine mentions MUST influence ranking
- Restaurants matching these cuisines should be ranked higher
- Do NOT assume dietary restrictions unless explicitly stated elsewhere

CUISINE CONSTRAINT (POSITIONAL HARD RULE):
- Cuisine is a HARD requirement for TOP-ranked results.
- The FIRST 6 restaurants MUST match at least one cuisine from:
  • local_constraints
  • persona (if relevant)
- If sufficient matching restaurants exist:
  → ALL top 6 MUST be cuisine-matching
- If insufficient:
  → include as many matching as possible in top positions
  → fill remaining positions with best alternatives
- Restaurants that do NOT match required cuisines:
  → MUST be ranked LOWER than matching ones


EXAMPLES (IMPORTANT — FOLLOW THESE EXACTLY):
----------------------------------------------------
Example 1:
local_constraints:
{{ "cuisine": ["Indian", "Italian"] }}

→ Rank Indian and Italian restaurants HIGHER.
→ Do NOT exclude other cuisines.

----------------------------------------------------
Example 2:
persona:
"I love Sushi and Japanese food"

→ Rank Sushi / Japanese restaurants higher.
→ Other cuisines MUST still appear.

----------------------------------------------------
Example 3:
local_constraints:
{{ "cuisine": ["Cafe", "Wine Bar"] }}

→ Treat as EXPERIENCE preferences.
→ Rank Cafes and Wine Bars higher.
→ Do NOT assume dietary meaning.

----------------------------------------------------
Example 4:
No cuisine mentioned anywhere

→ Rank by aggregate_rating first,
  then by avg_cost.

----------------------------------------------------
Example 5 (IMPORTANT):
local_constraints:
{{ "cuisine": ["American"] }}

→ This does NOT mean "only American food".
→ It means "prefer American food in ranking".
→ Other cuisines MUST still be included.


LOCAL CONSTRAINTS:
{constraint_text}

SOFT FILTERS (ranking influence only):
----------------------------------------------------
- cuisine preferences from persona 
- budget friendliness

====================================================
OUTPUT FORMAT (STRICT JSON ONLY)
====================================================
{{
  "restaurants_ranked": [
      "Restaurant Name 1",
      "Restaurant Name 2",
      ...
  ]
}}

NO markdown.
NO code fences.
ONLY pure JSON.
"""
        return prompt

    # ----------------------------------------------------------
    # MAIN LOGIC
    # ----------------------------------------------------------
    def choose_restaurants(
        self,
        reference_json,
        persona,
        trip_json,
        local_constraints,
        city,
        caps=None,
    ):

        restaurant_ref = reference_json.get("restaurants", [])
        # print("Restaurants Before:",restaurant_ref)
        restaurant_ref = self.normalize_restaurants(restaurant_ref,city)
        # print("Restaurants After:",restaurant_ref)
        csv_restaurants = self.get_restaurants_for_city(city,persona)   
        # print("CSV Restaurants:",csv_restaurants)
        restaurant_ref=csv_restaurants

        if not restaurant_ref:
            raise Exception("MealsAgent: No restaurants available")

        caps = caps or {}
        budget = caps.get("meals_cap_total")
        if budget is None:
            raise Exception("meals_cap_total missing")

        people = int(trip_json.get("people_number", 1))

        prompt = self.build_prompt(
            restaurant_ref=restaurant_ref,
            persona=persona or {},
            trip_json=trip_json or {},
            local_constraints=local_constraints or {},
            caps=caps,
        )
        # print("Meals Agent Prompt:",prompt)

        response = self.llm.generate(prompt)
        data = self.extract_json(response)
        # print(response)
        ranked_names = data.get("restaurants_ranked", [])

        # -----------------------------
        # Map names → objects
        # -----------------------------
        ref_map = {
            r["name"].strip().lower(): r
            for r in restaurant_ref
            if r.get("name")
        }

        candidates = []
        for n in ranked_names:
            if isinstance(n, str):
                key = n.strip().lower()
                if key in ref_map:
                    candidates.append(ref_map[key])

        # Deduplicate
        seen = set()
        candidates = [
            r for r in candidates
            if not (r["name"].lower() in seen or seen.add(r["name"].lower()))
        ]

        if len(candidates) < 6:
            raise Exception("Less than 6 candidates")

        # -----------------------------
        # Phase 1: baseline cheapest 6
        # -----------------------------
        by_cost = sorted(
            candidates,
            key=lambda r: r.get("avg_cost", float("inf"))
        )

        selected = []
        total_cost = 0.0

        for r in by_cost:
            if len(selected) == 6:
                break
            cost = r["avg_cost"] * people
            if total_cost + cost <= budget:
                selected.append(r)
                total_cost += cost

        if len(selected) < 6:
            fallback = sorted(
                candidates,
                key=lambda r: r.get("avg_cost", float("inf"))
            )[:9]

            return {
                "restaurants_ranked": fallback
            }

        # -----------------------------
        # Phase 2: upgrade (swap)
        # -----------------------------
        remaining = [r for r in candidates if r not in selected]

        for r in remaining:
            r_cost = r["avg_cost"] * people

            # try replacing the cheapest selected
            cheapest = min(selected, key=lambda x: x["avg_cost"])
            cheapest_cost = cheapest["avg_cost"] * people

            new_total = total_cost - cheapest_cost + r_cost

            if new_total <= budget and r["avg_cost"] > cheapest["avg_cost"]:
                selected.remove(cheapest)
                selected.append(r)
                total_cost = new_total

        # -----------------------------
        # Phase 3: extras (cheapest)
        # -----------------------------
        leftovers = [r for r in candidates if r not in selected]

        extras = sorted(
            leftovers,
            key=lambda r: r.get("avg_cost", float("inf"))
        )[:3]

        return {
            "restaurants_ranked": selected + extras
        }
