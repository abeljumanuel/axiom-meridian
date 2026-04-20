"""Unit tests for serialization utilities."""

import json

import pytest

from meridian.utils.serializers import json_encode, serialize, toon_encode


def test_json_encode_list():
    records = [
        {"code": "RN-001", "text": "Rule one"},
        {"code": "RN-002", "text": "Rule two"},
    ]
    result = json_encode(records)
    parsed = json.loads(result)
    assert parsed == records


def test_toon_encode_simple():
    records = [
        {"f1": "a", "f2": "b", "f3": "c"},
        {"f1": "d", "f2": "e", "f3": "f"},
    ]
    result = toon_encode(records, ["f1", "f2", "f3"])
    lines = result.split("\n")
    assert lines[0] == "items[2]{f1,f2,f3}:"
    assert lines[1] == "  a,b,c"
    assert lines[2] == "  d,e,f"


def test_toon_encode_commas():
    records = [{"f1": "val,ue"}]
    result = toon_encode(records, ["f1"])
    assert '"val,ue"' in result


def test_toon_encode_none():
    records = [{"f1": None}]
    result = toon_encode(records, ["f1"])
    lines = result.split("\n")
    assert lines[1] == "  "


def test_toon_encode_bool():
    records = [{"f1": True, "f2": False}]
    result = toon_encode(records, ["f1", "f2"])
    lines = result.split("\n")
    assert lines[1] == "  true,false"


def test_serialize_router_json():
    records = [{"x": 1}]
    result = serialize(records, format="json")
    assert json.loads(result) == records


def test_serialize_router_toon():
    records = [{"x": 1}]
    result = serialize(records, format="toon", fields=["x"])
    assert result.startswith("items[1]{x}:")


def test_serialize_router_invalid():
    with pytest.raises(ValueError, match="Unknown format"):
        serialize([], format="xml")


def test_serialize_toon_without_fields():
    with pytest.raises(ValueError, match="fields parameter is required"):
        serialize([], format="toon")
