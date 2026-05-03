# Turn-based Scoring Pipeline

For long chat datasets where one-LLM-call-per-message is too slow / too
expensive. Aggregates consecutive same-sender messages into TURNS, scores
each turn once, then expands back to message-level for the K-line system.

## Components

| Script | Role |
|---|---|
| `preprocess_turns.py`   | raw msgs → `auto_scored.jsonl` (trivial) + `turns.jsonl` |
| `score_turns_api.py`    | scores turns via Anthropic SDK with **async parallel batches + prompt caching** |
| `score_turns_dispatch.py` | splits turns into per-batch input files for **subagent fan-out** (Claude Code / Codex / etc.) |
| `expand_turns.py`       | turn-level scores → original message-level `scored.jsonl` |
| `pipeline_turns.py`     | end-to-end orchestrator (`--mode api` / `--mode subagent` / `--mode finalize`) |

## Aggregation rules

1. **Trivial messages** (single char / pure URL / empty) — skip aggregation,
   go straight to `auto_scored.jsonl` with `-0.2/-0.2/engagement/[]/""`.
2. **Substantive messages** — group consecutive same-sender messages whose
   neighboring timestamps are ≤ `--gap-min` minutes apart (default 10).
3. **One turn = one event.** Joined with `\n` between source messages.
4. **Expand-back rule.** When mapping turn scores back to original `i`:
   the FIRST message in the turn carries the full delta; every other
   message in the turn gets `0/0/engagement/[]/""`.
   This matches the K-line semantics: one event = one bar contribution.

## API mode (default; one machine, parallel)

```bash
export ANTHROPIC_API_KEY=sk-...

python scripts/pipeline_turns.py \
    --input   output/_jobs/myjob/messages.jsonl \
    --out-dir output/_jobs/myjob/ \
    --mode    api \
    --batch-size 60 \
    --concurrency 5 \
    --model claude-sonnet-4-6
```

Knobs:
- `--batch-size`  — turns per API call. Higher = fewer calls but each call
  slower & token-heavier. 50–100 is the sweet spot.
- `--concurrency` — parallel in-flight batches. Cap by your tier rate-limit.
  5 is safe; bump to 10–20 on tier 3+.
- `--resume`      — skip turn_ids already present in `turns_scored.jsonl`
  (safe to re-run after a crash).

The system prompt (skill/SKILL.md) is sent with `cache_control: ephemeral`,
so after the first batch every subsequent batch reuses the cached prompt
tokens (saves ~90% on system tokens, paid at 10% the rate).

## Subagent mode (Claude Code / Codex fan-out)

When you'd rather have multiple subagents each handle a batch:

```bash
# Step A: write batch input files + a manifest
python scripts/pipeline_turns.py \
    --input   output/_jobs/myjob/messages.jsonl \
    --out-dir output/_jobs/myjob/ \
    --mode    subagent \
    --batch-size 60
```

This produces:
```
output/_jobs/myjob/batches/
  batch_001_input.txt
  batch_002_input.txt
  ...
  manifest.json     # contains the suggested subagent prompt per batch
```

Now in your CLI fan out subagents in parallel — each one reads its
`batch_NNN_input.txt`, scores it, writes `batch_NNN_output.jsonl`.

Once all subagent outputs exist:

```bash
# Step B: gather + expand
python scripts/pipeline_turns.py \
    --input   output/_jobs/myjob/messages.jsonl \
    --out-dir output/_jobs/myjob/ \
    --mode    finalize
```

## Output

```
output/_jobs/<job>/
├── auto_scored.jsonl         # trivial messages
├── turns.jsonl               # aggregated turns
├── turns_meta.json           # stats
├── turns_scored.jsonl        # one row per turn (LLM output)
├── batches/                  # only if --mode subagent
│   ├── batch_001_input.txt
│   ├── batch_001_output.jsonl
│   └── manifest.json
└── scored_v31_turns.jsonl    # final, message-level, ready for K-line
```

## Performance reference

For a 9322-message dataset:
- Sequential 200/batch (legacy): ~25 batches → **~12 min**
- Turn-based 60/batch + 5 parallel + cache: **~3–5 min**, ~30% the token cost

## Resume / fault tolerance

API mode writes `turns_scored.jsonl` in append mode. If it crashes:
```bash
python scripts/pipeline_turns.py ... --mode api --resume
```
This re-reads existing `turn_id`s and only scores the missing ones.

Subagent mode is naturally checkpointed: every batch's output file is
independent. Re-run only failed batches.
