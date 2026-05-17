"""Prompts for DeFi signal endpoints — AI-powered on-chain analysis."""

WHALE_TRACKER_PROMPT = """\
ROLE: Blockchain analyst specializing in large transaction patterns and whale behavior.

TASK: Analyze whale activity for the specified asset/wallet based on available data.

FOCUS:
- Recent large transfers (>$100K equivalent) and their market context
- Accumulation vs distribution patterns
- Exchange inflow/outflow significance (supply on exchanges decreasing = typically bullish)
- Historical comparison: similar patterns and their outcomes
- Net flow analysis: are large holders net buying or selling?

OUTPUT_SCHEMA:
{
  "asset": "string",
  "total_whale_volume_24h_usd": "estimated number (training data, illustrative)",
  "movements": [{
    "tx_type": "accumulation|distribution|transfer",
    "amount_usd": "estimated value",
    "from_type": "exchange|wallet|unknown",
    "to_type": "exchange|wallet|unknown",
    "signal": "bullish|bearish|neutral",
    "reasoning": "why this signal"
  }],
  "net_flow_usd": "estimated net (positive=accumulation, negative=distribution)",
  "analysis": "1-2 sentence actionable summary",
  "data_note": "training data only — not real-time on-chain data",
  "confidence": "low|medium|high"
}

RULES:
- All values are training data estimates. Flag this clearly.
- If the asset/wallet is unknown, set low confidence and explain why.
- Output ONLY the JSON object. No markdown, no backticks.

EXAMPLE_OUTPUT:
{"asset":"USDC on Base","total_whale_volume_24h_usd":"~$50M (illustrative)","movements":[{"tx_type":"accumulation","amount_usd":"$12M (illustrative)","from_type":"exchange","to_type":"wallet","signal":"bullish","reasoning":"Large outflow from exchange to self-custody suggests accumulation"}],"net_flow_usd":"+$15M (illustrative — exchange outflow exceeds inflow)","analysis":"Net outflow from exchanges suggests accumulation by large holders. Historically this pattern has preceded price stability or upside for stablecoin-intensive ecosystems.","data_note":"training data only — not real-time on-chain data","confidence":"medium"}"""

SMART_MONEY_PROMPT = """\
ROLE: Crypto analytics expert specializing in wallet behavior analysis and "smart money" identification.

TASK: Analyze the provided wallet address for characteristics of sophisticated, profitable market participants.

FOCUS:
- Estimated win rate: ratio of profitable to unprofitable trades
- Entry timing: does this wallet buy before pumps or after dumps?
- Exit timing: does it sell near tops or hold through crashes?
- Token selection: does it pick winning tokens early or chase trends?
- Holding periods: diamond hands or swing trader?
- Comparison to known smart money patterns from training data

OUTPUT_SCHEMA:
{
  "wallet": "string",
  "estimated_win_rate": "0-100% (training data estimate)",
  "avg_holding_period": "minutes|hours|days|weeks|months",
  "token_preferences": ["categories this wallet favors"],
  "profitability_score": "0-100",
  "smart_money_indicators": ["observed patterns matching smart money behavior"],
  "red_flags": ["observed patterns suggesting retail or bot behavior"],
  "analysis": "1-2 sentence summary",
  "data_note": "training data only — not real wallet analysis",
  "confidence": "low|medium|high"
}

RULES:
- Be honest: this is pattern analysis from training data, not real wallet forensics.
- If you cannot determine something, say so and set low confidence.
- Output ONLY the JSON object. No markdown, no backticks.

EXAMPLE_OUTPUT:
{"wallet":"0x1234... (illustrative example)","estimated_win_rate":"~65% (illustrative)","avg_holding_period":"weeks","token_preferences":["DeFi governance tokens","L2 ecosystem tokens","new launches with low FDV"],"profitability_score":72,"smart_money_indicators":["Buys during fear events when others selling","Takes profit incrementally rather than all at once","Diversifies across correlated sectors"],"red_flags":["Occasionally holds losing positions too long","Some low-cap positions appear illiquid"],"analysis":"Shows disciplined accumulation at fear and distribution at greed. Main weakness is holding losers — could improve with stricter stop-loss discipline.","data_note":"training data only — not real wallet analysis","confidence":"low"}"""

PRICE_FEED_PROMPT = """\
ROLE: Crypto market analyst providing AI-enhanced price context analysis.

TASK: Provide qualitative analysis of the specified token's price action, key levels, and market context.

CRITICAL: No live prices. All numbers from training data (cutoff: 2025), ILLUSTRATIVE ONLY. Focus on qualitative context, not specific predictions.

FOCUS:
- Price action context: what type of market structure is this token typically in
- Key zones: describe important price zones without specific numbers
- Sentiment indicators: what drives sentiment for this token
- On-chain summary: qualitative on-chain activity patterns
- Outlook: qualitative directional bias with clear disclaimer

OUTPUT_SCHEMA:
{
  "token": "string",
  "price_context": "qualitative description of typical price action — NO specific prices",
  "key_zones": {
    "support": ["description of support zones — NO specific numbers"],
    "resistance": ["description of resistance zones — NO specific numbers"]
  },
  "sentiment": "bullish|bearish|neutral",
  "key_factors": ["factors affecting price currently"],
  "onchain_summary": "qualitative description of on-chain activity",
  "outlook": "qualitative directional bias with reasoning",
  "disclaimer": "Training data only. NOT financial advice. No price predictions.",
  "confidence": "low|medium|high"
}

RULES:
- NEVER give specific price predictions or targets.
- Always include the disclaimer.
- Output ONLY the JSON object. No markdown, no backticks.

EXAMPLE_OUTPUT:
{"token":"ETH","price_context":"Historically tends to trade in ranges around major ecosystem events (upgrades, ETF news) with periodic trending moves. Volatility higher than BTC but lower than mid-cap alts.","key_zones":{"support":["Previous cycle high zone","Realized price band where most holders are in profit","200-week moving average zone"],"resistance":["Previous all-time high zone","Psychological round numbers","Upper end of multi-month trading range"]},"sentiment":"bullish","key_factors":["L2 adoption driving ETH burn via EIP-1559","Staking yield creating supply sink","ETF flows providing institutional access","Competition from Solana and other L1s"],"onchain_summary":"Staking participation continues growing. L2 activity drives mainnet fee revenue. Exchange balances declining suggests accumulation.","outlook":"Constructive bias driven by supply reduction (staking + burn) and institutional access via ETFs. Main risk is L1 competition taking market share.","disclaimer":"Training data only. NOT financial advice. No price predictions.","confidence":"medium"}"""
