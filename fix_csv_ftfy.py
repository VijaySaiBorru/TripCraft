import csv
import sys
import os
from ftfy import fix_text

file_path = sys.argv[1]
temp_file = file_path + ".tmp"

with open(file_path, newline="", encoding="utf-8") as infile, \
     open(temp_file, "w", newline="", encoding="utf-8") as outfile:

    reader = csv.DictReader(infile)
    writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)

    writer.writeheader()

    for row in reader:
        new_row = {
            k: fix_text(v) if isinstance(v, str) else v
            for k, v in row.items()
        }
        writer.writerow(new_row)

os.replace(temp_file, file_path)

print(f"✅ Cleaned and overwritten: {file_path}")