import csv
import json
import sys


# -----------------------------
# NEW CITY EXTRACTION (CORRECT)
# -----------------------------

def extract_cities_from_refs(row, city_count):
    cities = []

    for i in range(1, city_count + 1):
        key = f"reference_information_{i}"
        ref = row.get(key)

        if not ref:
            cities.append("")
            continue

        try:
            data = json.loads(ref)

            if isinstance(data, list) and len(data) > 0:
                desc = data[0].get("Description", "")

                if " in " in desc:
                    city = desc.split(" in ")[-1].strip()
                    cities.append(city)
                else:
                    cities.append("")
            else:
                cities.append("")

        except:
            cities.append("")

    return cities


# -----------------------------
# MAIN CHECK SCRIPT
# -----------------------------

def main():

    if len(sys.argv) != 2:
        print("Usage: python check.py <3|5|7>")
        return

    day_type = int(sys.argv[1])
    city_count = {3: 1, 5: 2, 7: 3}[day_type]

    input_csv = f"/scratch/sg/Vijay/TripCraft/tripcraft_{day_type}day.csv"

    with open(input_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    invalid_rows = 0

    for idx, row in enumerate(rows):

        cities = extract_cities_from_refs(row, city_count)

        # remove empty
        valid_cities = [c for c in cities if c and c.strip()]

        # DEBUG (your problematic rows)
        if idx in [47, 171, 172, 301, 328]:
            print("\n==== DEBUG ROW ====")
            print("Cities Extracted:", cities)

        if len(valid_cities) < city_count:
            print(f"❌ Row {idx} INVALID -> {cities}")
            invalid_rows += 1

    print("\n-----------------------------")
    print(f"Total rows: {len(rows)}")
    print(f"Invalid rows: {invalid_rows}")
    print("-----------------------------")


if __name__ == "__main__":
    main()