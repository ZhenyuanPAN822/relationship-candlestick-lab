"""Convert WeChat-export CSV (PyWxDump-style) → standard RCL CSV.

Filters Type=1 (text). Maps IsSender 1 → 'me', 0 → 'them' (override via CLI).
"""
import argparse, csv, sys
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--me", default="me")
    ap.add_argument("--them", default="them")
    args = ap.parse_args()

    n_in = n_out = 0
    with open(args.input, "r", encoding="utf-8-sig", newline="") as fin, \
         open(args.output, "w", encoding="utf-8", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=["timestamp", "sender", "message"])
        writer.writeheader()
        for row in reader:
            n_in += 1
            if row.get("Type") != "1":
                continue
            text = (row.get("StrContent") or "").strip()
            if not text:
                continue
            sender = args.me if row.get("IsSender") == "1" else args.them
            writer.writerow({
                "timestamp": row.get("StrTime", "").strip(),
                "sender": sender,
                "message": text,
            })
            n_out += 1
    print(f"Read {n_in} rows, wrote {n_out} text messages → {args.output}")

if __name__ == "__main__":
    main()
