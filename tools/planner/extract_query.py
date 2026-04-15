# extract_query.py
"""
Extract people_number, budget, and local_constraint from trip_json["query"]
using the existing LLM instance.

Design rules:
- DO NOT initialize LLM here
- DO NOT add new schema keys
- DO NOT guess or infer values
- Fill ONLY explicitly stated values
- Output must match trip_json schema exactly
"""

import json
from typing import Dict, Any


# ------------------------------------------------------------
# JSON extraction helper (same logic as your agents)
# ------------------------------------------------------------
def extract_json(text: str) -> Dict[str, Any]:
    if not text or not isinstance(text, str):
        return {}

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


# ------------------------------------------------------------
# LLM PROMPT (WITH EXAMPLES, SCHEMA-LOCKED)
# ------------------------------------------------------------
PROMPT = """
You are a STRICT information extraction system.

Extract ONLY the following fields from the travel query.
Do NOT guess.
Do NOT infer.
If a value is NOT explicitly stated OR defined by the interpretation rules, return null.

Return ONLY valid JSON.
No explanation.
No markdown.

FIELDS:
- people_number (integer)
- budget (number or null)
- local_constraint:
  - house rule (string or null)
  - cuisine (string or null)
  - room type (string or null)
  - transportation (string or null)
  - event (string or null)
  - attraction (string or null)

====================
INTERPRETATION RULES
====================

People count rules:
- Words like "solo", "single", "me", "myself", "alone" → people_number = 1
- Phrases like "two people", "we are two", "couple" → people_number = 2
- Phrases like "group of X", "party of X" → people_number = X

Budget rules:
- "$1900", "$1,900", "budget is 1900", "budget set at $1900" → budget = 1900
- If no numeric budget exists → budget = null

Constraint rules:
- Extract constraints only if they are explicitly mentioned.
- Constraints may refer to house rules, cuisine preferences, room types,
  transportation restrictions, preferred event categories, or attraction types.
- If the query says "no specific constraints" → all constraints = null.
- Do NOT invent preferences.
- If multiple cuisines, events, or attractions are mentioned, combine them as comma-separated values.

====================
EXAMPLES
====================

Query:
"Plan a 3-day trip for one person from St. Petersburg to Rockford. The budget is $1700."

Output:
{
  "people_number": 1,
  "budget": 1700,
  "local_constraint": {
    "house rule": null,
    "cuisine": null,
    "room type": null,
    "transportation": null,
    "event": null,
    "attraction": null
  }
}

Query:
"We are a group of 4 traveling with a budget of $9400. We require entire rooms and no flights."

Output:
{
  "people_number": 4,
  "budget": 9400,
  "local_constraint": {
    "house rule": null,
    "cuisine": null,
    "room type": "Entire room",
    "transportation": "No flights",
    "event": null,
    "attraction": null
  }
}

Query:
"Our budget is $5500. We prefer Indian cuisine."

Output:
{
  "people_number": 1,
  "budget": 5500,
  "local_constraint": {
    "house rule": null,
    "cuisine": "Indian",
    "room type": null,
    "transportation": null,
    "event": null,
    "attraction": null
  }
}

Query:
"Plan a 3-day trip for 2 people from Charlotte to Lexington from November 22nd to November 24th, 2024, with a budget of $1,200. Accommodations should allow pets. Include dining options featuring French, Indian, Italian, and American cuisines, and visits to attractions such as sights, landmarks, and traveler resources."

Output:
{
  "people_number": 2,
  "budget": 1200,
  "local_constraint": {
    "house rule": "pets",
    "cuisine": "French, Indian, Italian, American",
    "room type": null,
    "transportation": null,
    "event": null,
    "attraction": "Sights & Landmarks, Traveler Resources"
  }
}

Query:
"Plan a 3-day trip for 3 people from Madison to New York from November 21st to November 23rd, 2024, with a budget of $4,950. Include visits to museums as part of the itinerary."

Output:
{
  "people_number": 3,
  "budget": 4950,
  "local_constraint": {
    "house rule": null,
    "cuisine": null,
    "room type": null,
    "transportation": null,
    "event": null,
    "attraction": "Museums"
  }
}

Query:
"Plan a 3-day trip for 3 people from Miami to Atlanta from November 1st to November 3rd, 2024, with a budget of $2,400. The trip should avoid self-driving transportation and allow accommodations that permit pets. Include events related to music and arts & theatre."

Output:
{
  "people_number": 3,
  "budget": 2400,
  "local_constraint": {
    "house rule": "pets",
    "cuisine": null,
    "room type": null,
    "transportation": "No self-driving",
    "event": "Music, Arts & Theatre",
    "attraction": null
  }
}

Query:
"Please plan a trip for me with no specific constraints."

Output:
{
  "people_number": 1,
  "budget": null,
  "local_constraint": {
    "house rule": null,
    "cuisine": null,
    "room type": null,
    "transportation": null,
    "event": null,
    "attraction": null
  }
}

====================
NOW PROCESS THIS QUERY
====================

QUERY:
<<< {query} >>>
"""

# ------------------------------------------------------------
# PUBLIC API
# ------------------------------------------------------------
def extract_query(trip_json: Dict[str, Any], llm) -> Dict[str, Any]:
    """
    Input:
      - trip_json (expects key 'query')
      - llm (already initialized elsewhere)

    Output (partial update only):
      {
        "people_number": int,
        "budget": float,
        "local_constraint": { ... }
      }
    """

    query = trip_json.get("query", "")
    # print("\n================ RAW QUERY ================")
    # print(query)
    # print("==========================================\n")

    if not query or not isinstance(query, str):
        return {}

    # --------------------------------------------------
    # 1. BUILD PROMPT EXPLICITLY
    # --------------------------------------------------
    final_prompt = PROMPT.format(query=query)

    # --------------------------------------------------
    # 2. PRINT PROMPT (THIS IS WHAT LLM SEES)
    # --------------------------------------------------
    # print("\n================ FINAL PROMPT SENT TO LLM ================")
    # print(final_prompt)
    # print("=========================================================\n")

    # --------------------------------------------------
    # 3. SEND TO LLM
    # --------------------------------------------------
    try:
        response = llm.generate(final_prompt)
    except Exception as e:
        print("[ERROR] LLM generate failed:", e)
        return {}

    # --------------------------------------------------
    # 4. PRINT RAW RESPONSE
    # --------------------------------------------------
    # print("\n================ RAW LLM RESPONSE ================")
    # print(response)
    # print("=================================================\n")

    # --------------------------------------------------
    # 5. PARSE JSON
    # --------------------------------------------------
    data = extract_json(response)

    # print("\n================ PARSED JSON ================")
    # print(data)
    # print("============================================\n")

    if not data or not isinstance(data, dict):
        return {}

    extracted = {}

    # -----------------------------
    # people_number
    # -----------------------------
    p = data.get("people_number")
    if isinstance(p, int) and p > 0:
        extracted["people_number"] = p

    # -----------------------------
    # budget
    # -----------------------------
    b = data.get("budget")
    if isinstance(b, (int, float)) and b > 0:
        extracted["budget"] = float(b)

    # -----------------------------
    # local_constraint
    # -----------------------------
    lc = data.get("local_constraint")
    if isinstance(lc, dict):
        clean_lc = {}
        for key in [
            "house rule",
            "cuisine",
            "room type",
            "transportation",
            "event",
            "attraction"
        ]:
            val = lc.get(key)
            if isinstance(val, str) and val.strip():
                clean_lc[key] = val.strip()

        if clean_lc:
            extracted["local_constraint"] = clean_lc

    return extracted
