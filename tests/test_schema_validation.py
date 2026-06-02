"""Tests for MCP Schema-First Validation (ECC pattern adaptation).

Validates:
  - JSON Schema generation from pricing.py input definitions
  - Required param enforcement (fail before payment)
  - Type coercion (string→number, string→boolean)
  - Type errors (string for number, etc.)
  - All 30 tools have schema coverage
  - Validation runs BEFORE _verify_payment
"""

import pytest
from app.services.schema_validator import (
    build_json_schema_for_tool,
    validate_tool_input,
    _parse_param_type,
    list_tools_with_schemas,
    get_tool_schema_json,
)


# ═══════════════════════════════════════════════════════════════════
# _parse_param_type — parsing individual param descriptions
# ═══════════════════════════════════════════════════════════════════

class TestParseParamType:
    def test_simple_string(self):
        schema, optional = _parse_param_type("string")
        assert schema == {"type": "string"}
        assert optional is False

    def test_optional_string(self):
        schema, optional = _parse_param_type("string (optional)")
        assert schema == {"type": "string"}
        assert optional is True

    def test_number(self):
        schema, optional = _parse_param_type("number")
        assert schema == {"type": "number"}
        assert optional is False

    def test_optional_number(self):
        schema, optional = _parse_param_type("number (optional)")
        assert schema == {"type": "number"}
        assert optional is True

    def test_integer_with_default(self):
        schema, optional = _parse_param_type("integer (optional, default: 100)")
        assert schema["type"] == "integer"
        assert schema["default"] == 100
        assert optional is True

    def test_boolean(self):
        schema, optional = _parse_param_type("boolean")
        assert schema == {"type": "boolean"}
        assert optional is False

    def test_string_array(self):
        schema, optional = _parse_param_type("[string] (optional)")
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "string"
        assert optional is True

    def test_number_array(self):
        schema, optional = _parse_param_type("[number] (optional)")
        assert schema["type"] == "array"
        assert schema["items"]["type"] == "number"

    def test_object(self):
        schema, optional = _parse_param_type("{source: price} (optional)")
        assert schema["type"] == "object"
        assert optional is True

    def test_number_default_float(self):
        schema, optional = _parse_param_type("number (optional, default: 0.5)")
        assert schema["default"] == 0.5


# ═══════════════════════════════════════════════════════════════════
# build_json_schema_for_tool — full schema generation
# ═══════════════════════════════════════════════════════════════════

class TestBuildJsonSchema:
    def test_audit_schema(self):
        schema = build_json_schema_for_tool("audit")
        assert schema is not None
        assert schema["type"] == "object"
        assert "code" in schema["properties"]
        assert schema["properties"]["code"]["type"] == "string"
        assert "code" in schema["required"]  # code is required
        assert "context" in schema["properties"]
        # payment_tx, api_key, network auto-added
        assert "payment_tx" in schema["properties"]
        assert "api_key" in schema["properties"]
        assert "network" in schema["properties"]
        assert schema["additionalProperties"] is True

    def test_refactor_schema(self):
        schema = build_json_schema_for_tool("refactor")
        assert schema is not None
        assert "code" in schema["properties"]
        assert "instructions" in schema["properties"]
        assert "code" in schema["required"]

    def test_defi_schema(self):
        schema = build_json_schema_for_tool("defi")
        assert schema is not None
        assert "protocol" in schema["properties"]
        assert "chain" in schema["properties"]
        assert "protocol" in schema["required"]  # required
        assert "chain" not in schema["required"]  # optional (has default)

    def test_trading_schema(self):
        schema = build_json_schema_for_tool("trading")
        assert schema is not None
        assert "asset" in schema["properties"]
        assert "asset" in schema["required"]

    def test_translate_code_schema(self):
        schema = build_json_schema_for_tool("translate-code")
        assert schema is not None
        assert "code" in schema["required"]
        assert "source_lang" in schema["required"]
        assert "target_lang" in schema["required"]

    def test_micro_task_schema(self):
        schema = build_json_schema_for_tool("validate-json")
        assert schema is not None
        assert "data" in schema["properties"]
        assert "data" in schema["required"]

    def test_generate_regex_schema(self):
        schema = build_json_schema_for_tool("generate-regex")
        assert schema is not None
        assert "description" in schema["required"]

    def test_composite_skill_schema(self):
        schema = build_json_schema_for_tool("defi-research")
        assert schema is not None
        assert "protocol" in schema["required"]

    def test_run_workflow_schema(self):
        schema = build_json_schema_for_tool("run-workflow")
        assert schema is not None
        assert "workflow_id" in schema["required"]
        assert "input_text" in schema["required"]

    def test_amm_security_schema(self):
        schema = build_json_schema_for_tool("amm-security-check")
        assert schema is not None
        # Numeric params from pricing input: reserve_in, reserve_out, amount_in, fee_bps, max_slippage_bps
        num_props = sum(
            1 for p in schema["properties"].values()
            if p["type"] in ("number", "integer")
        )
        assert num_props >= 3  # at minimum fee_bps + max_slippage_bps + one more
        # Schema includes pool_address, chain, tokens, oracle_prices, mev_config, pool_params
        assert "pool_address" in schema["properties"]
        assert "fee_bps" in schema["properties"]

    def test_unknown_tool_returns_none(self):
        schema = build_json_schema_for_tool("nonexistent-tool")
        assert schema is None


# ═══════════════════════════════════════════════════════════════════
# validate_tool_input — input validation
# ═══════════════════════════════════════════════════════════════════

class TestValidateToolInput:
    def test_valid_input_passes(self):
        err = validate_tool_input("audit", {"code": "function foo() {}"})
        assert err is None

    def test_missing_required_param_fails(self):
        err = validate_tool_input("audit", {})
        assert err is not None
        assert "audit" in err
        assert "code" in err.lower()
        assert "missing" in err.lower()

    def test_optional_param_missing_ok(self):
        err = validate_tool_input("audit", {"code": "test"})
        assert err is None  # context is optional

    def test_empty_required_param_fails(self):
        err = validate_tool_input("audit", {"code": ""})
        assert err is not None
        assert "code" in err.lower()

    def test_none_required_param_fails(self):
        err = validate_tool_input("translate-code", {
            "code": "test", "source_lang": None, "target_lang": "ts"
        })
        assert err is not None
        assert "source_lang" in err.lower()

    def test_string_for_number_coerces_ok(self):
        """String '50' for a number param should be coerced successfully."""
        schema = build_json_schema_for_tool("solidity-scan")
        if schema and "context" in schema.get("properties", {}):
            # solidity-scan has code (string) + context (string) — use a tool with numbers
            pass
        # Test amm-security which has numeric params
        err = validate_tool_input("amm-security-check", {
            "reserve_in": "1000", "reserve_out": "2000", "amount_in": "50"
        })
        # Should pass — string numbers coerced to numbers
        assert err is None

    def test_invalid_number_string_fails(self):
        err = validate_tool_input("amm-security-check", {"reserve_in": "not_a_number"})
        # reserve_in is optional, so missing it is fine. The bad value would be
        # caught if it were required. Let's test with a number param that IS required...
        # Actually in amm-security all params are optional. Let's check that coercion
        # doesn't crash on invalid string.
        # "not_a_number" → coerced via float() → ValueError → error
        # But reserve_in is optional and has default 0...
        # The coercion happens in validate_tool_input, which tries float("not_a_number")
        # and returns an error.
        assert err is not None
        assert "reserve_in" in err.lower()

    def test_boolean_string_coercion(self):
        """String 'true'/'false' for boolean params."""
        # amm-security has same_block: bool
        err = validate_tool_input("amm-security-check", {"same_block": "true"})
        assert err is None  # should coerce string "true" → True

        err = validate_tool_input("amm-security-check", {"same_block": "false"})
        assert err is None

    def test_invalid_boolean_string_fails(self):
        err = validate_tool_input("amm-security-check", {"same_block": "maybe"})
        assert err is not None
        assert "same_block" in err.lower()

    def test_type_mismatch_detected(self):
        """Passing a dict for a string param."""
        # FastMCP won't normally do this, but our validator should catch it
        # Need to pass actual dict - but strings in JSON context...
        err = validate_tool_input("audit", {"code": 123})  # number for string
        assert err is not None
        assert "code" in err.lower()
        assert "string" in err.lower()

    def test_additional_properties_allowed(self):
        """Extra params not in schema should be ignored (no error)."""
        err = validate_tool_input("audit", {
            "code": "test",
            "extra_unknown_param": "value",
            "another_one": 42,
        })
        assert err is None

    def test_unknown_tool_passes_through(self):
        err = validate_tool_input("nonexistent-tool", {"whatever": "test"})
        assert err is None  # no schema → allow through

    def test_payment_params_always_allowed(self):
        """payment_tx, api_key, network are auto-added as optional strings."""
        err = validate_tool_input("audit", {
            "code": "test",
            "payment_tx": "0xdead",
            "api_key": "sk-123",
            "network": "eip155:8453",
        })
        assert err is None


# ═══════════════════════════════════════════════════════════════════
# Validation ordering: schema check BEFORE payment
# ═══════════════════════════════════════════════════════════════════

class TestValidationBeforePayment:
    """Schema validation must fail-fast BEFORE _verify_payment is called."""

    def test_audit_missing_code_fails_before_payment(self):
        """Missing required 'code' → error, NOT a payment-required message."""
        err = validate_tool_input("audit", {})
        assert err is not None
        # Error is schema validation, not payment
        assert "Schema validation failed" in err
        assert "payment" not in err.lower()

    def test_translate_code_missing_langs(self):
        """Both source_lang and target_lang required."""
        err = validate_tool_input("translate-code", {"code": "test"})
        assert err is not None
        missing_fields = err.lower()
        # Should mention at least one of the missing fields
        assert "source_lang" in missing_fields or "target_lang" in missing_fields

    def test_format_data_missing_formats(self):
        """source_format and target_format are required."""
        err = validate_tool_input("format-data", {"data": "test"})
        assert err is not None
        missing = err.lower()
        assert "source_format" in missing or "target_format" in missing

    def test_workflow_missing_id(self):
        """workflow_id is required."""
        err = validate_tool_input("run-workflow", {"input_text": "test"})
        assert err is not None
        assert "workflow_id" in err.lower()

    def test_workflow_missing_input_text(self):
        """input_text is required."""
        err = validate_tool_input("run-workflow", {"workflow_id": "wf-123"})
        assert err is not None
        assert "input_text" in err.lower()


# ═══════════════════════════════════════════════════════════════════
# Schema coverage — all tools
# ═══════════════════════════════════════════════════════════════════

class TestSchemaCoverage:
    """Every MCP tool should have a schema generated from pricing.py."""

    def test_all_tools_have_schemas(self):
        schemas = list_tools_with_schemas()
        tool_names = sorted(schemas.keys())

        # All upto services + exact services + composite skills + run-workflow
        assert len(tool_names) >= 25, f"Expected ≥25 tools, got {len(tool_names)}: {tool_names}"

    def test_major_tools_covered(self):
        schemas = list_tools_with_schemas()
        required_tools = [
            "audit", "refactor", "docs", "defi", "trading",
            "solidity-scan", "whale-tracker", "smart-money", "price-feed",
            "agent-audit", "contract-verify", "security-score",
            "nl-to-sql", "sql-to-nl", "git-summarize", "translate-code",
            "data-feed", "debug-log", "amm-security-check",
            "validate-json", "classify-text", "extract-data",
            "generate-regex", "format-data", "summarize",
            "defi-research", "code-health-check", "smart-contract-audit",
            "data-pipeline", "run-workflow",
        ]
        for tool in required_tools:
            assert tool in schemas, f"Missing schema for tool: {tool}"

    def test_all_schemas_are_valid_json_schema(self):
        schemas = list_tools_with_schemas()
        for tool_name, schema in schemas.items():
            assert schema["type"] == "object", f"{tool_name}: must be object type"
            assert "properties" in schema, f"{tool_name}: must have properties"
            assert "$schema" in schema, f"{tool_name}: must have $schema"
            for prop_name, prop_schema in schema["properties"].items():
                assert "type" in prop_schema, \
                    f"{tool_name}.{prop_name}: missing type"

    def test_get_tool_schema_json(self):
        json_str = get_tool_schema_json("audit")
        assert json_str is not None
        assert '"type": "object"' in json_str
        assert '"audit"' not in json_str  # not in the schema itself


# ═══════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_params_dict(self):
        err = validate_tool_input("audit", {})
        assert err is not None

    def test_none_params_in_optional(self):
        """None value for optional param — should be OK (treated as missing)."""
        err = validate_tool_input("audit", {"code": "test", "context": None})
        assert err is None

    def test_zero_as_number(self):
        """0 is a valid number, not empty."""
        err = validate_tool_input("amm-security-check", {"reserve_in": 0})
        assert err is None  # 0 is valid, but it's optional...

    def test_negative_number(self):
        err = validate_tool_input("amm-security-check", {"reserve_in": -100})
        assert err is None  # schema doesn't specify min, so negative is valid type-wise

    def test_very_long_string(self):
        long_str = "x" * 100_000
        err = validate_tool_input("audit", {"code": long_str})
        assert err is None  # no maxLength constraint

    def test_unicode_params(self):
        err = validate_tool_input("audit", {"code": "функция привет() {}"})
        assert err is None

    def test_special_chars(self):
        err = validate_tool_input("audit", {"code": "function foo() { return '<script>'; }"})
        assert err is None


# ═══════════════════════════════════════════════════════════════════
# Integration: MCP server uses _v() helper for all tools
# ═══════════════════════════════════════════════════════════════════

class TestMCPIntegration:
    def test_v_helper_exists(self):
        from app.mcp_server import _v
        assert callable(_v)

    def test_v_helper_validates_correctly(self):
        from app.mcp_server import _v
        err = _v("audit", {"code": "test"})
        assert err is None

        err = _v("audit", {})
        assert err is not None

    def test_all_tool_functions_have_validation(self):
        """Verify every @mcp.tool function calls _v() before _verify_payment."""
        import inspect
        from app import mcp_server as mcp_mod

        # Get all tool functions (decorated with @mcp.tool)
        tool_funcs = []
        for name in dir(mcp_mod):
            if name.endswith("_tool") and callable(getattr(mcp_mod, name)):
                tool_funcs.append(name)

        assert len(tool_funcs) >= 30, f"Expected ≥30 tool functions, got {len(tool_funcs)}"

        for func_name in tool_funcs:
            func = getattr(mcp_mod, func_name)
            source = inspect.getsource(func)
            # Every tool should call _v() somewhere before _verify_payment
            assert "_v(" in source, \
                f"{func_name}: missing _v() validation call"
            # _v must appear before _verify_payment
            v_pos = source.find("_v(")
            verify_pos = source.find("_verify_payment")
            assert v_pos < verify_pos, \
                f"{func_name}: _v() must be called BEFORE _verify_payment (got _v at {v_pos}, verify at {verify_pos})"
