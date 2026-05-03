# -*- coding: utf-8 -*-
"""Score turns.jsonl in PARALLEL via Anthropic API with prompt caching.

Pipeline step 2 of 3 — API mode.

Architecture
------------
- Splits turns into batches of --batch-size.
- Spawns up to --concurrency parallel async calls.
- System prompt = skill/SKILL.md + cache_control(ephemeral) so repeat batches
  reuse cached tokens (massive cost savings).
- Each batch returns one JSONL line per turn:
    {"turn_id": int, "delta_vs_prior": float, "delta_vs_atmosphere": float,
     "primary_dim": str, "tags": [str], "rationale": str}
- Streams results to disk as batches complete (resumable).

Usage
-----
    export ANTHROPIC_API_KEY=sk-...
    python scripts/score_turns_api.py \
        --turns       output/_jobs/myjob/turns.jsonl \
        --out         output/_jobs/myjob/turns_scored.jsonl \
        --batch-size  60 \
        --concurrency 5 \
        --model       claude-sonnet-4-6
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterable

SKILL_PATH = Path(__file__).resolve().parent.parent / "skill" / "SKILL.md"


def load_turns(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def load_existing_scored(path: Path) -> set[int]:
    if not path.exists():
        return set()
    seen = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if "turn_id" in d:
                    seen.add(int(d["turn_id"]))
            except json.JSONDecodeError:
                continue
    return seen


def render_batch_text(batch: list[dict]) -> str:
    """Human-readable turn block (the model parses turn_id => score)."""
    lines = []
    for t in batch:
        lines.append(f"[{t['turn_id']}] {t['sender']} ({t['n_msgs']}msgs):")
        lines.append(t["text"])
        lines.append("---")
    return "\n".join(lines)


def build_user_prompt(batch: list[dict]) -> str:
    return (
        "Score each TURN below using the v3.1 schema described in the system "
        "prompt. A turn is one or more consecutive messages from the same sender "
        "concatenated with newlines — treat the whole turn as ONE event.\n\n"
        "Output ONLY one JSON object per turn, in input order, no markdown "
        "fences. Required fields:\n"
        '  {"turn_id": int, "delta_vs_prior": float, '
        '"delta_vs_atmosphere": float, "primary_dim": str, '
        '"tags": [str], "rationale": str}\n\n'
        f"Output exactly {len(batch)} JSONL lines.\n\n"
        "=== TURNS ===\n"
        f"{render_batch_text(batch)}"
    )


def parse_response(text: str, batch_ids: set[int]) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        tid = obj.get("turn_id")
        if tid is None or int(tid) not in batch_ids:
            continue
        # Normalize fields
        out.append({
            "turn_id":             int(tid),
            "delta_vs_prior":      float(obj.get("delta_vs_prior", 0.0)),
            "delta_vs_atmosphere": float(obj.get("delta_vs_atmosphere", 0.0)),
            "primary_dim":         str(obj.get("primary_dim", "engagement")),
            "tags":                obj.get("tags") or [],
            "rationale":           str(obj.get("rationale", "")),
        })
    return out


async def score_one_batch(
    client,
    model: str,
    system_blocks: list[dict],
    batch: list[dict],
    semaphore: asyncio.Semaphore,
    max_retries: int = 4,
) -> list[dict]:
    batch_ids = {t["turn_id"] for t in batch}
    user_prompt = build_user_prompt(batch)
    delay = 2.0
    last_err: Exception | None = None
    async with semaphore:
        for attempt in range(1, max_retries + 1):
            try:
                resp = await client.messages.create(
                    model=model,
                    max_tokens=8192,
                    system=system_blocks,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                text = "".join(
                    b.text for b in resp.content
                    if getattr(b, "type", "") == "text"
                )
                rows = parse_response(text, batch_ids)
                if len(rows) < len(batch):
                    missing = batch_ids - {r["turn_id"] for r in rows}
                    print(f"[WARN] batch first_turn={batch[0]['turn_id']} "
                          f"got {len(rows)}/{len(batch)} rows, "
                          f"missing {sorted(missing)[:6]}...",
                          file=sys.stderr, flush=True)
                return rows
            except Exception as e:
                last_err = e
                print(f"[retry {attempt}/{max_retries}] batch "
                      f"first_turn={batch[0]['turn_id']}: {type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError(
            f"batch first_turn={batch[0]['turn_id']} failed after "
            f"{max_retries} retries: {last_err}"
        )


async def run(args) -> None:
    try:
        from anthropic import AsyncAnthropic
    except ImportError as e:
        raise RuntimeError(
            "Need: pip install 'anthropic>=0.40.0'") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY env var is required")

    turns = load_turns(Path(args.turns))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done = load_existing_scored(out_path) if args.resume else set()
    if done:
        print(f"[resume] skipping {len(done)} already-scored turn_ids")

    pending = [t for t in turns if t["turn_id"] not in done]
    if not pending:
        print("[done] nothing to do")
        return

    batches = [
        pending[i:i + args.batch_size]
        for i in range(0, len(pending), args.batch_size)
    ]
    print(f"[plan] turns={len(pending)} batches={len(batches)} "
          f"batch_size={args.batch_size} concurrency={args.concurrency}")

    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    system_blocks = [
        {
            "type":  "text",
            "text":  skill_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    client = AsyncAnthropic(api_key=api_key)
    semaphore = asyncio.Semaphore(args.concurrency)
    fout = out_path.open("a", encoding="utf-8", newline="\n")
    write_lock = asyncio.Lock()

    completed = 0
    failed_batches: list[int] = []

    async def task(idx: int, batch: list[dict]):
        nonlocal completed
        try:
            t0 = time.time()
            rows = await score_one_batch(
                client, args.model, system_blocks, batch, semaphore,
                max_retries=args.max_retries,
            )
            dur = time.time() - t0
            async with write_lock:
                for r in rows:
                    fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                fout.flush()
            completed += 1
            print(f"[ok] batch {idx + 1}/{len(batches)} "
                  f"first_turn={batch[0]['turn_id']} "
                  f"got={len(rows)}/{len(batch)} "
                  f"({dur:.1f}s) progress={completed}/{len(batches)}",
                  flush=True)
        except Exception as e:
            failed_batches.append(idx)
            print(f"[FAIL] batch {idx + 1}: {e}", file=sys.stderr, flush=True)

    try:
        await asyncio.gather(*[task(i, b) for i, b in enumerate(batches)])
    finally:
        fout.close()

    print(f"[summary] ok={completed - len(failed_batches)} failed={len(failed_batches)}")
    if failed_batches:
        print(f"  failed batch indices: {failed_batches}")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", required=True)
    ap.add_argument("--out",   required=True)
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--batch-size",  type=int, default=60)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--max-retries", type=int, default=4)
    ap.add_argument("--resume", action="store_true",
                    help="skip turn_ids already in --out")
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
