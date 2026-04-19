import subprocess
import sys
import os
import time

REQUIRED_FREE = 2000      # MiB
CHECK_INTERVAL = 30        # seconds

MODEL_NAME = "qwen2.5"
DAY_TYPES = [3,5,7]

OUTPUT_DIR = "output_agentic_review_experiment"
BASEPATH = "./TripCraft_database"
API_KEY = "your_api_key_here"


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
            "tools/planner/agentic_planning_with_pro_cons.py",
            "--day_type", str(day_type),
            "--model_name", MODEL_NAME,
            "--api_key", API_KEY,
            "--output_dir", OUTPUT_DIR,
            "--basepath", BASEPATH,
        ]
        # cmd = [
        #     sys.executable,
        #     "tools/planner/rerun.py",
        #     "--model", MODEL_NAME,
        #     "--day", str(day_type),
        #     "--api_key", API_KEY
        # ]

        print(f"\n🚀 Starting Agentic Planner (day_type={day_type})")
        print("PYTHONPATH=. " + " ".join(cmd))

        subprocess.run(cmd, env=env, check=True)


if __name__ == "__main__":
    print("⏳ Waiting for GPU to become free...")
    print(f"➡️ Required free memory: {REQUIRED_FREE} MiB\n")

    while True:
        total, used = get_gpu_memory()
        free = total - used
        # cmd = [
        #     sys.executable,
        #     "tools/planner/rerun.py",
        #     "--model", MODEL_NAME,
        #     "--day", str(DAY_TYPES[0]),
        #     "--api_key", API_KEY
        # ]

        print(
            f"[GPU CHECK] "
            f"Used: {used:5d} MiB | "
            f"Free: {free:5d} MiB",
            # f"cmd: {cmd}",
            flush=True,
        )

        if free >= REQUIRED_FREE:
            print("\n✅ GPU is free enough. Launching jobs...")
            run_agentic_planner()
            break

        time.sleep(CHECK_INTERVAL)
