"""Parse model JSON without destroying code fences inside question strings."""
import json
import re


def parse_json_response(content):
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*\n?", "", content, count=1)
            content = re.sub(r"\s*```\s*$", "", content).strip()
        starts = [position for position in (content.find("{"), content.find("[")) if position >= 0]
        if not starts:
            return json.loads(content)  # Raise the normal JSON error for retry handling.
        result, _ = json.JSONDecoder().raw_decode(content[min(starts):])
        return result
