#!/usr/bin/env python3
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.
#
# ---------------------------------------------------------------------------
# generate_benchmark_template.py
#
# Generates a sample benchmark input file (benchmark_template.xlsx) that
# matches the schema expected by BenchmarkService / the `flask run-benchmark`
# CLI command.
#
# Usage:
#   python examples/generate_benchmark_template.py
#
# The output file is written to the same directory as this script:
#   examples/benchmark_template.xlsx
#
# See also: docs/benchmark_testing.md
# ---------------------------------------------------------------------------

import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    sys.exit(
        "❌ pandas is not installed. Run:  pip install pandas openpyxl"
    )

OUTPUT_PATH = Path(__file__).parent / "benchmark_template.xlsx"

# ---------------------------------------------------------------------------
# Sample rows — replace with rows that reflect your real prompt/user setup.
# Every column listed below is REQUIRED by BenchmarkService.run().
# ---------------------------------------------------------------------------
SAMPLE_ROWS = [
    {
        "username": "analyst@example.com",
        "client_identity": "12345678-9",
        "prompt_name": "financial_summary",
        "question": "What is the total current balance for this client?",
        "model": "gpt-4o",
    },
    {
        "username": "analyst@example.com",
        "client_identity": "98765432-1",
        "prompt_name": "financial_summary",
        "question": "List the last 3 transactions for this client.",
        "model": "gpt-4o",
    },
    {
        "username": "qa_tester@example.com",
        "client_identity": "11111111-1",
        "prompt_name": "risk_assessment",
        "question": "What is the credit risk level for this client?",
        "model": "claude-3-5-sonnet-20241022",
    },
    {
        "username": "qa_tester@example.com",
        "client_identity": "22222222-2",
        "prompt_name": "risk_assessment",
        "question": "Has this client missed any payments in the last 12 months?",
        "model": "claude-3-5-sonnet-20241022",
    },
    {
        "username": "analyst@example.com",
        "client_identity": "33333333-3",
        "prompt_name": "product_recommendation",
        "question": "Which savings products would you recommend for this client?",
        "model": "gemini-2.0-flash",
    },
]

# Optional: add extra columns for your own tracking (they are preserved in output)
EXTRA_COLUMNS = {
    "expected_answer": ["", "", "", "", ""],   # fill in for regression testing
    "test_id": ["FIN-001", "FIN-002", "RSK-001", "RSK-002", "PRD-001"],
}


def main():
    data = {**{k: [r[k] for r in SAMPLE_ROWS] for k in SAMPLE_ROWS[0]}, **EXTRA_COLUMNS}
    df = pd.DataFrame(data)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(OUTPUT_PATH, index=False)

    print(f"✅ Benchmark template saved to: {OUTPUT_PATH}")
    print(f"   Rows    : {len(df)}")
    print(f"   Columns : {list(df.columns)}")
    print()
    print("Next step:")
    print(f"  flask run-benchmark <company_short_name> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
