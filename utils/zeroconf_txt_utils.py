import json
from typing import Any, Dict, Mapping


def _decode_txt_component(component: Any) -> str:
    if component is None:
        return ""
    if isinstance(component, bytes):
        return component.decode("utf-8")
    return str(component)


def _decode_json_blob(blob: str):
    candidate = blob.strip()
    if not candidate:
        return {}

    candidates = [candidate]
    if candidate.startswith("{{") and candidate.endswith("}}"):
        candidates.append(candidate[1:-1].strip())

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data

    return None


def decode_txt_properties(properties: Mapping[Any, Any]) -> Dict[str, Any]:
    if not properties:
        return {}

    decoded_pairs: Dict[str, str] = {}
    for raw_key, raw_value in properties.items():
        key = _decode_txt_component(raw_key)
        value = _decode_txt_component(raw_value)
        if value == "":
            decoded_json = _decode_json_blob(key)
            if decoded_json is not None:
                return decoded_json
        decoded_pairs[key] = value

    return decoded_pairs
