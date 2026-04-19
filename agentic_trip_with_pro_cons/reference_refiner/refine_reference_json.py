import re
import json
from collections import defaultdict
from typing import Dict, Any, List


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def _parse_city_from_description(desc: str) -> str:
    """
    Extract city name from descriptions like:
    - 'Attractions in Rochester'
    - 'Events within 2024-11-05 and 2024-11-07 in Watertown'
    """
    if " in " not in desc:
        return ""
    return desc.rsplit(" in ", 1)[-1].strip()


def _parse_transport_from_description(desc: str) -> Dict[str, Any]:
    out = {}

    d = desc.lower()
    if d.startswith("flight"):
        out["mode"] = "flight"
    elif d.startswith("self-driving"):
        out["mode"] = "self-driving"
    elif d.startswith("taxi"):
        out["mode"] = "taxi"
    else:
        return {}

    m = re.search(r"from\s+(.*?)\s+to\s+(.*?)(?:\s+on\s+|$)", desc, re.IGNORECASE)
    if not m:
        return {}

    out["from"] = m.group(1).strip()
    out["to"] = m.group(2).strip()

    dm = re.search(r"on\s+(\d{4}-\d{2}-\d{2})", desc)
    if dm:
        out["date"] = dm.group(1)

    return out


def _parse_reference_information(raw) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        return raw

    if not isinstance(raw, str):
        return []

    blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]
    out = []

    for block in blocks:
        try:
            parsed = json.loads(block)
            if isinstance(parsed, list):
                out.extend(parsed)
        except Exception:
            continue

    return out


# --------------------------------------------------
# MAIN FUNCTION
# --------------------------------------------------

def refine_reference_json(reference_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    OUTPUT:
    {
      transportation: { legs: [...] },
      cities: {
        City: {
          attractions: [],
          restaurants: [],
          accommodations: [],
          events: [],
          raw_transit_rows: []
        }
      }
    }
    """

    ref_list = _parse_reference_information(
        reference_json.get("reference_information")
    )

    if not ref_list:
        return reference_json

    cities = defaultdict(lambda: {
        "attractions": [],
        "restaurants": [],
        "accommodations": [],
        "events": [],
        "raw_transit_rows": []
    })

    transport_legs = {}
    raw_events = []          # events without city info
    raw_transit_rows = []   # ✅ CREATE ONCE

    for item in ref_list:
        if not isinstance(item, dict):
            continue

        desc = item.get("Description", "")
        content = item.get("Content", "")
        if not desc or not content:
            continue

        desc_l = desc.lower()

        # ---------------- TRANSPORT ----------------
        if desc_l.startswith(("flight", "self-driving", "taxi")):
            meta = _parse_transport_from_description(desc)
            if not meta:
                continue

            key = (meta["from"], meta["to"])
            if key not in transport_legs:
                transport_legs[key] = {
                    "from": meta["from"],
                    "to": meta["to"],
                    "modes": {}
                }

            entry = {"content": content}
            if meta.get("mode") == "flight" and "date" in meta:
                entry["date"] = meta["date"]

            transport_legs[key]["modes"][meta["mode"]] = entry
            continue

        # ---------------- EVENTS ----------------
        if desc_l.startswith("events within"):
            city = _parse_city_from_description(desc)
            if city:
                cities[city]["events"].append(content)
            else:
                raw_events.append(content)
            continue

        # ---------------- NEAREST TRANSIT (STORE RAW ONLY) ----------------
        if desc_l.startswith("nearest public transit"):
            lines = content.splitlines()
            for row in lines[1:]:
                row = row.strip()
                if row:
                    raw_transit_rows.append(row)
            continue

        # ---------------- CITY DATA ----------------
        city = _parse_city_from_description(desc)
        if not city:
            continue

        if "attraction" in desc_l:
            cities[city]["attractions"].append(content)
        elif "restaurant" in desc_l:
            cities[city]["restaurants"].append(content)
        elif "accommodation" in desc_l:
            cities[city]["accommodations"].append(content)

    # ---------------- ATTACH TRANSIT TO ALL CITIES ----------------
    for city in cities:
        cities[city]["raw_transit_rows"] = raw_transit_rows

    # ---------------- RESOLVE EVENTS WITHOUT CITY ----------------
    if raw_events:
        city_names = list(cities.keys())
        if len(city_names) == 1:
            cities[city_names[0]]["events"].extend(raw_events)

    return {
        "transportation": {"legs": list(transport_legs.values())},
        "cities": dict(cities)
    }
