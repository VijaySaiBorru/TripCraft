import json

plan = [
  {
    "day": 1,
    "current_city": "from Denver to Wichita",
    "transportation": "Flight from Denver to Wichita, Departure Time: 09:53, Arrival Time: 12:18",
    "breakfast": "-",
    "attraction": "Sedgwick County Zoo, Wichita;",
    "lunch": "Doo-Dah Diner, Wichita",
    "dinner": "Public, Wichita",
    "accommodation": "Cozy Spacious Wizard of Oz themed Tiny House, Wichita"
  },
  {
    "day": 2,
    "current_city": "Wichita",
    "transportation": "-",
    "breakfast": "HomeGrown Wichita, Wichita",
    "attraction": "Botanica, The Wichita Gardens, Wichita; Old Cowtown Museum, Wichita; Exploration Place, Wichita;",
    "lunch": "The Anchor, Wichita",
    "dinner": "Sabor Latin Bar & Grille, Wichita",
    "accommodation": "Cozy Spacious Wizard of Oz themed Tiny House, Wichita"
  },
  {
    "day": 3,
    "current_city": "from Wichita to Denver",
    "transportation": "Flight from Wichita to Denver, Departure Time: 17:04, Arrival Time: 17:44",
    "breakfast": "Egg Crate Cafe, Wichita",
    "attraction": "Museum of World Treasures, Wichita;",
    "lunch": "Newport Grill, Wichita",
    "dinner": "-",
    "accommodation": "-"
  }
]

query_data = {
    "days": 3,
    "org": "Denver",
    "dest": "Kansas",
    "visiting_city_number": 1,
    "level": "easy",
    "local_constraint": "{}",
    "budget": 5000,
    "people_number": 1
}

data = {
    "idx": 0,
    "JSON": query_data,
    "plan": plan
}

with open("sample_test.jsonl", "w") as f:
    f.write(json.dumps(data) + "\n")
