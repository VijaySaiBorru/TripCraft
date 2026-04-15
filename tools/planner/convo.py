import csv
import json
from core.llm_backend import init_llm

CSV_PATH = "/scratch/sg/Vijay/TripCraft/tripcraft_3day_inputs.csv"


# ---------------------------------------------------------
# Pretty printing helpers
# ---------------------------------------------------------
def print_message(speaker, message):
    print("\n" + "=" * 90)
    print(f"{speaker.upper()}")
    print("-" * 90)
    print(message.strip())
    print("=" * 90)


# ---------------------------------------------------------
# Shared conversation state
# ---------------------------------------------------------
class ConversationState:
    def __init__(self):
        self.messages = []

    def speak(self, speaker, message):
        self.messages.append({"speaker": speaker, "message": message})

    def transcript(self):
        return "\n".join(
            f"{m['speaker']}: {m['message']}" for m in self.messages
        )


# ---------------------------------------------------------
# Base conversational agent
# ---------------------------------------------------------
class ConversationalAgent:
    def __init__(self, name, llm):
        self.name = name
        self.llm = llm

    def respond(self, prompt):
        return self.llm.generate(prompt)


# ---------------------------------------------------------
# Domain agents (ONLY DISCUSSION)
# ---------------------------------------------------------
class AccommodationAgent(ConversationalAgent):
    def talk(self, trip, state):
        prompt = f"""
You are an accommodation expert.

Options:
{trip['accommodation_city_1']}

Persona:
{trip['persona']}

Argue for ONE realistic accommodation choice.
"""
        r = self.respond(prompt)
        state.speak(self.name, r)
        print_message(self.name, r)


class TransportAgent(ConversationalAgent):
    def talk(self, trip, state):
        prompt = f"""
You are a transport planner.

Transport options:
{trip['transport_response']}

Dates:
{trip['date']}

Argue about realistic travel timing and constraints.
"""
        r = self.respond(prompt)
        state.speak(self.name, r)
        print_message(self.name, r)


class AttractionsAgent(ConversationalAgent):
    def talk(self, trip, state):
        prompt = f"""
You are a sightseeing planner.

Attractions:
{trip['attractions_city_1']}

Trip length: {trip['days']} days

Argue for a feasible daily attraction load.
"""
        r = self.respond(prompt)
        state.speak(self.name, r)
        print_message(self.name, r)


class MealsAgent(ConversationalAgent):
    def talk(self, trip, state):
        prompt = f"""
You are a meals strategy expert.

Restaurants:
{trip['restaurants_city_1']}

Budget: {trip['budget']}
Persona: {trip['persona']}

Conversation so far:
{state.transcript()}

Argue about meal pacing (light vs heavy days).
Do NOT list restaurants.
"""
        r = self.respond(prompt)
        state.speak(self.name, r)
        print_message(self.name, r)


class BudgetAgent(ConversationalAgent):
    def talk(self, trip, state):
        prompt = f"""
You are a strict budget guardian.

Budget: {trip['budget']}

Conversation so far:
{state.transcript()}

Flag luxury creep or overcommitment.
"""
        r = self.respond(prompt)
        state.speak(self.name, r)
        print_message(self.name, r)


# ---------------------------------------------------------
# Master agent (CONSTRUCTS FINAL ITINERARY)
# ---------------------------------------------------------
class MasterAgent(ConversationalAgent):
    def decide(self, trip, state):
        prompt = f"""
You are the master travel planner.

Conversation transcript:
{state.transcript()}

Using the discussion above, GENERATE a FINAL ITINERARY.

Rules:
- Be realistic with travel time
- Meals should match travel intensity
- Attractions should fit the day length
- Follow a SINGLE accommodation choice
- Use "-" if something is not applicable

Return STRICT JSON ONLY in this schema:

{{
  "days": [
    {{
      "day": 1,
      "current_city": "...",
      "transportation": "...",
      "breakfast": "...",
      "lunch": "...",
      "dinner": "...",
      "attraction": "...",
      "accommodation": "...",
      "event": "...",
      "point_of_interest_list": "..."
    }}
  ]
}}
"""
        r = self.respond(prompt)
        state.speak(self.name, r)
        print_message(self.name, r)
        return json.loads(r)


# ---------------------------------------------------------
# Load trip
# ---------------------------------------------------------
def load_trip():
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        return next(reader)


# ---------------------------------------------------------
# Run conversation
# ---------------------------------------------------------
def run_conversation():
    trip = load_trip()

    llm = init_llm(
        model_name="qwen2.5",
        api_key=None
    )

    state = ConversationState()

    agents = [
        AccommodationAgent("AccommodationAgent", llm),
        TransportAgent("TransportAgent", llm),
        AttractionsAgent("AttractionsAgent", llm),
        MealsAgent("MealsAgent", llm),
        BudgetAgent("BudgetAgent", llm),
    ]

    print("\n################ STARTING CONVERSATION ################")

    for agent in agents:
        agent.talk(trip, state)

    print("\n################ FULL TRANSCRIPT ################\n")
    print(state.transcript())

    master = MasterAgent("MasterAgent", llm)
    final_plan = master.decide(trip, state)

    return final_plan


# ---------------------------------------------------------
# Entry point
# ---------------------------------------------------------
if __name__ == "__main__":
    output = run_conversation()
    print("\n################ FINAL DAY-WISE PLAN ################\n")
    print(json.dumps(output, indent=2))
