# TripCraft Agentic Planner - Comprehensive Documentation

## 1. Introduction
TripCraft is an advanced multi-agent system designed to generate detailed, personalized travel itineraries. It uses a suite of specialized agents to handle different aspects of a trip (transport, accommodation, meals, attractions) and orchestrates them to create a coherent schedule that respects user preferences (persona), budget, and logistical constraints.

---

## 2. Architecture & Agents

The system is built around a central **Orchestrator** (`AgenticPlanner`) that coordinates **6 specialized Sub-Agents** and **1 Rule-Based Builder**.

### The 6 Sub-Agents
Each agent is responsible for a specific domain and uses an LLM (Large Language Model) to make decisions based on data.

1.  **AccommodationAgent** (`agentic_trip/agents/accommodationagent.py`)
    *   **Role**: Selects the best hotel/accommodation.
    *   **Logic**: Filters options from CSV by city/price. Prompts LLM to match "Persona". Handles upgrades if budget permits.
    *   **Output**: Selected hotel object.

2.  **TransportAgent** (`agentic_trip/agents/transportagent.py`)
    *   **Role**: Determines inter-city travel.
    *   **Logic**: Queries `flights.db` and Distance Matrix. Chooses Flight/Taxi/Self-Driving based on time/cost/distance.
    *   **Output**: Transport "legs" with timings.

3.  **MealsAgent** (`agentic_trip/agents/mealsagent.py`)
    *   **Role**: Selects curated restaurants.
    *   **Logic**: Ranks restaurants by persona. Selects a set fitting the `meals_cap` (budget).
    *   **Output**: Ranked list of restaurants.

4.  **AttractionAgent** (`agentic_trip/agents/attractionagent.py`)
    *   **Role**: Selects points of interest (POIs).
    *   **Logic**: Ranks attractions by user interest categories (History, Nature, etc.). Enforces minimum counts.
    *   **Output**: Ranked list of attractions.

5.  **EventAgent** (`agentic_trip/agents/eventsagent.py`)
    *   **Role**: Finds date-specific events.
    *   **Logic**: Selects events occurring exactly during trip dates. Matches persona.
    *   **Output**: Date-mapped events.

6.  **FinalScheduleAgent** (`agentic_trip/agents/finalscheduleagent.py`)
    *   **Role**: The "LLM Compiler".
    *   **Logic**:
        *   Builds a **Skeleton** (fixed transport/hotels).
        *   LLM fills meals/attractions into valid slots.
        *   **Validation**: Checks constraints (e.g., correct city). Triggers "Repair Loop" on failure.

### The 1 Builder
*   **FinalScheduleBuilder** (`agentic_trip/final_schedule_builder_dur.py`)
    *   **Role**: The "Deterministic Compiler" (Fallback).
    *   **Logic**: Uses strict Python rules (not LLM) to place items. Calculates exact windows (Breakfast 8-10am) and buffers.

---

## 3. Execution Flow

The entry point is `run.py`.

1.  **Initialization**: `run.py` checks GPU memory and sets environment variables.
2.  **Batch Driver**: `tools/planner/agentic_planning.py` loads the dataset (`tripcraft_3day.csv`) and initializes `AgenticPlanner`.
3.  **Planning Loop** (`AgenticPlanner.run_full_pipeline`):
    *   **Step 1**: `AccommodationAgent` runs first (highest priority).
    *   **Step 2**: `TransportAgent` runs (calculates remaining budget).
    *   **Step 3**: `MealsAgent`, `AttractionAgent`, `EventAgent` run to gather options.
    *   **Step 4**: `AccommodationAgent` runs *again* for potential upgrades.
    *   **Step 5**: `FinalScheduleAgent` (or `Builder`) synthesizes the final itinerary.
4.  **Output**: Results saved to `output_agentic/`.

---

## 4. Output Directory Structure

Outputs are organized hierarchically:

```text
output_agentic/
└── agentic/
    └── <model_name>/         # e.g., gemini-2.5-flash
        └── <duration>/       # e.g., 3day
            └── <id>/         # Trip ID
                ├── tripcraft_response.json       # ✅ Final Output
                ├── llm_tripcraft_response.json   # Raw LLM output
                ├── combined_reference.json       # All generic choices
                ├── trip_json_used.json           # Input request
                └── reference.json                # Raw DB extracts
```

---

## 5. Evaluation

Two main scripts verify plan quality.

### A. Quantitative (Constraints) - `eval.py`
Checks "Commonsense" (e.g., distinct restaurants) and "Hard" rules (e.g., budget).

```bash
cd evaluation
python eval.py --set_type 3d --evaluation_file_path <path_to_jsonl>
```

### B. Qualitative (Scores) - `qualitative_metrics.py`
Calculates quality scores:
*   **Temporal**: Logical meal times.
*   **Spatial**: Geographic coherence.
*   **Ordering**: Logical sequence (Hotel -> Breakfast -> Attraction).
*   **Persona**: Alignment with user interests.

```bash
cd evaluation
python qualitative_metrics.py --gen_file <generated_file> --anno_file tripcraft_golden_3day.jsonl
```

---

## 6. Expected Output Format (JSON)

The key output file `tripcraft_response.json` must follow this structure for evaluation scripts to work.

### Root Object
```json
{
  "days": [ ... ],             // List of day objects
  "budget_used": 1234.5,       // Total cost
  "budget_remaining": 500.0,   // Unused budget
  "budget_ok": true            // Boolean flag
}
```

### Day Object Fields
*   `transportation`: Description of travel (or "-").
*   `point_of_interest_list`: **CRITICAL**. Semi-structured string parsed by regex.
    *   **Format**: `Name, action from HH:MM to HH:MM, nearest transit: STOP, DIST m away`
    *   **Keywords**: "visit from", "stay from", "nearest transit".

### Example 1: 3-Day Trip (Savannah ↔ Baltimore)
*   **Mode**: Flight
*   **Model**: Gemini 2.5 Flash

```json
{
  "days": [
    {
      "day": 1,
      "current_city": "from Savannah to Baltimore",
      "transportation": "Flight Number: F2644210, from Savannah to Baltimore, Departure Time: 07:02, Arrival Time: 08:33",
      "breakfast": "-",
      "lunch": "Tagliata, Baltimore",
      "dinner": "Restaurante Tio Pepe, Baltimore",
      "attraction": "Fort McHenry National Monument And Historic Shrine, Baltimore;",
      "accommodation": "Private Queen Suite (B) Fells and Hopkins Medical, Baltimore",
      "point_of_interest_list": "Private Queen Suite (B) Fells and Hopkins Medical, stay from 09:03 to 09:33; Fort McHenry National Monument And Historic Shrine, visit from 10:03 to 13:48, nearest transit: SHOT TOWER STATION (METRO) sb, 3547.78m away; Tagliata, visit from 14:40 to 15:40, nearest transit: SHOT TOWER STATION (METRO) sb, 767.14m away; Restaurante Tio Pepe, visit from 20:45 to 22:00, nearest transit: LEXINGTON MARKET METRO North Entrance, 554.3m away; Private Queen Suite (B) Fells and Hopkins Medical, stay from 22:00 to 08:00"
    },
    {
      "day": 2,
      "current_city": "Baltimore",
      "transportation": "-",
      "point_of_interest_list": "Private Queen Suite (B) Fells and Hopkins Medical, stay from 08:00 to 08:30; Fogo de Chao Brazilian Steakhouse, visit from 09:00 to 09:50..."
    },
    {
       "day": 3,
       "current_city": "from Baltimore to Savannah",
       "transportation": "Flight Number: F1614796...",
       "point_of_interest_list": "Private Queen Suite (B) Fells and Hopkins Medical, stay from 07:30 to 08:00"
    }
  ],
  "budget_used": 696.0,
  "budget_ok": true
}
```

### Example 2: 5-Day Trip (Santa Fe ↔ Durango ↔ Colorado Springs)
*   **Mode**: Self-Driving
*   **Model**: Qwen 2.5

```json
{
  "days": [
    {
      "day": 1,
      "current_city": "from Santa Fe to Durango",
      "transportation": "Self-Driving from Santa Fe to Durango, Duration: 284 mins, Departure Time: 06:00, Arrival Time: 10:44",
      "attraction": "Mountain Waters Rafting & Adventure Company, Durango;",
      "point_of_interest_list": "Private Bedroom and Bath - Walk Downtown!, stay from 11:14 to 11:44; 81301 Coffee House and Roasters, visit from 14:40 to 15:40..."
    },
    {
      "day": 3,
      "current_city": "from Durango to Colorado Springs",
      "transportation": "Self-Driving from Durango to Colorado Springs, Duration: 394 mins, Departure Time: 06:00, Arrival Time: 12:34",
      "accommodation": "Cozy Colo Springs Home near transportation routes, Colorado Springs",
      "point_of_interest_list": "Cozy Colo Springs Home near transportation routes, stay from 13:04 to 13:34; Urban Egg A Daytime Eatery, visit from 14:40 to 15:40..."
    },
    {
      "day": 5,
      "current_city": "from Colorado Springs to Santa Fe",
      "transportation": "Self-Driving from Colorado Springs to Santa Fe, Duration: 336 mins, Departure Time: 16:00",
      "point_of_interest_list": "Cozy Colo Springs Home near transportation routes, stay from 08:00 to 08:30..."
    }
  ],
  "budget_used": 708.91,
  "budget_ok": true
}
```

### Example 3: 7-Day Trip (Champaign ↔ Houston ↔ Amarillo ↔ San Antonio)
*   **Mode**: Taxi
*   **Model**: Phi 4

```json
{
  "days": [
    {
      "day": 1,
      "current_city": "from Champaign to Houston",
      "transportation": "Taxi from Champaign to Houston, Duration: 1031 mins, Arrival Time: 19:30",
      "point_of_interest_list": "J-Modern Room nearDowntown\\Airport, stay from 20:00 to 20:30..."
    },
    {
      "day": 3,
      "current_city": "from Houston to Amarillo",
      "transportation": "Taxi from Houston to Amarillo, Duration: 649 mins...",
      "accommodation": "Side Street Private Guesthouse, Amarillo",
      "point_of_interest_list": "J-Modern Room nearDowntown\\Airport, stay from 05:00 to 05:30; Side Street Private Guesthouse, stay from 17:19 to 17:49..."
    },
    {
       "day": 5,
       "current_city": "from Amarillo to San Antonio",
       "transportation": "Taxi from Amarillo to San Antonio..."
    },
    {
      "day": 7,
      "current_city": "from San Antonio to Champaign",
      "transportation": "Taxi from San Antonio to Champaign...",
      "point_of_interest_list": "..."
    }
  ],
  "budget_used": 6048.22,
  "budget_ok": true
}
```
