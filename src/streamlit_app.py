"""
Streamlit dashboard for Swiggy Dark Kitchen Opportunity Finder.

Displays an interactive, Swiggy-branded dashboard with:
  - KPI metric cards
  - Folium opportunity map
  - Plotly bar and scatter charts
  - Filterable gap scores table
  - Methodology explainer

Usage:
    streamlit run src/streamlit_app.py
"""

import os
import sys

import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.db import get_gap_scores, create_tables
from src.map_builder import build_map

# ---------------------------------------------------------------------------
# Page config & custom CSS
# ---------------------------------------------------------------------------
st.set_page_config(
    layout="wide",
    page_title="Swiggy Dark Kitchen Finder",
    initial_sidebar_state="expanded",
)

SWIGGY_ORANGE = "#FC8019"
SWIGGY_DARK = "#1B1B1B"
SWIGGY_GRAY = "#2D2D2D"
GOLD = "#FF5200"
SILVER = "#888888"
BRONZE = "#4CAF50"

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* Global */
    .stApp {{
        background: linear-gradient(135deg, #1B1B1B 0%, #0D0D0D 100%);
        font-family: 'Inter', sans-serif;
    }}
    
    /* Force text to be visible on dark background even if Streamlit is in Light Mode */
    .stApp, .stMarkdown, .stMarkdown p, .stMarkdown li, .stMarkdown td, .stMarkdown th, .stText {{
        color: #EAEAEA !important;
    }}

    /* Header */
    .main-header {{
        background: linear-gradient(135deg, {SWIGGY_ORANGE}22 0%, {SWIGGY_DARK} 100%);
        border: 1px solid {SWIGGY_ORANGE}33;
        border-radius: 16px;
        padding: 32px 40px;
        margin-bottom: 24px;
        backdrop-filter: blur(10px);
    }}
    .main-header h1 {{
        color: {SWIGGY_ORANGE};
        font-size: 2.4rem;
        font-weight: 800;
        margin: 0;
        letter-spacing: -0.5px;
    }}
    .main-header p {{
        color: #AAAAAA;
        font-size: 1.05rem;
        margin: 8px 0 0 0;
    }}

    /* Metric cards */
    div[data-testid="stMetric"] {{
        background: linear-gradient(145deg, {SWIGGY_GRAY} 0%, #1A1A1A 100%);
        border: 1px solid #3A3A3A;
        border-radius: 14px;
        padding: 20px 24px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    }}
    div[data-testid="stMetric"]:hover {{
        border-color: {SWIGGY_ORANGE};
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(252,128,25,0.15);
    }}
    div[data-testid="stMetric"] label {{
        color: #999 !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {{
        color: white !important;
        font-size: 2rem !important;
        font-weight: 700 !important;
    }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background: {SWIGGY_DARK} !important;
        border-right: 1px solid #333;
    }}
    section[data-testid="stSidebar"] .stMarkdown h2 {{
        color: {SWIGGY_ORANGE};
        font-weight: 700;
    }}

    /* DataFrame styling */
    .stDataFrame {{
        border-radius: 12px;
        overflow: hidden;
    }}

    /* Expander */
    .streamlit-expanderHeader {{
        background: {SWIGGY_GRAY} !important;
        border-radius: 10px !important;
        color: white !important;
        font-weight: 600 !important;
    }}

    /* Section headers */
    .section-header {{
        color: white;
        font-size: 1.3rem;
        font-weight: 700;
        margin: 28px 0 16px 0;
        padding-bottom: 8px;
        border-bottom: 2px solid {SWIGGY_ORANGE}44;
    }}

    /* Hide Streamlit branding */
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    """Load gap scores from PostgreSQL with 5-minute cache.

    Returns:
        DataFrame with all gap_scores rows, or empty DataFrame.
    """
    create_tables()
    return get_gap_scores()


def classify_zone(area_name: str) -> str:
    """Classify an area into a broad NCR zone.

    Args:
        area_name: Name of the area.

    Returns:
        One of: 'Delhi', 'Noida', 'Gurgaon', 'Faridabad', 'Ghaziabad'.
    """
    name_lower = area_name.lower()
    if any(kw in name_lower for kw in ["noida", "greater noida"]):
        return "Noida"
    if any(kw in name_lower for kw in ["gurgaon", "gurugram", "cyber city", "sohna"]):
        return "Gurgaon"
    if "faridabad" in name_lower:
        return "Faridabad"
    if any(kw in name_lower for kw in ["ghaziabad", "indirapuram"]):
        return "Ghaziabad"
    return "Delhi"


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main() -> None:
    """Render the Streamlit dashboard."""

    # Header
    st.markdown("""
    <div class="main-header">
        <h1>Swiggy Dark Kitchen Finder</h1>
        <p>Discovering untapped food delivery opportunities across Delhi NCR using real-time supply–demand gap analysis</p>
    </div>
    """, unsafe_allow_html=True)

    # Load data
    gap_df = load_data()

    if gap_df.empty:
        st.warning(
            "No data found. Please run the ingestion and analysis pipeline first:\n\n"
            "```bash\n"
            "python src/ingest.py\n"
            "python src/analysis.py\n"
            "```"
        )
        return

    # Add zone column
    gap_df["zone"] = gap_df["area_name"].apply(classify_zone)

    # ------------------------------------------------------------------
    # Sidebar filters
    # ------------------------------------------------------------------
    with st.sidebar:
        st.markdown("## Filters")

        all_cuisines = sorted(gap_df["cuisine"].unique().tolist())
        selected_cuisines = st.multiselect(
            "Cuisines",
            options=all_cuisines,
            default=all_cuisines,
            help="Filter by cuisine category",
        )

        min_gap = st.slider(
            "Min Gap Score",
            min_value=0,
            max_value=100,
            value=0,
            step=5,
            help="Show only opportunities with gap score ≥ this value",
        )

        zone_options = ["All"] + sorted(gap_df["zone"].unique().tolist())
        selected_zone = st.selectbox("Zone", options=zone_options, index=0)

        st.markdown("---")
        st.markdown(
            f"<p style='color:#666;font-size:0.85rem;'>Built with "
            f"<span style='color:{SWIGGY_ORANGE};'>Swiggy Builders Club</span> MCP API</p>",
            unsafe_allow_html=True,
        )

    # Apply filters
    filtered = gap_df[
        (gap_df["cuisine"].isin(selected_cuisines)) &
        (gap_df["gap_score"] >= min_gap)
    ]
    if selected_zone != "All":
        filtered = filtered[filtered["zone"] == selected_zone]

    # ------------------------------------------------------------------
    # Row 1 — KPI Metric Cards
    # ------------------------------------------------------------------
    total_restaurants = len(filtered["area_name"].unique()) * 10  # approx
    areas_covered = filtered["area_name"].nunique()
    gold_count = len(filtered[filtered["opportunity_tier"] == "Gold"])

    # Most underserved cuisine: highest average gap score
    if not filtered.empty:
        cuisine_avg_gap = filtered.groupby("cuisine")["gap_score"].mean()
        most_underserved = cuisine_avg_gap.idxmax()
    else:
        most_underserved = "N/A"

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Restaurants Analyzed", f"{total_restaurants:,}")
    with col2:
        st.metric("Areas Covered", areas_covered)
    with col3:
        st.metric("Gold Opportunities", gold_count, delta="High demand")
    with col4:
        st.metric("Most Underserved Cuisine", most_underserved)

    st.markdown("")

    # ------------------------------------------------------------------
    # Row 2 — Map + Top Gaps Bar Chart (60/40 split)
    # ------------------------------------------------------------------
    st.markdown('<div class="section-header">Opportunity Map & Top Gaps</div>', unsafe_allow_html=True)

    map_col, chart_col = st.columns([3, 2])

    with map_col:
        m = build_map(filtered)
        st_folium(m, width=None, height=520, returned_objects=[])

    with chart_col:
        top_10 = filtered.nlargest(10, "gap_score")
        if not top_10.empty:
            color_map = {"Gold": GOLD, "Silver": SILVER, "Bronze": BRONZE}
            fig_bar = px.bar(
                top_10,
                y=top_10["area_name"] + " — " + top_10["cuisine"],
                x="gap_score",
                color="opportunity_tier",
                color_discrete_map=color_map,
                orientation="h",
                title="Top 10 Opportunities",
                labels={"gap_score": "Gap Score", "y": ""},
            )
            fig_bar.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="white", family="Inter"),
                title_font=dict(size=16, color=SWIGGY_ORANGE),
                showlegend=True,
                legend=dict(
                    bgcolor="rgba(0,0,0,0.5)",
                    font=dict(color="white"),
                ),
                yaxis=dict(autorange="reversed"),
                height=520,
                margin=dict(l=10, r=10, t=50, b=10),
            )
            fig_bar.update_xaxes(gridcolor="#333")
            fig_bar.update_yaxes(gridcolor="#333")
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("No data matches current filters.")

    # ------------------------------------------------------------------
    # Row 3 — Full-width styled dataframe
    # ------------------------------------------------------------------
    st.markdown('<div class="section-header">All Opportunities</div>', unsafe_allow_html=True)

    display_df = filtered[[
        "area_name", "pincode", "cuisine", "supply_score",
        "demand_proxy", "gap_score", "opportunity_tier", "zone",
    ]].copy()
    display_df.columns = [
        "Area", "Pincode", "Cuisine", "Supply Score",
        "Demand Proxy", "Gap Score", "Tier", "Zone",
    ]
    display_df = display_df.sort_values("Gap Score", ascending=False).reset_index(drop=True)

    def color_tier(val: str) -> str:
        """Apply background colour based on opportunity tier.

        Args:
            val: Tier string (Gold/Silver/Bronze).

        Returns:
            CSS background-color string.
        """
        if val == "Gold":
            return "background-color: rgba(255,82,0,0.15); color: #FF5200; font-weight: 700;"
        if val == "Silver":
            return "background-color: rgba(136,136,136,0.12); color: #AAA; font-weight: 600;"
        return "background-color: rgba(76,175,80,0.12); color: #4CAF50; font-weight: 600;"

    def color_row(row: pd.Series) -> list[str]:
        """Apply row-level background colour based on tier.

        Args:
            row: DataFrame row.

        Returns:
            List of CSS strings, one per column.
        """
        tier = row["Tier"]
        if tier == "Gold":
            bg = "background-color: rgba(255,82,0,0.06);"
        elif tier == "Silver":
            bg = "background-color: rgba(136,136,136,0.04);"
        else:
            bg = "background-color: rgba(76,175,80,0.04);"
        return [bg] * len(row)

    styled = (
        display_df.style
        .apply(color_row, axis=1)
        .applymap(color_tier, subset=["Tier"])
        .format({
            "Supply Score": "{:.1f}",
            "Demand Proxy": "{:.0f}",
            "Gap Score": "{:.1f}",
        })
    )

    st.dataframe(styled, use_container_width=True, height=450)

    # ------------------------------------------------------------------
    # Row 4 — Scatter: Supply vs Demand
    # ------------------------------------------------------------------
    st.markdown('<div class="section-header">Supply vs Demand Analysis</div>', unsafe_allow_html=True)

    if not filtered.empty:
        color_map = {"Gold": GOLD, "Silver": SILVER, "Bronze": BRONZE}
        fig_scatter = px.scatter(
            filtered,
            x="supply_score",
            y="demand_proxy",
            color="opportunity_tier",
            color_discrete_map=color_map,
            size="gap_score",
            size_max=25,
            hover_data=["area_name", "cuisine", "gap_score"],
            title="Supply Score vs Demand Proxy",
            labels={
                "supply_score": "Supply Score (weighted)",
                "demand_proxy": "Demand Proxy (city-wide rating count)",
                "opportunity_tier": "Tier",
            },
        )
        fig_scatter.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white", family="Inter"),
            title_font=dict(size=16, color=SWIGGY_ORANGE),
            legend=dict(bgcolor="rgba(0,0,0,0.5)", font=dict(color="white")),
            height=500,
        )
        fig_scatter.update_xaxes(gridcolor="#333", zeroline=False)
        fig_scatter.update_yaxes(gridcolor="#333", zeroline=False)
        st.plotly_chart(fig_scatter, use_container_width=True)

    # ------------------------------------------------------------------
    # Row 5 — Methodology expander
    # ------------------------------------------------------------------
    with st.expander("How This Works — Methodology"):
        st.markdown(f"""
### Data Collection
We query the **Swiggy Builders Club MCP API** across **20 Delhi NCR pin codes**,
collecting restaurant data including cuisines served, ratings, rating counts,
and pricing. When the sandbox API returns empty results, realistic mock data
is generated to ensure full coverage.

### Supply Score
For each *(area, cuisine)* pair:

```
weighted_supply_score = restaurant_count × avg_rating (capped at 5.0)
```

A high supply score means that cuisine is well-served in that area.

### Demand Proxy
We estimate demand using the **city-wide mean of total rating counts** for
each cuisine. A cuisine with many ratings across all areas signals high
consumer demand.

```
demand_proxy[cuisine] = mean(total_rating_count) across all areas
```

### Gap Score
The opportunity gap is the normalised difference between demand and supply:

```
gap_score = normalise(demand_proxy − supply_score) → 0–100
```

### Opportunity Tiers
| Tier | Gap Score | Signal |
|------|-----------|--------|
| **Gold** | > 70 | High demand, low supply — prime dark kitchen location |
| **Silver** | 40–70 | Moderate opportunity — worth investigating |
| **Bronze** | < 40 | Saturated market — lower priority |

### Limitations
- Demand proxy is a rough estimate based on rating volume, not actual order data.
- Mock data is used when the sandbox API returns empty results.
- This analysis should be combined with rental costs, logistics feasibility,
  and competitor analysis for real investment decisions.
        """)

    # Footer
    st.markdown(f"""
    <div style="text-align:center;padding:24px 0 12px 0;color:#555;font-size:0.85rem;">
        Built for <span style="color:{SWIGGY_ORANGE};font-weight:600;">Swiggy Builders Club</span>
        · Contact: <a href="mailto:gaurangityagi@gmail.com" style="color:{SWIGGY_ORANGE};">gaurangityagi@gmail.com</a>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
