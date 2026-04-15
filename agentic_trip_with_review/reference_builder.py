# agentic_trip/reference_builder.py
import ast
import pandas as pd
from typing import Any, Dict, Iterable, List, Optional
import math
from agentic_trip.filter_manager import FilterManager

def normalize_flights(raw):
    if raw is None:
        return []
    if isinstance(raw, dict):
        if "onward" in raw:
            return raw["onward"]
        if "return" in raw:
            return raw["return"]
        return list(raw.values())
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return [raw]


class ReferenceBuilder:
    def __init__(self, dm):
        self.dm = dm
        self.filter = FilterManager(dm)

    # ---------------------------------------------------------
    # helpers
    # ---------------------------------------------------------
    def _clean_city(self, name: Optional[str]) -> str:
        if name is None:
            return ""
        name = str(name).strip()
        for ch in ["\u200b", "\xa0", "\ufeff", "\u202f"]:
            name = name.replace(ch, "")
        return name.lower()

    def _first(self, src: Any, keys: Iterable[str], default=None):
        """
        Fetch first existing key from src (dict-like or pandas Series).
        Keys checked in order. Returns default if none found.
        """
        if src is None:
            return default
        # If pandas Series
        try:
            for k in keys:
                if isinstance(src, dict):
                    if k in src and src[k] not in [None, ""]:
                        return src[k]
                else:
                    # pandas Series or object with .get
                    try:
                        v = src.get(k)
                    except Exception:
                        v = getattr(src, k, None)
                    if v not in [None, ""]:
                        return v
        except Exception:
            pass
        return default

    def _as_float(self, val):
        if val is None:
            return None
        # if it's a numeric already
        try:
            return float(val)
        except Exception:
            pass
        # try to strip currency and parse
        try:
            s = str(val)
            # if it's JSON-like dict -> try to extract
            if ("{" in s and "}" in s) or (":" in s):
                try:
                    j = ast.literal_eval(s)
                    # typical keys
                    for k in ["price", "amount", "value"]:
                        if k in j:
                            return self._as_float(j[k])
                except Exception:
                    pass
            digits = "".join(c for c in s if (c.isdigit() or c in "."))
            if digits:
                return float(digits)
        except Exception:
            pass
        return None

    def _parse_coords(self, acc):
        """Return (lat, lon) trying several column names and a coordinates JSON if present."""
        lat_keys = ["latitude", "lat", "Latitude", "LAT", "geo_lat"]
        lon_keys = ["longitude", "lon", "lng", "Longitude", "LON", "geo_lon"]

        lat = self._first(acc, lat_keys)
        lon = self._first(acc, lon_keys)

        # If found and numeric, return
        latf = self._as_float(lat)
        lonf = self._as_float(lon)
        if latf is not None and lonf is not None:
            return latf, lonf

        # Try coordinates JSON-like field
        coord_raw = self._first(acc, ["coordinates", "coord", "location", "geo"], None)
        if coord_raw:
            try:
                if isinstance(coord_raw, str):
                    coord = ast.literal_eval(coord_raw)
                else:
                    coord = dict(coord_raw)
                # common keys in nested object
                for lk in ["latitude", "lat", "y"]:
                    for lk2 in ["longitude", "lon", "lng", "x"]:
                        if lk in coord and lk2 in coord:
                            lf = self._as_float(coord.get(lk))
                            lf2 = self._as_float(coord.get(lk2))
                            if lf is not None and lf2 is not None:
                                return lf, lf2
                # sometimes nested under 'geometry'->'location'
                if "geometry" in coord and "location" in coord["geometry"]:
                    loc = coord["geometry"]["location"]
                    return self._as_float(loc.get("lat")), self._as_float(loc.get("lng"))
            except Exception:
                pass

        return None, None

    # ---------------------------------------------------------
    # ground transport helper (kept from your original logic)
    # ---------------------------------------------------------
    def _make_ground_entry(self, org, dest):
        org_c = self._clean_city(org)
        dest_c = self._clean_city(dest)

        info = self.dm.get_distance(org_c, dest_c)

        if not info:
            return None

        try:
            dist = float(info.get("distance_km"))
            dur = float(info.get("duration_min"))
        except (TypeError, ValueError):
            return None

        # ✅ CRITICAL: reject NaN values
        if math.isnan(dist) or math.isnan(dur):
            return None

        dist = round(dist, 2)
        dur = round(dur, 2)

        drive_cost = round(dist * 0.05, 2)
        taxi_cost = round(dist * 1.0, 2)

        return [
            {
                "Description": f"Self-driving from {org_c} to {dest_c}",
                "Content": f"Duration: {dur} mins, Distance: {dist} km, Estimated Cost: ${drive_cost}"
            },
            {
                "Description": f"Taxi from {org_c} to {dest_c}",
                "Content": f"Duration: {dur} mins, Distance: {dist} km, Estimated Cost: ${taxi_cost}"
            }
        ]


    # ---------------------------------------------------------
    # MAIN BUILD
    # ---------------------------------------------------------
    def build(self, trip_json: Dict) -> Dict:
        origin_raw = trip_json.get("org")
        dest_raw = trip_json.get("dest")

        origin = self._clean_city(origin_raw)
        dest = self._clean_city(dest_raw)

        dates = trip_json.get("dates") or trip_json.get("date") or []
        if isinstance(dates, list) and dates:
            start_date = dates[0]
            end_date = dates[-1]
        else:
            start_date = trip_json.get("date") or None
            end_date = start_date

        ref: Dict[str, Any] = {}

        # -------------------------
        # 1) FLIGHTS
        # -------------------------
        direct_onward = self.filter.filter_flights(origin, dest, start_date)
        direct_return = self.filter.filter_flights(dest, origin, end_date)

        # connecting flights via SQL loader if supported
        if hasattr(self.dm.flights, "get_connecting_flights"):
            connecting_onward = self.dm.flights.get_connecting_flights(origin, dest, start_date)
            connecting_return = self.dm.flights.get_connecting_flights(dest, origin, end_date)
        else:
            connecting_onward = []
            connecting_return = []

        def top5_connect(flights):
            if not flights:
                return []
            df = pd.DataFrame(flights)
            if "Price" in df.columns:
                df = df.sort_values("Price")
            return df.head(5).to_dict(orient="records")

        # connecting_onward = top5_connect(connecting_onward)
        # connecting_return = top5_connect(connecting_return)
        connecting_onward = []
        connecting_return = []

        merged_onward = normalize_flights(direct_onward) + connecting_onward
        merged_return = normalize_flights(direct_return) + connecting_return

        ref["flights"] = {
            "onward": merged_onward[:20],
            "return": merged_return[:20]
        }

        # -------------------------
        # 2) Ground transport
        # -------------------------
        ref["ground_transportation"] = []
        out_ground = self._make_ground_entry(origin, dest)
        ret_ground = self._make_ground_entry(dest, origin)
        if out_ground:
            ref["ground_transportation"] += out_ground
        if ret_ground:
            ref["ground_transportation"] += ret_ground

                # -------------------------
        # 3) ACCOMMODATIONS (improved: min nights + reviews)
        # -------------------------
        raw_acc = self.filter.filter_accommodations(dest)
        cleaned_acc = []

        for acc in raw_acc:
            # support dicts and pandas Series/rows
            a = dict(acc) if not isinstance(acc, dict) else acc

            name = self._first(a, ["name", "Name", "NAME", "title"])
            room_type = self._first(a, ["roomType", "room_type", "room type", "room"])
            max_occ = self._first(a, ["max_occupancy", "maximum_occupancy", "maximum occupancy", "maxOcc"])
            house_rules = self._first(a, ["house_rules", "house rules", "houseRules"])

            # minimum nights: try several keys
            min_nights_raw = self._first(a, ["minimum_nights", "minimum nights", "min_nights", "min_night", "minimum_night"])
            try:
                minimum_nights = int(min_nights_raw) if min_nights_raw not in [None, ""] and float(min_nights_raw).is_integer() else float(min_nights_raw) if min_nights_raw not in [None, ""] else None
            except Exception:
                minimum_nights = None

            # coordinates
            lat, lon = self._parse_coords(a)

            # rating (could be numeric or nested JSON)
            raw_rating = self._first(a, ["rating", "review_rate_number", "review_rate", "rating_average"])
            rating = None
            try:
                if raw_rating is not None:
                    rating = self._as_float(raw_rating)
            except:
                rating = None

            # reviews count: try common keys
            raw_reviews = self._first(a, ["reviews", "review_count", "review_count_total", "reviewsCount", "num_reviews"])
            reviews = None
            try:
                if raw_reviews not in [None, ""]:
                    reviews = int(self._as_float(raw_reviews))
            except:
                reviews = None

            # pricing: try multiple keys; support numeric or JSON
            raw_price = self._first(a, ["price_per_night", "price", "Price", "cost", "amount"])
            price_val = self._as_float(raw_price)

            item: Dict[str, Any] = {
                "name": name,
                "roomType": room_type,
                "max_occupancy": int(max_occ) if max_occ not in [None, ""] and str(max_occ).isdigit() else (self._as_float(max_occ) if max_occ not in [None, ""] else None),
                "house_rules": house_rules,
                "minimum_nights": minimum_nights,
                "latitude": lat,
                "longitude": lon,
                "rating": rating,
                "reviews": reviews,
                "price_per_night": price_val,
                "price": price_val,
                "currency": self._first(a, ["currency", "Currency"]) or "USD"
            }

            cleaned_acc.append(item)

        ref["accommodations"] = cleaned_acc


        # -------------------------
        # 4) ATTRACTIONS
        # -------------------------
        attrs = self.filter.filter_attractions(dest)
        cleaned_attrs = []
        for a in attrs:
            aa = dict(a) if not isinstance(a, dict) else a
            name = self._first(aa, ["name", "Name", "TITLE"])
            subcats = self._first(aa, ["subcategories", "category", "categories", "type"]) or ""
            visit_d = self._first(aa, ["visit_duration", "duration", "avg_time"]) or None
            # coords/address/website
            lat, lon = self._parse_coords(aa)
            addr = self._first(aa, ["address", "Address", "addr"]) or None
            web = self._first(aa, ["website", "Website", "url"]) or None

            cleaned_attrs.append({
                "name": name,
                "subcategories": subcats,
                "visit_duration": self._as_float(visit_d) if visit_d not in [None, ""] else None,
                "address": addr,
                "latitude": lat,
                "longitude": lon,
                "website": web
            })

        ref["attractions"] = cleaned_attrs

        # -------------------------
        # 5) RESTAURANTS
        # -------------------------
        raw_rest = self.filter.filter_restaurants(dest)
        cleaned_rest = []
        for r in raw_rest:
            rr = dict(r) if not isinstance(r, dict) else r
            name = self._first(rr, ["name", "Name"])
            cuisines = self._first(rr, ["cuisines", "cuisine", "categories"]) or []
            if isinstance(cuisines, str):
                # try to parse list-like strings
                try:
                    cuisines = ast.literal_eval(cuisines)
                except Exception:
                    cuisines = [x.strip() for x in cuisines.split(",") if x.strip()]
            avg_cost = self._as_float(self._first(rr, ["avg_cost", "average_cost", "cost"]))
            rating = self._as_float(self._first(rr, ["rating", "avg_rating"]))

            cleaned_rest.append({
                "name": name,
                "cuisines": cuisines,
                "avg_cost": avg_cost,
                "rating": rating
            })

        ref["restaurants"] = cleaned_rest

        return ref
