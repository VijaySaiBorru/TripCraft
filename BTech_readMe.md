# TripCraft – BTP README

## Project Overview

TripCraft is a multi-agent travel itinerary generation framework that generates structured travel plans from natural language user queries. The framework uses multiple collaborative agents for itinerary planning and also supports review-grounded reasoning and pro-cons based itinerary generation.

The project supports:
- Multi-agent itinerary planning
- Review-grounded itinerary generation
- With-review and without-review pipelines
- JSON to JSONL conversion utilities
- Automatic evaluation and qualitative analysis

---

## Project Structure

```bash
TripCraft/
│
├── run.py
├── run_review.py
├── run_review_pro_cons.py
├── jsonl.py
├── requirements.txt
├── agentic.yml
│
├── agentic_planning.py
│
├── evaluation/
│   ├── eval.py
│   ├── qualitative_metrics.py
│   └── evaluate_rgpa.py
│
└── TripCraft_database/
```

---

## Features

- Multi-agent itinerary generation
- Travel planning from natural language queries
- Support for multiple LLM backends
- Review-grounded planning
- Pro-cons based reasoning
- Automatic evaluation scripts
- Qualitative and review-grounded metrics

---

## Dependencies

The project uses the following dependencies:

```txt
torch
transformers
accelerate
openai
pandas
numpy
tqdm
```

---

## Environment Setup

### 1. Clone the Repository

```bash
git clone <repository_url>
cd TripCraft
```

### 2. Create Conda Environment

```bash
conda env create -f agentic.yml
```

Activate the environment:

```bash
conda activate agentic
```

### 3. Install Required Packages

```bash
pip install -r requirements.txt
```

---

## Dataset / Database Setup

Before execution, download the `TripCraft_database` from the following Google Drive link:

Dataset Link:  
https://drive.google.com/drive/folders/1k2rz7-oBd8qKFBZR-0Nl-OVjjYSAK-OH

After downloading, place the database inside the project directory.

Expected structure:

```bash
TripCraft/
└── TripCraft_database/
```
---

## Results / Sample Outputs

Generated sample outputs and result JSON/JSONL files can be accessed from the following Google Drive link:

Results Folder:  
https://drive.google.com/drive/folders/1lEK4p-PIEVLu2nDy2SrQfPhD5BbdjBqh

This folder contains:
- Generated itineraries
- JSONL converted files
- Evaluation result files


## Execution Instructions

### A. Running Without Reviews

```bash
python run.py
```

#### Required Configuration

Inside `run.py`:
- Initialize the required model
- Configure the required day type

Inside `agentic_planning.py`:
- Set the start index
- Set the end index

---

### B. Running With Reviews

```bash
python run_review.py
```

or

```bash
python run_review_pro_cons.py
```

#### Required Configuration

Before execution:
- Initialize the desired model
- Configure day type settings
- Set start and end indices inside `agentic_planning.py`

---

## JSON to JSONL Conversion

Convert generated JSON outputs into JSONL format using:

```bash
python jsonl.py --model <model_name> --day <day_number>
```

Example:

```bash
python jsonl.py --model llama --day 3
```

---

## Evaluation

Move to the evaluation directory:

```bash
cd evaluation
```

### 1. Standard Evaluation

```bash
python eval.py --set_type <day_type> --evaluation_file_path <path_to_file>
```

Example:

```bash
python eval.py --set_type 3day --evaluation_file_path outputs/result.jsonl
```

---

### 2. Qualitative Metrics Evaluation

```bash
python qualitative_metrics.py --gen_file <generated_file> --anno_file <golden_annotation_file>
```

Example:

```bash
python qualitative_metrics.py --gen_file generated.jsonl --anno_file golden.jsonl
```

---

### 3. Review-Grounded Metrics Evaluation

```bash
python evaluate_rgpa.py --gen_file <generated_file> --db_dir <database_path>
```

Example:

```bash
python evaluate_rgpa.py --gen_file generated.jsonl --db_dir ../TripCraft_database
```

---

## Configuration Notes

### Model Initialization

Before running experiments:
- Initialize the required LLM/model
- Configure API keys if required
- Update model paths appropriately

---

### Day Type Configuration

Update day type settings inside:
- `run.py`
- `run_review.py`
- `run_review_pro_cons.py`

---

### Start and End Index Configuration

Modify indices inside:

```bash
agentic_planning.py
```

This helps in:
- Partial dataset execution
- Parallel experimentation
- Resuming interrupted runs

---

## Output

Generated itineraries are stored in JSON format and can later be converted into JSONL format for evaluation.

---

## Research Context

This project is developed as part of a Bachelor Thesis Project (BTP) focusing on:
- Multi-agent systems
- LLM-based planning
- Travel itinerary generation
- Review-grounded reasoning
- Agentic AI workflows

---

## Citation

If using this project or dataset, please cite the corresponding TripCraft paper.

Example:

> Chaudhuri et al., "TripCraft: A Fine-Grained Spatio-Temporal Benchmark for Travel Planning", ACL 2025.