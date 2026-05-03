# -*- coding: utf-8 -*-
"""Pre-process raw messages into TURNS for batched LLM scoring.

Pipeline step 1 of 3.

What it does
------------
1. Read raw messages.jsonl (fields: i, timestamp, sender, message).
2. Mark trivial messages (single-char / pure URL / empty) -> auto_scored.jsonl
   with -0.2/-0.2/engagement.
3. Aggregate consecutive messages from the SAME sender (after trivial removal)
   when adjacent timestamps are within --gap-min minutes -> turns.jsonl.
4. Write turns_meta.json — the mapping needed by expand_turns.py.

Usage
-----
    python scripts/preprocess_turns.py \
        --input  output/_jobs/myjob/messages.jsonl \
        --out-dir output/_jobs/myjob/ \
        --gap-min 10
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

URL_PATTERN = re.compile(r"^https?://\S+$")


def is_trivial(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return True
    if len(text) == 1:
        return True
    if URL_PATTERN.match(text):
        return True
    return False


def load_messages(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def parse_ts(ts: str) -> datetime:
    # Tolerate both "T" and " " separators, trailing Z optional.
    if ts.endswith("Z"):
        ts = ts[:-1]
    return datetime.fromisoformat(ts)


def aggregate_turns(substantive: list[dict], gap_min: int) -> list[dict]:
    """Group consecutive same-sender msgs into turns when gap <= gap_min minutes."""
    turns: list[dict] = []
    cur: list[dict] | None = None
    gap_seconds = gap_min * 60

    for m in substantive:
        if cur is None:
            cur = [m]
            continue
        prev = cur[-1]
        same_sender = (m["sender"] == prev["sender"])
        gap = (parse_ts(m["timestamp"]) - parse_ts(prev["timestamp"])).total_seconds()
        if same_sender and gap <= gap_seconds:
            cur.append(m)
        else:
            turns.append(_finalize_turn(cur, len(turns) + 1))
            cur = [m]

    if cur:
        turns.append(_finalize_turn(cur, len(turns) + 1))
    return turns


def _finalize_turn(msgs: list[dict], turn_id: int) -> dict:
    text = "\n".join((m["message"] or "").rstrip("\n") for m in msgs)
    return {
        "turn_id":      turn_id,
        "sender":       msgs[0]["sender"],
        "ts_first":     msgs[0]["timestamp"],
        "ts_last":      msgs[-1]["timestamp"],
        "n_msgs":       len(msgs),
        "char_total":   sum(len(m["message"] or "") for m in msgs),
        "original_is":  [int(m["i"]) for m in msgs],
        "text":         text,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="raw messages.jsonl")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--gap-min", type=int, default=10,
                    help="max gap in minutes between same-sender messages "
                         "to count as one turn")
    args = ap.parse_args()

    in_path  = Path(args.input)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    msgs = load_messages(in_path)
    msgs.sort(key=lambda m: int(m["i"]))

    auto: list[dict] = []
    substantive: list[dict] = []
    for m in msgs:
        if is_trivial(m.get("message", "")):
            auto.append({
                "i": int(m["i"]),
                "delta_vs_prior":      -0.2,
                "delta_vs_atmosphere": -0.2,
                "primary_dim":         "engagement",
                "tags":                [],
                "rationale":           "",
            })
        else:
            substantive.append(m)

    turns = aggregate_turns(substantive, args.gap_min)

    auto_path  = out_dir / "auto_scored.jsonl"
    turns_path = out_dir / "turns.jsonl"
    meta_path  = out_dir / "turns_meta.json"

    with auto_path.open("w", encoding="utf-8", newline="\n") as f:
        for r in auto:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with turns_path.open("w", encoding="utf-8", newline="\n") as f:
        for t in turns:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    meta = {
        "input_messages":   len(msgs),
        "trivial_auto":     len(auto),
        "substantive_msgs": len(substantive),
        "turns":            len(turns),
        "compression_ratio": round(len(turns) / len(substantive), 3) if substantive else 0,
        "gap_min":          args.gap_min,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    print(f"[preprocess] msgs={meta['input_messages']}  "
          f"auto={meta['trivial_auto']}  "
          f"substantive={meta['substantive_msgs']}  "
          f"turns={meta['turns']}  "
          f"compress={meta['compression_ratio']}")
    print(f"  -> {auto_path}")
    print(f"  -> {turns_path}")
    print(f"  -> {meta_path}")


if __name__ == "__main__":
    main()
