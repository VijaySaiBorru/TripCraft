import pandas as pd
from pandas import DataFrame
from typing import Optional
from datetime import datetime


class Events:
    def __init__(self, path='/scratch/sg/Vijay/TripCraft/TripCraft_database/events/events_cleaned.csv'):
        self.path = path

        # Load required columns
        self.data = pd.read_csv(self.path)[
            ['name', 'url', 'dateTitle', 'streetAddress', 'segmentName', 'city']
        ].dropna(subset=['name', 'url', 'dateTitle', 'city'])

        # --------------------------------------------------
        # Parse dateTitle → start_date / end_date
        # --------------------------------------------------
        start_dates = []
        end_dates = []

        for raw in self.data['dateTitle']:
            raw = str(raw).strip()

            try:
                # Case 1: date range (dd-mm-yyyy to dd-mm-yyyy)
                if 'to' in raw:
                    s, e = [x.strip() for x in raw.split('to')]
                    start = datetime.strptime(s, '%d-%m-%Y').date()
                    end = datetime.strptime(e, '%d-%m-%Y').date()
                else:
                    # Case 2: single date
                    start = end = datetime.strptime(raw, '%d-%m-%Y').date()
            except Exception:
                start = end = None

            start_dates.append(start)
            end_dates.append(end)

        self.data['start_date'] = start_dates
        self.data['end_date'] = end_dates

        # Drop rows with unparseable dates
        self.data = self.data.dropna(subset=['start_date', 'end_date'])

        print("Events loaded.")

    def load_db(self):
        self.__init__(self.path)

    def run(self, city: str, date_range: list) -> DataFrame:
        """
        Search for events by city and date range.
        Includes multi-day events if they overlap the range.
        """
        start_date = datetime.strptime(date_range[0], '%Y-%m-%d').date()
        end_date = datetime.strptime(date_range[-1], '%Y-%m-%d').date()

        results = self.data[
            (self.data['city'] == city) &
            (self.data['start_date'] <= end_date) &
            (self.data['end_date'] >= start_date)
        ].reset_index(drop=True)

        if len(results) == 0:
            return "There are no events in this city for the given date range."

        return results

    def run_for_annotation(self, city: str) -> DataFrame:
        results = self.data[self.data["city"] == city]
        return results.reset_index(drop=True)
