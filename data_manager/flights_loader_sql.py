# flights_loader_sql.py
# flights_loader_sql.py
import sqlite3
import pandas as pd
import os


class FlightsLoaderSQL:

    def __init__(self, base_path, db_path):
        """
        base_path = E:/BTP/Vijay/TravelPlanner/database
        db_path   = E:/BTP/Vijay/TravelPlanner/db/flights.db
        """

        # Correct CSV path
        self.csv_path = os.path.join(
            base_path,
            "flights",
            "clean_Flights_2022.csv"
        )

        self.db_path = db_path

        # Ensure DB folder exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        create_db = not os.path.exists(db_path)

        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()

        if create_db:
            print(f"[FlightsLoaderSQL] No DB found → creating at {db_path}")
            self._create_table()
            self._import_csv()
            self._create_indexes()
        else:
            print(f"[FlightsLoaderSQL] Using existing DB → {db_path}")

        self.data = None


    # -----------------------------------------------------------
    # TABLE SCHEMA (MATCHES YOUR CSV EXACTLY)
    # -----------------------------------------------------------
    def _create_table(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS flights (
                FlightNum TEXT,
                Price REAL,
                DepTime TEXT,
                ArrTime TEXT,
                ActualElapsedTime TEXT,
                FlightDate TEXT,
                OriginCityName TEXT,
                DestCityName TEXT,
                Distance REAL,
                Airline TEXT
            )
        """)
        self.conn.commit()

    # -----------------------------------------------------------
    # IMPORT CSV → SQLITE
    # -----------------------------------------------------------
    def _import_csv(self):
        if not os.path.exists(self.csv_path):
            raise FileNotFoundError(f"Flights CSV not found → {self.csv_path}")

        df = pd.read_csv(self.csv_path)

        # Normalize column names
        df.columns = [c.strip() for c in df.columns]

        # Rename to match DB schema
        rename_map = {
            "Flight Number": "FlightNum",
            "Price": "Price",
            "DepTime": "DepTime",
            "ArrTime": "ArrTime",
            "ActualElapsedTime": "ActualElapsedTime",
            "FlightDate": "FlightDate",
            "OriginCityName": "OriginCityName",
            "DestCityName": "DestCityName",
            "Distance": "Distance",
        }
        df = df.rename(columns=rename_map)

        # Missing airline field
        if "Airline" not in df.columns:
            df["Airline"] = "Unknown"

        df["OriginCityName"] = df["OriginCityName"].astype(str).str.strip()
        df["DestCityName"] = df["DestCityName"].astype(str).str.strip()

        df.to_sql("flights", self.conn, if_exists="append", index=False)

        print(f"[FlightsLoaderSQL] Imported {len(df)} rows into DB")

    # -----------------------------------------------------------
    # INDEXES FOR FAST SEARCH
    # -----------------------------------------------------------
    def _create_indexes(self):
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_org ON flights(OriginCityName)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_dest ON flights(DestCityName)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON flights(FlightDate)")
        self.conn.commit()

    # -----------------------------------------------------------
    # LOAD INTO MEMORY (OPTIONAL)
    # -----------------------------------------------------------
    def load(self):
        self.data = None

    # -----------------------------------------------------------
    # DIRECT FLIGHTS
    # -----------------------------------------------------------
    def get_flights(self, origin, dest, date):
        query = """
            SELECT *
            FROM flights
            WHERE LOWER(OriginCityName) = LOWER(?)
              AND LOWER(DestCityName) = LOWER(?)
              AND FlightDate = ?
        """
        return pd.read_sql_query(query, self.conn, params=[origin, dest, date])

    # -----------------------------------------------------------
    # 1-STOP CONNECTING FLIGHTS
    # -----------------------------------------------------------
    def get_connecting_flights(self, origin, dest, date, min_layover=45, max_layover=180):

        leg1_df = pd.read_sql_query("""
            SELECT * FROM flights
            WHERE LOWER(OriginCityName) = LOWER(?)
              AND FlightDate = ?
        """, self.conn, params=[origin, date])

        leg2_df = pd.read_sql_query("""
            SELECT * FROM flights
            WHERE LOWER(DestCityName) = LOWER(?)
              AND FlightDate = ?
        """, self.conn, params=[dest, date])

        results = []

        def t2min(t):
            h, m = map(int, t.split(":"))
            return h * 60 + m

        for _, f1 in leg1_df.iterrows():
            mid = f1["DestCityName"]
            arr1 = t2min(f1["ArrTime"])

            candidates = leg2_df[
                leg2_df["OriginCityName"].str.lower() == mid.lower()
            ]

            for _, f2 in candidates.iterrows():
                dep2 = t2min(f2["DepTime"])
                layover = dep2 - arr1

                if min_layover <= layover <= max_layover:
                    results.append({
                        "intermediate_city": mid,
                        "layover_minutes": layover,
                        "leg1": dict(f1),
                        "leg2": dict(f2)
                    })

        return results

    # -----------------------------------------------------------
    # CLOSE CONNECTION
    # -----------------------------------------------------------
    def close(self):
        self.conn.close()
