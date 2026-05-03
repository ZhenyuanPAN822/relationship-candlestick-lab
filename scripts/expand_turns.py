# -*- coding: utf-8 -*-
"""Expand turn-level scores back to original message-level scored.jsonl.

Pipeline step 3 of 3.

Rules
-----
- For each scored turn, the FIRST original message i in the turn receives
  the full delta payload (delta_vs_prior, delta_vs_atmosphere, primary_dim,
  tags, rationale).
- The other messages in the turn (the "fragments" that were merged) get
  0/0/engagement/[]/"" — no extra contribution to the K-line.
- Auto-scored trivial messages keep their -0.2/-0.2 entries.
- Output is sorted by i.

Usage
-----
    python scripts/expand_turns.py \
        --turns         output/_jobs/myjob/turns.jsonl \
        --turns-scored  output/_jobs/myjob/turns_scored.jsonl \
        --auto          output/_jobs/myjob/auto_scored.jsonl \
        --messages      output/_jobs/myjob/messages.jsonl \
        --out           output/_jobs/myjob/scored_v31_turns.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


ZERO = {
    "delta_vs_prior":      0.0,
    "delta_vs_atmosphere": 0.0,
    "primary_dim":         "engagement",
    "tags":                [],
    "rationale":           "",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns",        required=True)
    ap.add_argument("--turns-scored", required=True)
    ap.add_argument("--auto",         required=True)
    ap.add_argument("--messages",     required=True,
                    help="raw messages.jsonl (used only for full-coverage check)")
    ap.add_argument("--out",          required=True)
    args = ap.parse_args()

    turns        = load_jsonl(Path(args.turns))
    turns_scored = load_jsonl(Path(args.turns_scored))
    autos        = load_jsonl(Path(args.auto))
    msgs         = load_jsonl(Path(args.messages))

    score_by_turn = {int(s["turn_id"]): s for s in turns_scored}

    # Build i -> record
    by_i: dict[int, dict] = {}

    # 1. Auto-scored fillers (lowest priority among "real" entries)
    for a in autos:
        i = int(a["i"])
        by_i[i] = {
            "i": i,
            "delta_vs_prior":      a["delta_vs_prior"],
            "delta_vs_atmosphere": a["delta_vs_atmosphere"],
            "primary_dim":         a.get("primary_dim", "engagement"),
            "tags":                a.get("tags", []),
            "rationale":           a.get("rationale", ""),
        }

    # 2. Turn expansion (overrides auto if there's any collision — there shouldn't be)
    missing_turn_scores = []
    for t in turns:
        tid = int(t["turn_id"])
        ois = [int(x) for x in t["original_is"]]
        score = score_by_turn.get(tid)
        if score is None:
            missing_turn_scores.append(tid)
            for k, i in enumerate(ois):
                by_i[i] = {"i": i, **ZERO}
            continue
        first = ois[0]
        by_i[first] = {
            "i":                   first,
            "delta_vs_prior":      score["delta_vs_prior"],
            "delta_vs_atmosphere": score["delta_vs_atmosphere"],
            "primary_dim":         score["primary_dim"],
            "tags":                score["tags"],
            "rationale":           score["rationale"],
        }
        for i in ois[1:]:
            by_i[i] = {"i": i, **ZERO}

    # 3. Coverage check vs raw messages
    expected_is = {int(m["i"]) for m in msgs}
    missing_i = sorted(expected_is - set(by_i))
    extra_i   = sorted(set(by_i) - expected_is)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for i in sorted(by_i):
            f.write(json.dumps(by_i[i], ensure_ascii=False) + "\n")

    print(f"[expand] turns={len(turns)} scored_turns={len(turns_scored)} "
          f"auto={len(autos)} -> total i={len(by_i)}")
    print(f"  missing_turn_scores: {len(missing_turn_scores)}")
    if missing_turn_scores[:10]:
        print(f"    first 10: {missing_turn_scores[:10]}")
    print(f"  missing i (vs messages): {len(missing_i)}")
    if missing_i[:10]:
        print(f"    first 10: {missing_i[:10]}")
    print(f"  extra i (not in messages): {len(extra_i)}")
    print(f"  -> {out_path}")

    if missing_i or missing_turn_scores:
        sys.exit(2)


if __name__ == "__main__":
    main()
