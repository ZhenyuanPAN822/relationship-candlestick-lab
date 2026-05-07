"""Parse chat logs from CSV / JSON / TXT into a normalized DataFrame.

Output schema:
    timestamp (pd.Timestamp), sender (str), message (str)
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import List, Optional

import pandas as pd
from dateutil import parser as dtparser


_TXT_LINE = re.compile(
    r"^\s*(?P<ts>\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)\s+"
    r"(?P<sender>[^:：]+)\s*[:：]\s*(?P<msg>.+?)\s*$"
)


def _to_df(rows: List[dict]) -> pd.DataFrame:
    if not rows:
        raise ValueError("No messages parsed from input.")
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["sender"] = df["sender"].astype(str).str.strip()
    df["message"] = df["message"].astype(str)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


_WECHAT_REQUIRED = {"Type", "IsSender", "StrTime", "StrContent"}


def parse_csv(path: str | Path) -> pd.DataFrame:
    """CSV parser. Auto-detects WeChat-export schema (PyWxDump-style)."""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        rows_raw = list(reader)

    if _WECHAT_REQUIRED.issubset(fields):
        return _parse_wechat_rows(rows_raw)

    rows = []
    for r in rows_raw:
        rows.append({
            "timestamp": r["timestamp"],
            "sender":    r["sender"],
            "message":   r.get("message") or r.get("text") or "",
        })
    return _to_df(rows)


def _parse_wechat_rows(rows_raw: list) -> pd.DataFrame:
    """Convert WeChat-export rows. Keeps Type==1 (text) only.
    sender = 'me' for IsSender==1, else uses Remark/NickName/wxid."""
    rows = []
    other_label = None
    for r in rows_raw:
        if r.get("Type") != "1":
            continue
        text = (r.get("StrContent") or "").strip()
        if not text:
            continue
        if r.get("IsSender") == "1":
            sender = "me"
        else:
            if other_label is None:
                other_label = (
                    (r.get("Remark") or r.get("NickName") or r.get("Sender") or "them").strip()
                )
            sender = other_label
        rows.append({
            "timestamp": (r.get("StrTime") or "").strip(),
            "sender":    sender,
            "message":   text,
        })
    return _to_df(rows)


_JSON_WRAP_KEYS = ("messages", "data", "chat", "chats", "records", "items", "list")
_TS_ALIASES = ("timestamp", "ts", "time", "datetime", "date", "StrTime", "createTime", "create_time", "msgTime", "send_time")
_SENDER_ALIASES = ("sender", "from", "user", "name", "speaker", "author", "talker", "Sender")
_MSG_ALIASES = ("message", "text", "content", "msg", "body", "StrContent")


def _pick(d: dict, keys: tuple) -> Optional[str]:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def parse_json(path: str | Path) -> pd.DataFrame:
    """Parse JSON chat logs.

    Accepts:
      - Top-level list of message objects: [{timestamp, sender, message}, ...]
      - Wrapped: {"messages": [...]}, {"data": [...]}, {"chat": [...]}, etc.
      - JSONL (one JSON object per line)
      - Field aliases: ts/time/datetime/StrTime → timestamp;
                       from/user/name/talker → sender;
                       text/content/msg/StrContent → message

    Rejects (with friendly error):
      - MemoTrace fine-tuning format ([{"conversations": [{role, content}, ...]}, ...])
        — no timestamps, can't build a time-series K-line.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    # Try standard JSON first; fall back to JSONL.
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = []
        for ln, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"JSON parse failed: not valid JSON and not valid JSONL (line {ln}: {e})."
                )

    # Unwrap common container shapes: {"messages": [...]}, {"data": [...]}, etc.
    if isinstance(data, dict):
        for k in _JSON_WRAP_KEYS:
            v = data.get(k)
            if isinstance(v, list):
                data = v
                break
        else:
            raise ValueError(
                "JSON top-level is an object but no recognized list field found "
                f"(looked for: {', '.join(_JSON_WRAP_KEYS)}). "
                "Expected a list of message objects, or an object wrapping one."
            )

    if not isinstance(data, list):
        raise ValueError("JSON input must be a list of message objects (or an object wrapping one).")

    if not data:
        raise ValueError("JSON input is empty.")

    # Detect MemoTrace fine-tuning format and reject with a clear hint.
    if isinstance(data[0], dict) and "conversations" in data[0]:
        raise ValueError(
            "Detected MemoTrace fine-tuning format (list of {'conversations': [...]}). "
            "This format has no timestamps, so it can't be used to build a time-series K-line. "
            "Please re-export from MemoTrace as CSV instead."
        )

    rows = []
    missing_ts = 0
    for i, d in enumerate(data):
        if not isinstance(d, dict):
            raise ValueError(f"JSON item #{i} is not an object: {type(d).__name__}.")
        ts = _pick(d, _TS_ALIASES)
        sender = _pick(d, _SENDER_ALIASES)
        msg = _pick(d, _MSG_ALIASES)
        if ts is None:
            missing_ts += 1
            continue
        if sender is None or msg is None:
            continue
        rows.append({"timestamp": ts, "sender": sender, "message": msg})

    if not rows:
        if missing_ts:
            raise ValueError(
                f"No usable messages: {missing_ts} item(s) had no timestamp field "
                f"(looked for: {', '.join(_TS_ALIASES)}). "
                "K-line requires a timestamp on every message."
            )
        raise ValueError(
            "No usable messages parsed. Each item needs a timestamp, sender, and message field "
            f"(aliases supported: ts/time/StrTime, from/user/talker, text/content/StrContent)."
        )

    return _to_df(rows)


def parse_txt(path: str | Path) -> pd.DataFrame:
    rows = []
    bad: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            m = _TXT_LINE.match(line)
            if not m:
                bad.append(f"line {i}: {line!r}")
                continue
            try:
                ts = dtparser.parse(m.group("ts"))
            except (ValueError, OverflowError):
                bad.append(f"line {i}: bad timestamp {m.group('ts')!r}")
                continue
            rows.append({
                "timestamp": ts,
                "sender":    m.group("sender"),
                "message":   m.group("msg"),
            })
    if not rows:
        raise ValueError(
            "TXT parse failed. Expected lines like:\n"
            "  2026-05-01 20:01 A: 你今天在干嘛\n"
            f"First few problems: {bad[:3]}"
        )
    return _to_df(rows)


def parse(path: str | Path, fmt: Optional[str] = None) -> pd.DataFrame:
    p = Path(path)
    fmt = (fmt or p.suffix.lstrip(".")).lower()
    if fmt == "csv":
        return parse_csv(p)
    if fmt == "json":
        return parse_json(p)
    if fmt == "txt":
        return parse_txt(p)
    raise ValueError(f"Unsupported format: {fmt!r}. Use csv | json | txt.")
