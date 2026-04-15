# agentic_trip/agents/mealsagent.py

import json
import re
from typing import Any, Dict, List, Optional
import os
import csv
import ast


class MealsAgent:
    def __init__(self, llm):
        self.llm = llm

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


    def get_restaurants_for_city(
        self,
        city: str,
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

                results.append({
                    "name": name,
                    "avg_cost": avg_cost,
                    "cuisines": cuisines,
                    "aggregate_rating": rating,
                    # "description": description,
                    # "city": row.get("City"),
                })

        # ---- Sort cheapest first (stable baseline) ----
        results.sort(key=lambda r: r["avg_cost"])

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

Ranking MUST be based on:
- cuisine match with persona AND local constraints
- aggregate_rating
- budget-friendliness (lower avg_cost is preferred)
- suitability for a traveler (not hyper-local places)

This is a RELATIVE ordering only.
Earlier items = better persona fit.
Later items = worse persona fit.


"BEST" means:
- better cuisine match with persona / constraints
- higher aggregate_rating
- more budget-friendly (lower avg_cost)

RANKING RULES (STRICT):
----------------------------------------------------
✔ Prefer restaurants whose cuisines match persona OR local_constraints.
✔ Prefer HIGHER aggregate_rating.
✔ Prefer LOWER avg_cost when ratings/cuisines are similar.
✔ Ranking is ONLY by persona + local suitability.
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
- Cuisine mentions MUST NOT exclude any restaurant
- Cuisine is NEVER a hard filter in this dataset
- Do NOT assume dietary restrictions unless explicitly stated elsewhere

Cuisine mentions = SOFT preference (ranking only), not exclusion.


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
- cuisine preferences from persona or local_constraints
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
        csv_restaurants = self.get_restaurants_for_city(city)   
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
