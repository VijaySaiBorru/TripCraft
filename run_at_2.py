import subprocess
import sys
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # Python 3.9+

REQUIRED_FREE = 32000      # MiB
CHECK_INTERVAL = 30        # seconds

MODEL_NAME = "phi4"
DAY_TYPES = [3, 5, 7]

OUTPUT_DIR = "output_agentic_final"
BASEPATH = "./TripCraft_database"
API_KEY = "your_api_key_here"

IST = ZoneInfo("Asia/Kolkata")


def wait_until_2am():
    now = datetime.now(IST)
    target = now.replace(hour=23, minute=30, second=0, microsecond=0)

    # If already past 2 AM today → schedule for tomorrow
    if now >= target:
        target += timedelta(days=1)

    wait_seconds = (target - now).total_seconds()

    print(f"🕑 Current IST time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏳ Waiting until 23:30 PM IST ({target.strftime('%Y-%m-%d %H:%M:%S')})")
    print(f"⏳ Sleeping for {int(wait_seconds)} seconds...\n")

    time.sleep(wait_seconds)


def get_gpu_memory():
    result = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=memory.total,memory.used",
            "--format=csv,noheader,nounits",
        ]
    )
    total, used = map(int, result.decode().strip().split(","))
    return total, used


def run_agentic_planner():
    env = os.environ.copy()
    env["PYTHONPATH"] = "."

    for day_type in DAY_TYPES:
        cmd = [
            sys.executable,
            "tools/planner/agentic_planning.py",
            "--day_type", str(day_type),
            "--model_name", MODEL_NAME,
            "--api_key", API_KEY,
            "--output_dir", OUTPUT_DIR,
            "--basepath", BASEPATH,
        ]

        print(f"\n🚀 Starting Agentic Planner (day_type={day_type})")
        print("PYTHONPATH=. " + " ".join(cmd))

        subprocess.run(cmd, env=env, check=True)


if __name__ == "__main__":

    # Step 1: Wait until 2 AM IST
    wait_until_2am()

    # Step 2: Start GPU monitoring
    print("⏳ Waiting for GPU to become free...")
    print(f"➡️ Required free memory: {REQUIRED_FREE} MiB\n")

    while True:
        total, used = get_gpu_memory()
        free = total - used

        print(
            f"[GPU CHECK] "
            f"Used: {used:5d} MiB | "
            f"Free: {free:5d} MiB",
            flush=True,
        )

        if free >= REQUIRED_FREE:
            print("\n✅ GPU is free enough. Launching jobs...")
            run_agentic_planner()
            break

        time.sleep(CHECK_INTERVAL)
