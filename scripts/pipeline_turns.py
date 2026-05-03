# -*- coding: utf-8 -*-
"""End-to-end orchestrator for the TURN-based scoring pipeline.

Wraps the three steps:
    1. preprocess_turns.py  → turns.jsonl + auto_scored.jsonl
    2. score_turns_api.py   (--mode api)        → turns_scored.jsonl
       OR score_turns_dispatch.py (--mode subagent) → batch_NNN_input.txt files
    3. expand_turns.py      → scored_v31_turns.jsonl

Usage
-----
    # API mode (one-shot, parallel calls):
    python scripts/pipeline_turns.py \
        --input output/_jobs/myjob/messages.jsonl \
        --out-dir output/_jobs/myjob/ \
        --mode api \
        --batch-size 60 --concurrency 5

    # Subagent dispatch mode (writes batch files; you fan-out yourself):
    python scripts/pipeline_turns.py \
        --input output/_jobs/myjob/messages.jsonl \
        --out-dir output/_jobs/myjob/ \
        --mode subagent --batch-size 60
    # ... then run each batch with subagents, drop outputs as
    # batches/batch_NNN_output.jsonl, then re-run with --mode finalize
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PY = sys.executable


def run(cmd: list[str]) -> None:
    print(f"\n>>> {' '.join(cmd)}")
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        sys.exit(proc.returncode)


def gather_subagent_outputs(out_dir: Path, dest: Path) -> int:
    """Concatenate batches/batch_*_output.jsonl into one turns_scored.jsonl."""
    batches_dir = out_dir / "batches"
    files = sorted(batches_dir.glob("batch_*_output.jsonl"))
    n = 0
    with dest.open("w", encoding="utf-8", newline="\n") as fout:
        for fp in files:
            with fp.open(encoding="utf-8") as fin:
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    fout.write(line + "\n")
                    n += 1
    print(f"[gather] {len(files)} files -> {dest} ({n} lines)")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input",   required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--mode", choices=["api", "subagent", "finalize"],
                    required=True,
                    help="api: parallel API calls. subagent: split batches "
                         "for manual subagent fan-out. finalize: gather "
                         "subagent outputs and run expand step.")
    ap.add_argument("--gap-min",     type=int, default=10)
    ap.add_argument("--batch-size",  type=int, default=60)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--model",       default="claude-sonnet-4-6")
    ap.add_argument("--resume",      action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    turns_path        = out_dir / "turns.jsonl"
    auto_path         = out_dir / "auto_scored.jsonl"
    turns_scored_path = out_dir / "turns_scored.jsonl"
    final_path        = out_dir / "scored_v31_turns.jsonl"
    batches_dir       = out_dir / "batches"

    # Step 1 — preprocess
    run([PY, str(ROOT / "preprocess_turns.py"),
         "--input",   args.input,
         "--out-dir", str(out_dir),
         "--gap-min", str(args.gap_min)])

    if args.mode == "api":
        # Step 2a — async API scoring
        cmd = [PY, str(ROOT / "score_turns_api.py"),
               "--turns",       str(turns_path),
               "--out",         str(turns_scored_path),
               "--batch-size",  str(args.batch_size),
               "--concurrency", str(args.concurrency),
               "--model",       args.model]
        if args.resume:
            cmd.append("--resume")
        run(cmd)

        # Step 3 — expand
        run([PY, str(ROOT / "expand_turns.py"),
             "--turns",        str(turns_path),
             "--turns-scored", str(turns_scored_path),
             "--auto",         str(auto_path),
             "--messages",     args.input,
             "--out",          str(final_path)])

    elif args.mode == "subagent":
        # Step 2b — split into batch input files for subagent dispatch
        run([PY, str(ROOT / "score_turns_dispatch.py"),
             "--turns",      str(turns_path),
             "--out-dir",    str(batches_dir),
             "--batch-size", str(args.batch_size)])
        print()
        print("=" * 60)
        print("Now hand each batch input file to a fresh subagent.")
        print(f"Manifest: {batches_dir / 'manifest.json'}")
        print("Each subagent writes its result to:")
        print(f"  {batches_dir}/batch_NNN_output.jsonl")
        print("When all subagents are done, run:")
        print(f"  python scripts/pipeline_turns.py "
              f"--input {args.input} --out-dir {args.out_dir} "
              f"--mode finalize")
        print("=" * 60)

    elif args.mode == "finalize":
        # Step 2c — gather subagent outputs
        n = gather_subagent_outputs(out_dir, turns_scored_path)
        if n == 0:
            sys.exit("no batch outputs found in batches/")
        # Step 3
        run([PY, str(ROOT / "expand_turns.py"),
             "--turns",        str(turns_path),
             "--turns-scored", str(turns_scored_path),
             "--auto",         str(auto_path),
             "--messages",     args.input,
             "--out",          str(final_path)])

    print("\n[pipeline] done.")
    if (out_dir / "scored_v31_turns.jsonl").exists():
        print(f"  final: {out_dir / 'scored_v31_turns.jsonl'}")


if __name__ == "__main__":
    main()
