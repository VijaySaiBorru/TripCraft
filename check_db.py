import sqlite3
import re

DB = "/scratch/sg/Vijay/TripCraft/db/flights.db"

def parse_stored_duration(text):
    m = re.match(r"(\d+)\s*hours?\s*(\d+)\s*minutes?", text)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))

def compute_duration(dep, arr):
    dh, dm = map(int, dep.split(":"))
    ah, am = map(int, arr.split(":"))

    dep_min = dh * 60 + dm
    arr_min = ah * 60 + am

    return arr_min - dep_min if arr_min >= dep_min else (1440 - dep_min) + arr_min

conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("""
SELECT
  "Flight Number",
  DepTime,
  ArrTime,
  ActualElapsedTime
FROM flights
""")

bad = 0
total = 0

for fno, dep, arr, stored in cur.fetchall():
    total += 1
    stored_min = parse_stored_duration(stored)
    calc_min = compute_duration(dep, arr)

    if stored_min != calc_min:
        bad += 1
        print("❌ MISMATCH:", fno, dep, arr, stored, stored_min, calc_min)

print("\nTOTAL ROWS:", total)
print("MISMATCHES:", bad)

conn.close()
