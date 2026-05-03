# -*- coding: utf-8 -*-
"""Split turns.jsonl into per-batch input files for SUBAGENT dispatch.

Pipeline step 2 of 3 — subagent mode.

Use this when running inside Claude Code / Codex / any CLI with subagent
fan-out support. Each batch becomes one self-contained text file you can
hand to a fresh subagent. After all subagents finish, concatenate their
JSONL outputs into turns_scored.jsonl.

Usage
-----
    python scripts/score_turns_dispatch.py \
        --turns      output/_jobs/myjob/turns.jsonl \
        --out-dir    output/_jobs/myjob/batches/ \
        --batch-size 60

Outputs
-------
    {out_dir}/batch_001_input.txt   (human-readable turn block)
    {out_dir}/batch_002_input.txt
    ...
    {out_dir}/manifest.json         (batch metadata + suggested subagent prompt)

Each subagent should be told:
    "Read scripts/SUBAGENT_PROMPT.md for the scoring rules. Read
     {batch_NNN_input.txt}. Emit JSONL lines (one per turn) to
     {batch_NNN_output.jsonl}. No prose, no fences."
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROMPT_TEMPLATE = (
    "Score each TURN in {input_file} using the v3.1 schema (read "
    "skill/SKILL.md for the full rule set). A turn is one or more "
    "consecutive same-sender messages joined by newlines — treat it as "
    "ONE event.\n\n"
    "For each turn, output ONE JSON object with fields:\n"
    '  {{"turn_id": int, "delta_vs_prior": float, '
    '"delta_vs_atmosphere": float, "primary_dim": str, '
    '"tags": [str], "rationale": str}}\n\n'
    "Write the {n_turns} JSONL lines (no markdown, no prose) to "
    "{output_file}.\n\n"
    "Reminders:\n"
    "  - Most turns should have nonzero deltas (±0.2 ~ ±0.5).\n"
    "  - 0/0 only when a turn truly contributes nothing.\n"
    "  - rationale ≤ 8 Chinese characters; '' is fine for routine.\n"
    "  - primary_dim ∈ {{affection, engagement, care, conflict, tension, "
    "investment, awkwardness, future_orientation, vulnerability, "
    "shared_identity}}."
)


def render_batch_text(batch: list[dict]) -> str:
    lines = []
    for t in batch:
        lines.append(f"[{t['turn_id']}] {t['sender']} ({t['n_msgs']}msgs):")
        lines.append(t["text"])
        lines.append("---")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns",   required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--batch-size", type=int, default=60)
    args = ap.parse_args()

    turns = []
    with open(args.turns, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                turns.append(json.loads(line))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    batches = [
        turns[i:i + args.batch_size]
        for i in range(0, len(turns), args.batch_size)
    ]

    manifest = {
        "total_turns": len(turns),
        "batch_size":  args.batch_size,
        "n_batches":   len(batches),
        "batches":     [],
    }

    for idx, batch in enumerate(batches, start=1):
        in_name  = f"batch_{idx:03d}_input.txt"
        out_name = f"batch_{idx:03d}_output.jsonl"
        in_path  = out_dir / in_name
        in_path.write_text(render_batch_text(batch), encoding="utf-8")

        manifest["batches"].append({
            "index":       idx,
            "input_file":  str(in_path.as_posix()),
            "output_file": str((out_dir / out_name).as_posix()),
            "first_turn":  batch[0]["turn_id"],
            "last_turn":   batch[-1]["turn_id"],
            "n_turns":     len(batch),
            "subagent_prompt": PROMPT_TEMPLATE.format(
                input_file=in_name,
                output_file=out_name,
                n_turns=len(batch),
            ),
        })

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[dispatch] turns={len(turns)} batches={len(batches)} "
          f"out_dir={out_dir}")
    print(f"  -> {out_dir / 'manifest.json'}")
    print(f"  hand each batch_NNN_input.txt to a subagent (prompt in manifest)")


if __name__ == "__main__":
    main()
