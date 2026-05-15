"""Run on VPS: python3 /tmp/update.py"""
import sys
B = "/opt/agent-api"

# Backup
for f in [f"{B}/.env", f"{B}/app/config.py", f"{B}/app/x402_setup.py", f"{B}/app/mcp_server.py"]:
    with open(f) as src: open(f+".bak","w").write(src.read())
    print(f"backup: {f}.bak")

# 1. .env
with open(f"{B}/.env") as f: c=f.read()
c=c.replace("FACILITATOR_URL=https://x402.org/facilitator","FACILITATOR_URL=https://x402.dexter.cash")
with open(f"{B}/.env","w") as f: f.write(c); print("OK .env")

# 2. config.py
with open(f"{B}/app/config.py") as f: c=f.read()
c=c.replace('"https://x402.org/facilitator"','"https://x402.dexter.cash"')
with open(f"{B}/app/config.py","w") as f: f.write(c); print("OK config.py")

# 3. x402_setup.py
with open(f"{B}/app/x402_setup.py") as f: c=f.read()
c=c.replace("from app.facilitator import DirectFacilitator",
    "from x402.http.facilitator_client import HTTPFacilitatorClient, FacilitatorConfig\nfrom app.facilitator import DirectFacilitator")
c=c.replace("    facilitator = DirectFacilitator(testnet=testnet, pay_to=pay_to_evm)",
    "    if testnet:\n        facilitator = DirectFacilitator(testnet=True, pay_to=pay_to_evm)\n    else:\n        facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=facilitator_url))")
with open(f"{B}/app/x402_setup.py","w") as f: f.write(c); print("OK x402_setup.py")

# 4. mcp_server.py
with open(f"{B}/app/mcp_server.py") as f: c=f.read()
c=c.replace("from app.facilitator import DirectFacilitator",
    "from x402.http.facilitator_client import HTTPFacilitatorClient, FacilitatorConfig\nfrom app.facilitator import DirectFacilitator")
old_fac='facilitator = DirectFacilitator(\n    testnet=settings.testnet,\n    pay_to=settings.pay_to_address_evm,\n)'
new_fac='if settings.testnet:\n    facilitator = DirectFacilitator(testnet=True, pay_to=settings.pay_to_address_evm)\nelse:\n    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=settings.facilitator_url))'
c=c.replace(old_fac, new_fac)
with open(f"{B}/app/mcp_server.py","w") as f: f.write(c); print("OK mcp_server.py")

# Restart
import os
print("\nRestarting agent-api...")
os.system("sudo systemctl restart agent-api && sleep 2 && curl -s http://localhost:8000/health && echo '' && curl -s -X POST http://localhost:8000/api/validate-json -H 'Content-Type: application/json' -d '{}' -w ' HTTP:%{http_code}'")
