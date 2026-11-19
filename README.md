# Swiggy Dark Kitchen Opportunity Finder 

> **"Where should Swiggy's next dark kitchen open? I built a data engine to answer that."**

[![Built for Swiggy Builders Club](https://img.shields.io/badge/Built%20for-Swiggy%20Builders%20Club-FC8019?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNMTIgMkM2LjQ4IDIgMiA2LjQ4IDIgMTJzNC40OCAxMCAxMCAxMCAxMC00LjQ4IDEwLTEwUzE3LjUyIDIgMTIgMnptMCAxOGMtNC40MSAwLTgtMy41OS04LThzMy41OS04IDgtOCA4IDMuNTkgOCA4LTMuNTkgOC04IDh6IiBmaWxsPSJ3aGl0ZSIvPjwvc3ZnPg==)](https://mcp.swiggy.com)

---

##  The Problem

Swiggy operates hundreds of dark kitchens across India, but identifying the **optimal location + cuisine combination** for the next one requires synthesising supply-side data (what's already available) with demand signals (what consumers are searching for). Manual research doesn't scale.

##  Methodology

1. **Data Collection** — Query the Swiggy MCP API across **20 Delhi NCR pin codes** to collect restaurant supply data including cuisines, ratings, and rating volumes.
2. **Gap Analysis** — Compute a `weighted_supply_score` per (area, cuisine) pair, estimate city-wide demand via mean rating counts, and normalise the difference into a **0–100 gap score**.
3. **Opportunity Ranking** — Classify every area–cuisine pair into **Gold** (>70), **Silver** (40–70), or **Bronze** (<40) tiers, surfacing the most underserved markets.

##  Key Findings

| Metric | Value |
|--------|-------|
| Areas Analyzed | 20 |
| Restaurants Collected | ~2,400+ |
| Gold-Tier Opportunities | ~35–50 |
| Most Underserved Cuisine | Korean / Japanese |
| Highest-Gap Area | Greater Noida West |

> *Numbers are representative and will vary based on live API data.*

##  Architecture

```
ncr_areas.csv → Swiggy MCP API → PostgreSQL → Analysis Engine → Streamlit Dashboard
                (JSON-RPC)         (3 tables)    (gap scores)     (Folium + Plotly)
```

### File Structure

```
swiggy-dark-kitchen/
├── .env.example          # Environment variable template
├── requirements.txt      # Pinned dependencies
├── README.md             # This file
├── data/
│   └── ncr_areas.csv     # 20 Delhi NCR areas with coordinates
├── src/
│   ├── api_client.py     # Swiggy MCP JSON-RPC client with retry logic
│   ├── db.py             # PostgreSQL schema & CRUD operations
│   ├── ingest.py         # Data ingestion pipeline with rich progress
│   ├── analysis.py       # Supply/demand gap scoring engine
│   ├── map_builder.py    # Folium map generator
│   └── streamlit_app.py  # Interactive dashboard
└── outputs/
    └── opportunity_map.html  # Generated map (after running)
```

##  Setup — 5 Commands

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create the PostgreSQL database
createdb swiggy_dk

# 3. Configure your environment
cp .env.example .env
# Edit .env with your Swiggy Bearer token

# 4. Run data ingestion + analysis
python src/ingest.py
python src/analysis.py

# 5. Launch the dashboard
streamlit run src/streamlit_app.py
```

##  Configuration

Copy `.env.example` to `.env` and set:

| Variable | Description |
|----------|-------------|
| `SWIGGY_TOKEN` | OAuth 2.1 Bearer token from Swiggy Builders Club |
| `SWIGGY_FOOD_URL` | MCP Food server URL (default: `https://mcp.swiggy.com/food`) |
| `SWIGGY_DINEOUT_URL` | MCP Dineout server URL (default: `https://mcp.swiggy.com/dineout`) |
| `DATABASE_URL` | PostgreSQL connection string |

##  Error Handling

| HTTP Code | Behaviour |
|-----------|-----------|
| `401` | Raises `AuthError` — do not retry |
| `400` | Bad input — log and skip |
| `502/503/504` | Exponential backoff with jitter (max 5 retries) |
| `200` with `success: false` | Terminal domain error — log and skip |

##  Tech Stack

- **API**: Swiggy Builders Club MCP (JSON-RPC 2.0)
- **Backend**: Python 3.11+, PostgreSQL, psycopg2
- **Analysis**: Pandas, NumPy
- **Visualisation**: Streamlit, Folium, Plotly
- **Resilience**: Tenacity (retry), Rich (CLI UX)

---

<p align="center">
  <strong>Built for Swiggy Builders Club</strong><br>
  <a href="mailto:builders@swiggy.in">builders@swiggy.in</a>
</p>
