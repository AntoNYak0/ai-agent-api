"""MCP Schema-First Validation — strict JSON Schema validation for all MCP tools.

ECC MCP schema-first pattern adapted for agent-api:
  - Builds JSON Schema from pricing.py input definitions (single source of truth)
  - Validates tool parameters BEFORE payment verification
  - Returns clear, structured error messages on validation failure
  - Supports type coercion for string→number where safe

Design: zero-config for new tools — just add to pricing.py and schemas auto-generate.
"""

import re
import json as _json
from typing import Any

from app.pricing import (
    AI_UPTO_SERVICES, EXACT_SERVICES, COMPOSITE_SKILLS,
    _TOOL_NAMES,
)

# Special tools not in pricing dicts but still need schema validation
_SPECIAL_TOOLS_INPUT: dict[str, dict[str, str]] = {
    "run-workflow": {
        "workflow_id": "string",
        "input_text": "string",
    },
}


def _parse_param_type(param_desc: str) -> dict:
    """Parse a param description like 'string' or 'number (optional)' into JSON Schema.

    Supported formats:
      - "string" → {"type": "string"}
      - "number (optional)" → {"type": "number"}
      - "number (optional, default: 30)" → {"type": "number", "default": 30}
      - "integer" → {"type": "integer"}
      - "boolean" → {"type": "boolean"}
      - "[string] (optional)" → {"type": "array", "items": {"type": "string"}}
      - "{source: price} (optional)" → {"type": "object"}
    """
    desc = param_desc.strip()

    # Check optional
    is_optional = "(optional" in desc or desc.endswith("(optional)")

    # Extract type
    if desc.startswith("["):
        items_type = "string"  # default
        inner = desc[1:desc.index("]")]
        if inner == "string":
            items_type = "string"
        elif inner == "number":
            items_type = "number"
        elif inner == "integer":
            items_type = "integer"
        result: dict[str, Any] = {"type": "array", "items": {"type": items_type}}
    elif desc.startswith("{"):
        result = {"type": "object"}
    elif desc.startswith("number"):
        result = {"type": "number"}
    elif desc.startswith("integer"):
        result = {"type": "integer"}
    elif desc.startswith("boolean"):
        result = {"type": "boolean"}
    else:
        result = {"type": "string"}  # default

    # Extract default value
    default_match = re.search(r'default:\s*([^\s)]+)', desc)
    if default_match:
        default_val = default_match.group(1)
        # Try to parse as number
        try:
            if "." in default_val:
                result["default"] = float(default_val)
            else:
                result["default"] = int(default_val)
        except ValueError:
            result["default"] = default_val.strip('"').strip("'")

    return result, is_optional


def build_json_schema_for_tool(tool_name: str) -> dict | None:
    """Build a JSON Schema for tool input parameters from pricing definitions.

    Returns a JSON Schema (draft-07) dict, or None if no schema can be built.
    """
    # 1. Try AI_UPTO_SERVICES
    pricing_key = _TOOL_NAMES.get(tool_name)
    input_def = None

    if pricing_key:
        svc = AI_UPTO_SERVICES.get(pricing_key)
        if svc:
            input_def = svc.get("input", {})
        else:
            svc = EXACT_SERVICES.get(pricing_key)
            if svc:
                input_def = svc.get("input", {})

    # 2. Try COMPOSITE_SKILLS
    if input_def is None:
        # composite skills use underscore names
        composite_key = tool_name.replace("-", "_")
        if composite_key in COMPOSITE_SKILLS:
            input_def = COMPOSITE_SKILLS[composite_key].get("input", {})

    # 3. Try special tools (e.g., run-workflow)
    if input_def is None:
        input_def = _SPECIAL_TOOLS_INPUT.get(tool_name)

    if not input_def:
        return None

    properties = {}
    required: list[str] = []

    for param_name, param_desc in input_def.items():
        prop_schema, is_optional = _parse_param_type(param_desc)
        properties[param_name] = prop_schema
        if not is_optional:
            required.append(param_name)

    # Add standard payment/auth params (always optional — provided by framework)
    for std_param in ["payment_tx", "api_key", "network"]:
        if std_param not in properties:
            properties[std_param] = {"type": "string"}

    schema = {
        "$schema": "https://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": properties,
        "additionalProperties": True,  # Allow extra params (framework adds them)
    }
    if required:
        schema["required"] = required

    return schema


def validate_tool_input(tool_name: str, params: dict) -> str | None:
    """Validate MCP tool input parameters against the generated JSON Schema.

    Args:
        tool_name: MCP tool name (e.g. 'audit', 'amm-security-check')
        params: Dict of parameter names to values

    Returns:
        None if valid, or an error message string if invalid.
    """
    schema = build_json_schema_for_tool(tool_name)
    if schema is None:
        return None  # No schema defined — allow through

    # Coerce numeric strings to numbers
    coerced = {}
    for key, value in params.items():
        prop = schema.get("properties", {}).get(key, {})
        if prop.get("type") in ("number", "integer") and isinstance(value, str) and value:
            try:
                coerced[key] = float(value) if prop["type"] == "number" else int(value)
            except (ValueError, TypeError):
                return (
                    f"Schema validation failed for '{tool_name}': "
                    f"parameter '{key}' must be a {prop['type']}, got string '{value}'"
                )
        elif prop.get("type") == "boolean" and isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                coerced[key] = True
            elif value.lower() in ("false", "0", "no", ""):
                coerced[key] = False
            else:
                return (
                    f"Schema validation failed for '{tool_name}': "
                    f"parameter '{key}' must be a boolean, got '{value}'"
                )
        else:
            coerced[key] = value

    # Check required fields
    for req in schema.get("required", []):
        if req not in coerced or coerced[req] is None or coerced[req] == "":
            return (
                f"Schema validation failed for '{tool_name}': "
                f"required parameter '{req}' is missing or empty"
            )

    # Check types
    for key, value in coerced.items():
        if value is None or value == "":
            continue  # Optional field, skip type check
        prop = schema.get("properties", {}).get(key, {})
        expected_type = prop.get("type")
        if expected_type is None:
            continue  # No type constraint

        if expected_type == "string" and not isinstance(value, str):
            return f"Schema validation failed for '{tool_name}': parameter '{key}' must be a string, got {type(value).__name__}"
        if expected_type == "number" and not isinstance(value, (int, float)):
            return f"Schema validation failed for '{tool_name}': parameter '{key}' must be a number, got {type(value).__name__}"
        if expected_type == "integer" and not isinstance(value, int):
            return f"Schema validation failed for '{tool_name}': parameter '{key}' must be an integer, got {type(value).__name__}"
        if expected_type == "boolean" and not isinstance(value, bool):
            return f"Schema validation failed for '{tool_name}': parameter '{key}' must be a boolean, got {type(value).__name__}"
        if expected_type == "array" and not isinstance(value, list):
            return f"Schema validation failed for '{tool_name}': parameter '{key}' must be an array, got {type(value).__name__}"
        if expected_type == "object" and not isinstance(value, dict):
            return f"Schema validation failed for '{tool_name}': parameter '{key}' must be an object, got {type(value).__name__}"

    return None  # Valid


def get_tool_schema_json(tool_name: str) -> str | None:
    """Get the JSON Schema for a tool as a JSON string (for .well-known exposure)."""
    schema = build_json_schema_for_tool(tool_name)
    if schema is None:
        return None
    return _json.dumps(schema, indent=2)


def list_tools_with_schemas() -> dict[str, dict]:
    """Return {tool_name: schema} for all tools that have schemas defined."""
    result = {}
    # AI upto services
    for pricing_key in AI_UPTO_SERVICES:
        # Find the MCP name
        mcp_name = None
        for k, v in _TOOL_NAMES.items():
            if v == pricing_key:
                mcp_name = k
                break
        if mcp_name:
            schema = build_json_schema_for_tool(mcp_name)
            if schema:
                result[mcp_name] = schema

    # Exact services
    for pricing_key in EXACT_SERVICES:
        mcp_name = None
        for k, v in _TOOL_NAMES.items():
            if v == pricing_key:
                mcp_name = k
                break
        if mcp_name:
            schema = build_json_schema_for_tool(mcp_name)
            if schema:
                result[mcp_name] = schema

    # Composite skills
    for composite_key in COMPOSITE_SKILLS:
        mcp_name = composite_key.replace("_", "-")
        schema = build_json_schema_for_tool(mcp_name)
        if schema:
            result[mcp_name] = schema

    # Special tools
    for tool_name in _SPECIAL_TOOLS_INPUT:
        schema = build_json_schema_for_tool(tool_name)
        if schema:
            result[tool_name] = schema

    return result
