# /scratch/sg/Vijay/TripCraft/check_csv.py
import csv
import json
import os
import sys

def build_accommodation_prompt(
    accommodation_ref,
    persona_json,
    localconstraints_json
) -> str:

    prompt_path = "/scratch/sg/Vijay/TripCraft/prompts/accommodation_prompt.txt"

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    prompt = (
        template
        .replace("{{ACCOMMODATION_REF}}", json.dumps(accommodation_ref, indent=2))
        .replace("{{PERSONA_JSON}}", json.dumps(persona_json, indent=2))
        .replace("{{LOCALCONSTRAINTS_JSON}}", json.dumps(localconstraints_json, indent=2))
    )

    return prompt.strip()


# --------------------------------------------------
# Transport Prompt Builder
# --------------------------------------------------

def build_transport_prompt(
    transport_ref,
    persona_json,
    localconstraints_json,
    allowed_modes,
    people_number,
    days,
    travel_days,
    transport_cap
) -> str:

    prompt_path = "/scratch/sg/Vijay/TripCraft/prompts/transport_prompt.txt"

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    prompt = (
        template
        .replace("{{TRANSPORT_REF_JSON}}", json.dumps(transport_ref, indent=2))
        .replace("{{PERSONA_JSON}}", json.dumps(persona_json, indent=2))
        .replace("{{LOCALCONSTRAINTS_JSON}}", json.dumps(localconstraints_json, indent=2))
        .replace("{{ALLOWED_MODES}}", ", ".join(allowed_modes))
        .replace("{{PEOPLE}}", str(people_number))
        .replace("{{DAYS}}", str(days))
        .replace("{{TRAVEL_DAYS}}", json.dumps(travel_days))
        .replace("{{TRANSPORT_CAPS_JSON}}", json.dumps(transport_cap, indent=2))
    )

    return prompt.strip()

# --------------------------------------------------
# Meals Prompt Builder
# --------------------------------------------------

def build_meals_prompt(
    restaurant_cards,
    persona_json,
    localconstraints_json,
    meals_cap
) -> str:

    prompt_path = "/scratch/sg/Vijay/TripCraft/prompts/meals_prompt.txt"

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    prompt = (
        template
        .replace("{{RESTAURANT_CARDS_JSON}}", json.dumps(restaurant_cards, indent=2, ensure_ascii=False))
        .replace("{{PERSONA_JSON}}", json.dumps(persona_json, indent=2, ensure_ascii=False))
        .replace("{{LOCAL_CONSTRAINTS_JSON}}", json.dumps(localconstraints_json, indent=2, ensure_ascii=False))
        .replace("{{MEALS_CAP}}", str(meals_cap))
    )

    return prompt.strip()

# --------------------------------------------------
# Attraction Prompt Builder (NO TRANSFORMATION)
# --------------------------------------------------

def build_attraction_prompt(
    attraction_ref,
    persona_json,
    localconstraints_json
) -> str:

    prompt_path = "/scratch/sg/Vijay/TripCraft/prompts/attraction_prompt.txt"

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    prompt = (
        template
        .replace(
            "{{ATTRACTIONS_JSON}}",
            json.dumps(attraction_ref, indent=2, ensure_ascii=False)
        )
        .replace(
            "{{PERSONA_JSON}}",
            json.dumps(persona_json, indent=2, ensure_ascii=False)
        )
        .replace(
            "{{LOCAL_CONSTRAINTS_JSON}}",
            json.dumps(localconstraints_json, indent=2, ensure_ascii=False)
        )
    )

    return prompt.strip()

def build_events_prompt(
    events,
    persona_json,
    localconstraints_json
) -> str:

    prompt_path = "/scratch/sg/Vijay/TripCraft/prompts/events_prompt.txt"

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    prompt = (
        template
        .replace("{{EVENT_CARDS_JSON}}",
                 json.dumps(events, indent=2, ensure_ascii=False))
        .replace("{{PERSONA_JSON}}",
                 json.dumps(persona_json, indent=2, ensure_ascii=False))
        .replace("{{LOCAL_CONSTRAINTS_JSON}}",
                 json.dumps(localconstraints_json, indent=2, ensure_ascii=False))
    )

    return prompt.strip()


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    if len(sys.argv) != 3:
        print("Usage: python check_csv.py <3|5|7> <row_index (1-based)>")
        sys.exit(1)

    day_type = sys.argv[1]
    row_index = int(sys.argv[2])  # 1-based indexing

    csv_path = f"/scratch/sg/Vijay/TripCraft/tripcraft_{day_type}day_inputs.csv"
    out_dir = "/scratch/sg/Vijay/TripCraft/debug_prompts"
    os.makedirs(out_dir, exist_ok=True)

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if row_index < 1 or row_index > len(rows):
        raise IndexError(f"Row index {row_index} out of range")

    row = rows[row_index - 1]

    # --------------------------------------------------
    # Read core fields from CSV (NO recomputation)
    # --------------------------------------------------

    visiting_city_number = int(row["visiting_city_number"])
    days = int(row["days"])
    travel_days = json.loads(row["travel_dates"])

    persona_json = json.loads(row["persona_json"])
    localconstraints_json = json.loads(row["localconstraints_json"])
    transport_ref = json.loads(row["transport_ref"])
    people_number = int(row["people_number"])
    meals_cap = row.get("meals_cap")

    transport_cap = {
        "transport_cap": row.get("transport_cap")
    }

    allowed_modes_raw = row.get("allowed_modes", "").strip()
    allowed_modes = (
        json.loads(allowed_modes_raw)
        if allowed_modes_raw
        else ["flight", "taxi", "self-driving"]
    )

    # --------------------------------------------------
    # Accommodation prompts (PER CITY)
    # --------------------------------------------------

    for city_idx in range(1, visiting_city_number + 1):
        col_name = f"accommodation_city_{city_idx}"

        if not row.get(col_name):
            print(f"⚠️ Missing {col_name}, skipping")
            continue

        accommodation_ref = json.loads(row[col_name])

        acc_prompt = build_accommodation_prompt(
            accommodation_ref=accommodation_ref,
            persona_json=persona_json,
            localconstraints_json=localconstraints_json
        )

        acc_out_path = os.path.join(
            out_dir,
            f"accommodation_row_{row_index}_city_{city_idx}.txt"
        )

        with open(acc_out_path, "w", encoding="utf-8") as f:
            f.write(acc_prompt)

        print(f"✅ Written: {acc_out_path}")

    # --------------------------------------------------
    # Transport prompt (ONCE PER TRIP)
    # --------------------------------------------------

    transport_prompt = build_transport_prompt(
        transport_ref=transport_ref,
        persona_json=persona_json,
        localconstraints_json=localconstraints_json,
        allowed_modes=allowed_modes,
        people_number=people_number,
        days=days,
        travel_days=travel_days,
        transport_cap=transport_cap
    )

    transport_out_path = os.path.join(
        out_dir,
        f"transport_row_{row_index}.txt"
    )

    with open(transport_out_path, "w", encoding="utf-8") as f:
        f.write(transport_prompt)

    print(f"✅ Written: {transport_out_path}")
    # --------------------------------------------------
    # Meals prompts (PER CITY)
    # --------------------------------------------------

    for city_idx in range(1, visiting_city_number + 1):
        col_name = f"restaurants_city_{city_idx}"

        if not row.get(col_name):
            print(f"⚠️ Missing {col_name}, skipping meals")
            continue

        restaurant_cards = json.loads(row[col_name])

        meals_prompt = build_meals_prompt(
            restaurant_cards=restaurant_cards,
            persona_json=persona_json,
            localconstraints_json=localconstraints_json,
            meals_cap=meals_cap
        )

        meals_out_path = os.path.join(
            out_dir,
            f"meals_row_{row_index}_city_{city_idx}.txt"
        )

        with open(meals_out_path, "w", encoding="utf-8") as f:
            f.write(meals_prompt)

        print(f"✅ Written: {meals_out_path}")
        # --------------------------------------------------
        # Attractions prompts (PER CITY)
        # --------------------------------------------------

        for city_idx in range(1, visiting_city_number + 1):
            col_name = f"attractions_city_{city_idx}"

            if not row.get(col_name):
                print(f"⚠️ Missing {col_name}, skipping attractions")
                continue

            attraction_ref = json.loads(row[col_name])

            attraction_prompt = build_attraction_prompt(
                attraction_ref=attraction_ref,
                persona_json=persona_json,
                localconstraints_json=localconstraints_json
            )

            attraction_out_path = os.path.join(
                out_dir,
                f"attractions_row_{row_index}_city_{city_idx}.txt"
            )

            with open(attraction_out_path, "w", encoding="utf-8") as f:
                f.write(attraction_prompt)

            print(f"✅ Written: {attraction_out_path}")
            # --------------------------------------------------
            # Events prompts (PER CITY)
            # --------------------------------------------------

            for city_idx in range(1, visiting_city_number + 1):
                col_name = f"events_city_{city_idx}"

                if not row.get(col_name):
                    print(f"⚠️ Missing {col_name}, skipping events")
                    continue

                events = json.loads(row[col_name])

                events_prompt = build_events_prompt(
                    events=events,
                    persona_json=persona_json,
                    localconstraints_json=localconstraints_json
                )

                events_out_path = os.path.join(
                    out_dir,
                    f"events_row_{row_index}_city_{city_idx}.txt"
                )

                with open(events_out_path, "w", encoding="utf-8") as f:
                    f.write(events_prompt)

                print(f"✅ Written: {events_out_path}")





if __name__ == "__main__":
    main()
