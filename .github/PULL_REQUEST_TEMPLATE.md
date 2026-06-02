## Summary

<!-- What does this PR do? One paragraph. -->

## Type

- [ ] New AI service
- [ ] Bug fix
- [ ] Improvement / refactor
- [ ] Documentation
- [ ] Infrastructure / CI

## Checklist

- [ ] Tests pass: `pytest tests/ -v`
- [ ] Lint passes: `ruff check app/ --ignore=E501,F841`
- [ ] Pricing updated in `app/pricing.py` (if new service)
- [ ] MCP tool registered in `app/mcp_server.py` (if new service)
- [ ] Counts updated in `README.md`, `AGENTS.md`, `mcp.json`, `smithery.yaml`, `server.json`
- [ ] CI is green

## Verification

<!-- How did you test this? Paste curl commands or pytest output. -->

```bash
# Example: test the new endpoint
curl ...
```

## Screenshots

<!-- If UI changes, add screenshots. -->
