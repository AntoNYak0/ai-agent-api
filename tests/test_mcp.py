"""Smoke tests for MCP tools — verify payment rejection without credentials."""

import pytest


# Tool names, amounts, and sample args for the 16 individual MCP tools
MCP_TOOLS = [
    ("audit",           "audit_tool",           {"code": "function f() {}"}),
    ("refactor",        "refactor_tool",        {"code": "def x(): pass"}),
    ("docs",            "docs_tool",            {"code": "print(1)"}),
    ("defi",            "defi_tool",            {"protocol": "Uniswap"}),
    ("trading",         "trading_tool",         {"asset": "ETH"}),
    ("solidity-scan",   "solidity_scan_tool",   {"code": "contract A {}"}),
    ("nl-to-sql",       "nl_to_sql_tool",       {"query": "get all items"}),
    ("sql-to-nl",       "sql_to_nl_tool",       {"sql": "SELECT 1"}),
    ("git-summarize",   "git_summarize_tool",   {"diff": "diff --git a/x b/x"}),
    ("translate-code",  "translate_code_tool",  {"code": "print(1)", "source_lang": "python", "target_lang": "typescript"}),
    ("validate-json",   "validate_json_tool",   {"data": "{}"}),
    ("classify-text",   "classify_text_tool",   {"text": "Hello world"}),
    ("extract-data",    "extract_data_tool",    {"text": "john@email.com"}),
    ("generate-regex",  "generate_regex_tool",  {"description": "email"}),
    ("format-data",     "format_data_tool",     {"data": "a,b", "source_format": "csv", "target_format": "json"}),
    ("summarize",       "summarize_tool",       {"text": "Short text."}),
]

COMPOSITE_SKILLS = [
    ("defi-research",       "defi_research_tool",       {"protocol": "Aave", "chain": "ethereum", "onchain_data": "tx: 0x1234"}),
    ("code-health-check",   "code_health_check_tool",   {"code": "def f(): pass"}),
    ("smart-contract-audit","smart_contract_audit_tool",{"code": "contract B {}"}),
    ("data-pipeline",       "data_pipeline_tool",       {"text": "Sample text"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,func_name,args", MCP_TOOLS)
async def test_mcp_tool_requires_payment(name, func_name, args):
    """Every MCP tool should reject calls without payment_tx or api_key."""
    import importlib
    module = importlib.import_module("app.mcp_server")
    tool_fn = getattr(module, func_name)
    result = await tool_fn(**args, payment_tx="", api_key="")
    assert "Payment required" in result or "Payment" in result, \
        f"{func_name}: expected payment rejection, got: {result[:200]}"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,func_name,args", COMPOSITE_SKILLS)
async def test_composite_skill_requires_payment(name, func_name, args):
    """Every composite skill should reject calls without payment_tx or api_key."""
    import importlib
    module = importlib.import_module("app.mcp_server")
    tool_fn = getattr(module, func_name)
    result = await tool_fn(**args, payment_tx="", api_key="")
    assert "Payment required" in result, \
        f"{func_name}: expected payment rejection, got: {result[:200]}"


@pytest.mark.asyncio
async def test_mcp_tool_invalid_api_key():
    """Call with a fake API key should return 'Invalid API key'."""
    from app.mcp_server import validate_json_tool
    result = await validate_json_tool(
        data="{}", payment_tx="", api_key="ak-invalidkey1234567890abcdef"
    )
    assert "Invalid API key" in result


@pytest.mark.asyncio
async def test_mcp_tool_with_api_key_but_zero_balance():
    """Call with a real but zero-balance API key should say 'needs ... credits'."""
    from app.services.credits import generate_api_key, get_balance, spend_credits
    from app.mcp_server import validate_json_tool

    key = generate_api_key()
    # New keys get 50 welcome credits — drain them to test the zero-balance error path
    # spend_credits deducts cents * 10 credits: 5 cents = 50 credits
    if get_balance(key)["credits"] > 0:
        spend_credits(key, get_balance(key)["credits"] // 10)
    assert get_balance(key)["credits"] == 0

    result = await validate_json_tool(
        data="{}", payment_tx="", api_key=key
    )
    assert "needs" in result.lower() or "insufficient" in result.lower(), \
        f"Expected credit requirement message, got: {result[:200]}"
