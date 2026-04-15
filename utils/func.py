import json
import re
import gradio as gr
import os

# -------------------------
# JSONL helpers
# -------------------------

def load_line_json_data(filename):
    data = []
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data.append(json.loads(line))
    return data


def save_file(data, path):
    with open(path, 'w', encoding='utf-8') as w:
        for unit in data:
            w.write(json.dumps(unit) + "\n")


# -------------------------
# Query helpers
# -------------------------

def extract_query_number(query_string):
    pattern = r"Query (\d+)"
    match = re.search(pattern, query_string)
    return int(match.group(1)) if match else None


# -------------------------
# Display helpers (Gradio)
# -------------------------

def create_data_display(css_content, data, annotation_idx):
    item = data[annotation_idx - 1]
    return f"""
    <style>{css_content}</style>
    <div>
        <span class="query-highlighted"><strong>Query {annotation_idx}:</strong> {item['query']}</span><br>
        <span class="highlighted"><strong>Day:</strong> {item['days']}</span>
        <span class="highlighted"><strong>Visiting City Number:</strong> {item['visiting_city_number']}</span>
        <span class="highlighted"><strong>Date:</strong> {item['date']}</span>
        <span class="highlighted"><strong>Departure:</strong> {item['org']}</span>
        <span class="highlighted"><strong>Destination:</strong> {item['dest']}</span><br>
        <span class="highlighted-alt"><strong>People Number:</strong> {item['people_number']}</span>
        <span class="highlighted-alt"><strong>Budget:</strong> {item['budget']}</span>
        <span class="highlighted-alt"><strong>Hotel Rule:</strong> {item['local_constraint']['house rule']}</span>
        <span class="highlighted-alt"><strong>Cuisine:</strong> {item['local_constraint']['cuisine']}</span>
        <span class="highlighted-alt"><strong>Room Type:</strong> {item['local_constraint']['room type']}</span>
        <span class="highlighted-alt"><strong>Transportation:</strong> {item['local_constraint']['transportation']}</span>
    </div>
    """


# -------------------------
# Validation helpers
# -------------------------

def judge_valid_info(info):
    return bool(info and info != "You don't need to fill in the information for this or later days.")


def judge_submit_info(info, current_day, label, annotation_data, *tested_data):
    if not info:
        raise gr.Error(f"Day {current_day} {label} is empty!")

    if info != "-":
        if label == "transportation":
            if not judge_valid_transportation(info, annotation_data):
                raise gr.Error(f"Day {current_day} transportation is invalid.")
        elif label == "accommodation":
            if not judge_valid_room_type(info, annotation_data, tested_data[0]):
                raise gr.Error(f"Day {current_day} room type invalid.")
            if not judge_valid_room_rule(info, annotation_data, tested_data[0]):
                raise gr.Error(f"Day {current_day} house rule invalid.")

    return True


def judge_valid_transportation(info, annotation_data):
    rule = annotation_data['local_constraint']['transportation']
    if rule == 'no flight' and 'Flight' in info:
        return False
    if rule == 'no self-driving' and 'Self-driving' in info:
        return False
    return True


def judge_valid_room_type(info, annotation_data, accommodation_data_all):
    data = get_filtered_data(info, accommodation_data_all)
    if data.empty:
        return False

    room_type = annotation_data['local_constraint']['room type']
    actual = data['room type'].values[0]

    if room_type == 'not shared room' and actual == 'Shared room':
        return False
    if room_type == 'shared room' and actual != 'Shared room':
        return False
    if room_type == 'private room' and actual != 'Private room':
        return False
    if room_type == 'entire room' and actual != 'Entire home/apt':
        return False

    return True


def judge_valid_room_rule(info, annotation_data, accommodation_data_all):
    data = get_filtered_data(info, accommodation_data_all)
    if data.empty:
        return False

    rules = str(data['house_rules'].values[0])
    rule = annotation_data['local_constraint']['house rule']

    if rule == 'smoking' and 'No smoking' in rules:
        return False
    if rule == 'parties' and 'No parties' in rules:
        return False
    if rule == 'children under 10' and 'No children under 10' in rules:
        return False
    if rule == 'visitors' and 'No visitors' in rules:
        return False
    if rule == 'pets' and 'No pets' in rules:
        return False

    return True


def judge_valid_cuisine(info, annotation_data, restaurant_data_all, cuisine_set: set):
    if info != "-" and annotation_data['local_constraint']['cuisine'] and annotation_data['org'] not in info:
        data = get_filtered_data(info, restaurant_data_all, ('Name', 'City'))
        if not data.empty:
            for cuisine in annotation_data['local_constraint']['cuisine']:
                if cuisine in data.iloc[0]['Cuisines']:
                    cuisine_set.add(cuisine)
    return cuisine_set


# -------------------------
# Parsing helpers
# -------------------------

def get_valid_name_city(info):
    parts = info.rsplit(',', 1)
    if len(parts) == 2:
        name = parts[0].strip()
        city = extract_before_parenthesis(parts[1].strip())
        return name, city.strip()
    return "-", "-"


def extract_numbers_from_filenames(directory):
    pattern = r'annotation_(\d+).json'
    return [
        int(re.search(pattern, f).group(1))
        for f in os.listdir(directory)
        if re.match(pattern, f)
    ]


def get_filtered_data(component, data, column_name=('NAME', 'city')):
    name, city = get_valid_name_city(component)
    return data[(data[column_name[0]] == name) & (data[column_name[1]] == city)]


def extract_before_parenthesis(s):
    match = re.search(r'^(.*?)\([^)]*\)', s)
    return match.group(1) if match else s


def count_consecutive_values(lst):
    if not lst:
        return []
    result = []
    current = lst[0]
    count = 1
    for item in lst[1:]:
        if item == current:
            count += 1
        else:
            result.append((current, count))
            current = item
            count = 1
    result.append((current, count))
    return result
