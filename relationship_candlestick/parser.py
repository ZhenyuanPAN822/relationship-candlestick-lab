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


def parse_json(path: str | Path) -> pd.DataFrame:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON input must be a list of message objects.")
    rows = [{
        "timestamp": d["timestamp"],
        "sender":    d["sender"],
        "message":   d.get("message") or d.get("text") or "",
    } for d in data]
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
