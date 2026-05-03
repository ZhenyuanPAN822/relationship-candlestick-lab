from pathlib import Path
import pytest
from relationship_candlestick.parser import parse

EX = Path(__file__).resolve().parent.parent / "examples"

def test_parse_csv():
    df = parse(EX / "sample_chat.csv")
    assert len(df) > 50
    assert set(df.columns) >= {"timestamp", "sender", "message"}
    assert df["timestamp"].is_monotonic_increasing

def test_parse_json():
    df = parse(EX / "sample_chat.json")
    assert len(df) == 9
    assert df.iloc[-1]["message"] == "我也喜欢你"

def test_parse_txt():
    df = parse(EX / "sample_chat.txt")
    assert len(df) == 9
    assert df.iloc[0]["sender"] == "A"

def test_parse_txt_bad(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("this is not a chat line\n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse(p)
