"""
Folium map builder for Swiggy Dark Kitchen Opportunity Finder.

Generates an interactive HTML map of Delhi NCR with circle markers colour-coded
by opportunity tier (Gold / Silver / Bronze). Each marker popup displays the
area name, top 3 cuisine gaps, and a tier badge.

Usage:
    python src/map_builder.py
"""

import os
import sys

import folium
import pandas as pd
from rich.console import Console

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.db import get_gap_scores

console = Console()

# Swiggy brand + tier colours
TIER_COLOURS: dict[str, str] = {
    "Gold": "#FF5200",
    "Silver": "#888888",
    "Bronze": "#4CAF50",
}

TIER_PRIORITY: dict[str, int] = {
    "Gold": 3,
    "Silver": 2,
    "Bronze": 1,
}

OUTPUT_DIR: str = os.path.join(os.path.dirname(__file__), "..", "outputs")
OUTPUT_PATH: str = os.path.join(OUTPUT_DIR, "opportunity_map.html")


def build_map(gap_df: pd.DataFrame) -> folium.Map:
    """Build a Folium map with circle markers for each NCR area.

    Markers are coloured by the best (highest-priority) opportunity tier
    found in that area. Popups list the top 3 cuisine gaps with scores.

    Args:
        gap_df: DataFrame from gap_scores table with columns: area_name,
                pincode, latitude, longitude, cuisine, gap_score,
                opportunity_tier.

    Returns:
        Configured Folium Map object.
    """
    # Centre on Delhi NCR
    m = folium.Map(
        location=[28.6139, 77.2090],
        zoom_start=10,
        tiles="CartoDB dark_matter",
        attr="Swiggy Dark Kitchen Finder",
    )

    # Group by area
    areas = gap_df.groupby("area_name")

    for area_name, area_group in areas:
        lat = area_group["latitude"].iloc[0]
        lng = area_group["longitude"].iloc[0]
        pincode = area_group["pincode"].iloc[0]

        # Determine best tier for this area
        best_tier = "Bronze"
        best_priority = 0
        for tier in area_group["opportunity_tier"].unique():
            if TIER_PRIORITY.get(tier, 0) > best_priority:
                best_priority = TIER_PRIORITY[tier]
                best_tier = tier

        colour = TIER_COLOURS.get(best_tier, "#888888")

        # Top 3 cuisine gaps for popup
        top_3 = area_group.nlargest(3, "gap_score")
        popup_lines = [
            f"<div style='font-family:Inter,sans-serif;min-width:220px;'>"
            f"<h4 style='margin:0 0 6px 0;color:#FC8019;'>{area_name}</h4>"
            f"<p style='margin:0 0 4px 0;color:#666;font-size:12px;'>📍 {pincode}</p>"
            f"<hr style='margin:6px 0;border-color:#eee;'>"
        ]

        tier_emoji = {"Gold": "🥇", "Silver": "🥈", "Bronze": "🥉"}
        for _, row in top_3.iterrows():
            emoji = tier_emoji.get(row["opportunity_tier"], "")
            popup_lines.append(
                f"<div style='margin:4px 0;font-size:13px;'>"
                f"<b>{row['cuisine']}</b> — Gap: {row['gap_score']:.1f} "
                f"<span style='color:{TIER_COLOURS.get(row['opportunity_tier'], '#888')};'>"
                f"{emoji} {row['opportunity_tier']}</span></div>"
            )

        popup_lines.append(
            f"<div style='margin-top:8px;padding:4px 8px;background:{colour};"
            f"color:white;border-radius:4px;text-align:center;font-weight:bold;'>"
            f"Best Tier: {best_tier}</div></div>"
        )

        popup_html = "\n".join(popup_lines)

        folium.CircleMarker(
            location=[lat, lng],
            radius=12 if best_tier == "Gold" else 9 if best_tier == "Silver" else 6,
            color=colour,
            fill=True,
            fill_color=colour,
            fill_opacity=0.7,
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=f"{area_name} — {best_tier}",
        ).add_to(m)

    # Add legend
    legend_html = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:1000;
         background:rgba(0,0,0,0.85);padding:16px 20px;border-radius:10px;
         font-family:Inter,sans-serif;color:white;font-size:13px;
         box-shadow:0 4px 12px rgba(0,0,0,0.3);">
        <h4 style="margin:0 0 10px 0;color:#FC8019;">🍳 Opportunity Tiers</h4>
        <div style="margin:4px 0;"><span style="color:#FF5200;">●</span> Gold — Gap &gt; 70</div>
        <div style="margin:4px 0;"><span style="color:#888;">●</span> Silver — Gap 40–70</div>
        <div style="margin:4px 0;"><span style="color:#4CAF50;">●</span> Bronze — Gap &lt; 40</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m


def save_map(m: folium.Map) -> str:
    """Save the Folium map to an HTML file.

    Creates the outputs/ directory if it does not exist.

    Args:
        m: Folium Map object.

    Returns:
        Absolute path to the saved HTML file.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    m.save(OUTPUT_PATH)
    return os.path.abspath(OUTPUT_PATH)


def generate_opportunity_map() -> str:
    """End-to-end map generation: load gap scores → build map → save.

    Returns:
        Path to the saved HTML map file.

    Raises:
        SystemExit: If no gap score data is available.
    """
    gap_df = get_gap_scores()
    if gap_df.empty:
        console.print("[bold red]✗ No gap scores found. Run analysis.py first.[/bold red]")
        sys.exit(1)

    m = build_map(gap_df)
    path = save_map(m)
    return path


if __name__ == "__main__":
    console.print("\n[bold orange1]🗺️  Swiggy Dark Kitchen — Map Builder[/bold orange1]\n")
    path = generate_opportunity_map()
    console.print(f"[bold green]✓ Map saved to {path}[/bold green]\n")
