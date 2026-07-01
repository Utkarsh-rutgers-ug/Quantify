
Planned production flow:
```text
Web Service
 └── gunicorn wsgi:app
Worker Service
 └── python worker.py
Database
 └── PostgreSQL
```
This separation matters because production web servers such as Gunicorn may run multiple worker processes. If each web worker starts its own scheduler, the app could accidentally duplicate market data calls and insert repeated samples. A dedicated worker process gives the quote sampler a single owner.
---
## Project Status
The project currently has a working paper trading and market data foundation.
Completed or mostly completed:
- Flask application structure
- Local SQLite database
- Paper trading engine
- Account and position tracking
- Realized/unrealized P&L
- Finnhub quote integration
- Automatic quote collection
- Local quote history
- Multi-range chart views
- Portfolio performance graph
- Rule-based risk advisor
- Frontend dashboard
In progress / planned:
- Separate production web and worker processes
- PostgreSQL compatibility
- Database migrations
- Duplicate quote-sample protection
- Market-hours awareness
- Stale-price detection
- Sampler health/status endpoint
- Improved logging and failure recovery
- Deployment readiness
- News and source-intelligence system
- Experimental market forecasting
---
## Long-Term Vision
The long-term vision for Quantify is to become a broader financial intelligence platform.
Future advisor capabilities may include:
- Traditional quantitative risk formulas
- Portfolio concentration analysis
- Correlation and diversification analysis
- Company and sector news analysis
- Government and central-bank statement tracking
- Source reliability scoring
- Claim extraction from financial news
- Confirmation and contradiction detection across sources
- Market relevance scoring
- Expected-impact scoring
- Explainable citations and uncertainty
A key design principle is that dependable risk analysis should remain separate from experimental forecasting.
For example:
- Risk rating: based on explainable portfolio and market conditions
- Forecasting: experimental, timestamped, and evaluated without look-ahead bias
This separation is important because predictions can be uncertain, but risk explanations should be transparent and defensible.
---
## Local Development
### 1. Clone the repository
```bash
git clone https://github.com/Utkarsh-rutgers-ug/Quantify.git
cd Quantify
```
### 2. Create a virtual environment
```bash
python -m venv .venv
source .venv/bin/activate
```
### 3. Install dependencies
```bash
pip install -r requirements.txt
```
### 4. Create a local `.env` file
Create:
```text
algorithmic_trading/.env
```
Example:
```env
FINNHUB_API_KEY=your_finnhub_key_here
QUOTE_SAMPLE_INTERVAL_SECONDS=30
QUOTE_SAMPLE_MAX_PER_CYCLE=25
APP_PORT=5001
DATABASE_URL=sqlite:///trading.db
```
Do not commit `.env`.
### 5. Run the app
```bash
cd algorithmic_trading
python run.py
```
Open:
```text
http://127.0.0.1:5001
```
---
## Tests
The project includes tests for the trading simulation and quote history logic.
```bash
python test_simulation.py
python test_quote_history.py
```
---
## Security Notes
The following files should not be committed:
```text
.env
.venv/
venv/
instance/
*.db
.idea/
__pycache__/
*.pyc
.DS_Store
*.zip
```
API keys and local database files are intentionally excluded from version control.
---
## What This Project Demonstrates
Quantify demonstrates practical experience with:
- Backend API design
- Financial data modeling
- Paper trading simulation
- Portfolio accounting logic
- Market data integration
- Scheduled background jobs
- Database-backed analytics
- Frontend dashboard development
- Risk analysis foundations
- Production architecture planning
It is both a learning project and a foundation for more advanced fintech, quantitative finance, and market intelligence systems.
