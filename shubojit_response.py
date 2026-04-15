import re

def extract_itinerary(response: str) -> str:
    match = re.search(r"\bITINERARY\b|\bItinerary\b", response)
    if not match:
        raise RuntimeError("Missing ITINERARY section from LLM")
    itinerary = response[match.end():].strip()
    itinerary = re.sub(r"^[\s:\-]+", "", itinerary)
    if itinerary.startswith("```"):
        itinerary = re.sub(r"^```[a-zA-Z]*\n?", "", itinerary)
        itinerary = re.sub(r"\n?```$", "", itinerary)
    itinerary = itinerary.strip()
    if not itinerary:
        raise RuntimeError("Empty itinerary from LLM")
    return itinerary

class AFTERLLMPOIAGENT:
    def __init__(self):
        pass

    def min_to_hhmm(self,m: int) -> str:
        m = m % 1440
        h = m // 60
        mi = m % 60
        return f"{h:02d}:{mi:02d}"

    def convert_minutes_to_time(self,itinerary: str) -> str:
        lines = []
        for line in itinerary.splitlines():
            match = re.search(r"from\s+(\d+)\s+to\s+(\d+);", line)
            if not match:
                lines.append(line)
                continue
            start_min = int(match.group(1))
            end_min = int(match.group(2))
            start_time = self.min_to_hhmm(start_min)
            end_time = self.min_to_hhmm(end_min)
            line = re.sub(
                r"from\s+\d+\s+to\s+\d+;",
                f"from {start_time} to {end_time};",
                line
            )
            lines.append(line)
        return "\n".join(lines)

    def enforce_monotonic_schedule(self,itinerary: str) -> str:
        entries = []
        for line in itinerary.splitlines():
            m = re.search(r"from (\d+) to (\d+);", line)
            if not m:
                continue
            start = int(m.group(1))
            end = int(m.group(2))
            entries.append((start, end, line))
        entries.sort(key=lambda x: x[0])
        cleaned = []
        prev_end = None
        for start, end, line in entries:
            if prev_end is not None and start < prev_end:
                continue
            cleaned.append(line)
            prev_end = end
        return "\n".join(cleaned)

    def process_llm_response(self, response: str) -> str:
        if "ITINERARY" not in response:
            raise RuntimeError("Missing ITINERARY section from LLM")
        itinerary = extract_itinerary(response)
        if not itinerary:
            raise RuntimeError("Empty itinerary from LLM")
        itinerary = itinerary.replace('"', '').replace("'", "")
        itinerary = re.sub(r'(^|\n)\s*-\s*', r'\1', itinerary)
        itinerary = re.sub(r'(^|\n)\s*\d+\.\s*', r'\1', itinerary)
        itinerary = self.enforce_monotonic_schedule(itinerary)
        itinerary = self.convert_minutes_to_time(itinerary)
        return itinerary

def main():
    print("Starting AFTERLLMPOIAGENT test...")

    agent = AFTERLLMPOIAGENT()

    response = """
    Here is the plan:
    =======================
    ITINERARY
    =======================
    Accommodation Name, stay from 1200 to 1230;
    """

    try:
        result = agent.process_llm_response(response)
        print(result)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
