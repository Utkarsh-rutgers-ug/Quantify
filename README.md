# Quantify

Quantify is a local paper-trading simulator with virtual cash, automatic
Finnhub quote sampling, locally accumulated chart history, and an explainable
rule-based risk advisor.

See [algorithmic_trading/README.md](algorithmic_trading/README.md) for setup,
architecture, API endpoints, and testing instructions.

Never commit API keys. Copy `algorithmic_trading/.env.example` to
`algorithmic_trading/.env` and keep real credentials only in that ignored
local file.
