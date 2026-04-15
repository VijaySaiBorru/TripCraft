import csv

input_file = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/pending_attractions_manual.csv"
output_file = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/pending_attractions_manual_with_rating.csv"

rows_per_attraction = 15

with open(input_file, newline="", encoding="cp1252") as f:
    reader = list(csv.reader(f))
    header = reader[0]
    data = reader[1:]

# New header with Rating
new_header = header[:5] + ["Rating"] + header[5:]

new_rows = []

for i, row in enumerate(data):
    block_position = i % rows_per_attraction

    if block_position < 5:
        rating = 5
    elif block_position < 10:
        rating = 3
    else:
        rating = 1

    new_row = row[:5] + [rating] + row[5:]
    new_rows.append(new_row)

with open(output_file, "w", newline="", encoding="cp1252") as out:
    writer = csv.writer(out)
    writer.writerow(new_header)
    writer.writerows(new_rows)

print("✅ Rating column added successfully.")
print("Output file:", output_file)