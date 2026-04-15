import csv
import os
import json
from flask import Flask, render_template_string, request, redirect

csv.field_size_limit(10**9)

app = Flask(__name__)

FILE_PATH = "/scratch/sg/Vijay/TripCraft/TripCraft_database/reviews/pend_attraction.csv"

RESULT_COL = 5


# ===============================
# Clean Smart Quotes (IMPORTANT)
# ===============================
def clean_text(text):
    replacements = {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "—": "-",
        "–": "-",
        "…": "...",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text


def load_data():
    with open(FILE_PATH, newline="", encoding="utf-8", errors="ignore") as f:
        return list(csv.reader(f))


def save_data(data):
    with open(FILE_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerows(data)


def ensure_result_column(row):
    if len(row) <= RESULT_COL:
        row += [""] * (RESULT_COL + 1 - len(row))
    return row


def find_first_unprocessed(rows):
    for i, row in enumerate(rows):
        row = ensure_result_column(row)
        if row[RESULT_COL].strip() == "":
            return i
    return None


HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
    <title>Attraction Review Entry</title>
    <script>
        function addReviewRow() {
            let table = document.getElementById("reviewTable");
            let row = table.insertRow(-1);

            let cell1 = row.insertCell(0);
            let cell2 = row.insertCell(1);

            cell1.innerHTML = '<input type="text" name="title" style="width:400px;">';
            cell2.innerHTML = '<textarea name="comment" rows="4" cols="60"></textarea>';
        }
    </script>
</head>
<body>

<h2>{{ attraction[0] }}</h2>
<p><b>City:</b> {{ attraction[2] }}</p>
<p><b>State:</b> {{ attraction[1] }}</p>
<p><a href="{{ attraction[4] }}" target="_blank">Open TripAdvisor Page</a></p>

<hr>
<p><b>Existing Reviews (Saved JSON):</b></p>
<pre style="background:#f5f5f5; padding:10px; max-height:200px; overflow:auto;">
{{ existing_reviews }}
</pre>
<hr>

<form method="post">
    <input type="hidden" name="row_index" value="{{ row_index }}">

    <table border="1" id="reviewTable">
        <tr>
            <th>Title</th>
            <th>Comment</th>
        </tr>
        <tr>
            <td><input type="text" name="title" style="width:400px;"></td>
            <td><textarea name="comment" rows="4" cols="60"></textarea></td>
        </tr>
    </table>

    <br>
    <button type="button" onclick="addReviewRow()">➕ Add Another Review</button>
    <br><br>

    <button type="submit" name="action" value="save_next">Save & Next</button>
    <button type="submit" name="action" value="next">Next</button>
    <button type="submit" name="action" value="prev">Previous</button>
    <button type="submit" name="action" value="skip">No Reviews Found</button>
</form>

<br>
<p>Attraction {{ row_index + 1 }} / {{ total }}</p>

</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():

    if not os.path.exists(FILE_PATH):
        return "CSV file not found."

    data = load_data()
    header = data[0]
    rows = data[1:]

    for i in range(len(rows)):
        rows[i] = ensure_result_column(rows[i])
        data[i + 1] = rows[i]

    row_index = request.args.get("row")

    if row_index is not None:
        row_index = int(row_index)
    else:
        row_index = 0

    if request.method == "POST":
        row_index = int(request.form["row_index"])
        action = request.form["action"]

        titles = request.form.getlist("title")
        comments = request.form.getlist("comment")

        reviews = []

        for t, c in zip(titles, comments):
            t = clean_text(t.strip())
            c = clean_text(c.strip())

            if t or c:
                reviews.append({
                    "Title": t,
                    "Comment": c
                })

        if action == "save_next":
            data[row_index + 1][RESULT_COL] = json.dumps(reviews, ensure_ascii=False)
            save_data(data)

        elif action == ["next", "skip"]:
            # Do nothing, just move forward
            pass

        elif action == "prev":
            pass

        if action == "prev":
            row_index = max(0, row_index - 1)
        else:
            row_index = min(len(rows) - 1, row_index + 1)

        return redirect(f"/?row={row_index}")

    attraction = rows[row_index]
    existing_reviews = rows[row_index][RESULT_COL]

    return render_template_string(
        HTML_TEMPLATE,
        attraction=attraction,
        row_index=row_index,
        total=len(rows),
        existing_reviews=existing_reviews
    )


if __name__ == "__main__":
    app.run(debug=False)