"""
Cuisine supply & demand gap analysis for Swiggy Dark Kitchen Opportunity Finder.

Normalises cuisine tags, computes per-area supply scores, estimates city-wide
demand proxies, and produces a ranked gap score DataFrame identifying the best
dark kitchen opportunities across Delhi NCR.

Usage:
    python src/analysis.py
"""

import os
import sys

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.db import (
    create_tables,
    get_all_restaurants,
    get_cuisine_supply as db_get_cuisine_supply,
    upsert_cuisine_supply_batch,
    upsert_gap_scores,
)

console = Console()

# ---------------------------------------------------------------------------
# Cuisine normalisation mapping
# ---------------------------------------------------------------------------
CUISINE_NORMALISATION: dict[str, str] = {
    "north indian": "North Indian",
    "mughlai": "North Indian",
    "punjabi": "North Indian",
    "south indian": "South Indian",
    "dosa": "South Indian",
    "idli": "South Indian",
    "chinese": "Chinese",
    "indo chinese": "Chinese",
    "italian": "Italian",
    "pizza": "Italian",
    "mexican": "Mexican",
    "tex mex": "Mexican",
    "japanese": "Japanese",
    "sushi": "Japanese",
    "korean": "Korean",
    "fast food": "Fast Food",
    "burgers": "Fast Food",
    "healthy": "Healthy",
    "salads": "Healthy",
    "desserts": "Desserts",
    "ice cream": "Desserts",
    "cakes": "Desserts",
    "biryani": "Biryani",
    "cafe": "Cafe",
    "coffee": "Cafe",
}

CSV_PATH: str = os.path.join(os.path.dirname(__file__), "..", "data", "ncr_areas.csv")


def normalise_cuisine(tag: str) -> str:
    """Map a raw cuisine tag to its canonical form.

    Looks up the lowercased tag in CUISINE_NORMALISATION. If not found,
    returns the tag in title-case.

    Args:
        tag: Raw cuisine string from the API or mock data.

    Returns:
        Normalised cuisine name.
    """
    return CUISINE_NORMALISATION.get(tag.strip().lower(), tag.strip().title())


def compute_cuisine_supply(restaurants_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate restaurant data into per-area cuisine supply metrics.

    For each (area, normalised_cuisine) pair, computes:
        - restaurant_count
        - avg_rating (capped at 5.0)
        - total_rating_count
        - weighted_supply_score = restaurant_count × min(avg_rating, 5.0)

    Args:
        restaurants_df: DataFrame from the restaurants table with columns
                        area_name, cuisines (list), rating, rating_count.

    Returns:
        Supply DataFrame with one row per (area_name, cuisine).
    """
    rows: list[dict] = []

    for _, restaurant in restaurants_df.iterrows():
        cuisines = restaurant.get("cuisines", [])
        if isinstance(cuisines, str):
            # PostgreSQL array comes back as Python list via psycopg2,
            # but handle string edge case defensively
            cuisines = [c.strip() for c in cuisines.strip("{}").split(",")]

        for raw_cuisine in cuisines:
            norm = normalise_cuisine(raw_cuisine)
            rows.append({
                "area_name": restaurant["area_name"],
                "cuisine": norm,
                "rating": float(restaurant.get("rating", 0)),
                "rating_count": int(restaurant.get("rating_count", 0)),
            })

    if not rows:
        return pd.DataFrame(columns=[
            "area_name", "cuisine", "restaurant_count", "avg_rating",
            "total_rating_count", "weighted_supply_score",
        ])

    exploded = pd.DataFrame(rows)
    supply = (
        exploded
        .groupby(["area_name", "cuisine"], as_index=False)
        .agg(
            restaurant_count=("rating", "count"),
            avg_rating=("rating", "mean"),
            total_rating_count=("rating_count", "sum"),
        )
    )
    supply["avg_rating"] = supply["avg_rating"].clip(upper=5.0).round(2)
    supply["weighted_supply_score"] = (
        supply["restaurant_count"] * supply["avg_rating"]
    ).round(2)

    return supply


def compute_demand_proxy(supply_df: pd.DataFrame) -> dict[str, float]:
    """Estimate city-wide demand for each cuisine category.

    Demand proxy = mean of total_rating_count across all areas for a cuisine.
    A high city-wide rating count signals high consumer demand.

    Args:
        supply_df: Output of compute_cuisine_supply().

    Returns:
        Dict mapping cuisine name → demand proxy value.
    """
    if supply_df.empty:
        return {}

    demand = (
        supply_df
        .groupby("cuisine", as_index=False)["total_rating_count"]
        .mean()
    )
    return dict(zip(demand["cuisine"], demand["total_rating_count"]))


def compute_gap_scores(
    supply_df: pd.DataFrame,
    demand_proxy: dict[str, float],
    areas_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute opportunity gap scores for every (area, cuisine) combination.

    gap_score = (demand_proxy[cuisine] − supply_score), normalised to 0–100.
    opportunity_tier: >70 → "Gold", 40–70 → "Silver", <40 → "Bronze".

    Args:
        supply_df: Per-area cuisine supply from compute_cuisine_supply().
        demand_proxy: City-wide demand dict from compute_demand_proxy().
        areas_df: NCR areas with pincode, latitude, longitude.

    Returns:
        DataFrame with columns: area_name, pincode, latitude, longitude,
        cuisine, supply_score, demand_proxy, gap_score, opportunity_tier.
    """
    area_lookup: dict[str, dict] = {}
    for _, row in areas_df.iterrows():
        area_lookup[row["area_name"]] = {
            "pincode": str(row["pincode"]),
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }

    all_areas = areas_df["area_name"].unique()
    all_cuisines = list(demand_proxy.keys())

    records: list[dict] = []
    for area in all_areas:
        area_info = area_lookup.get(area, {"pincode": "", "latitude": 0, "longitude": 0})
        for cuisine in all_cuisines:
            mask = (supply_df["area_name"] == area) & (supply_df["cuisine"] == cuisine)
            matched = supply_df.loc[mask]
            supply_score = float(matched["weighted_supply_score"].iloc[0]) if len(matched) > 0 else 0.0
            dp = demand_proxy.get(cuisine, 0.0)

            records.append({
                "area_name": area,
                "pincode": area_info["pincode"],
                "latitude": area_info["latitude"],
                "longitude": area_info["longitude"],
                "cuisine": cuisine,
                "supply_score": supply_score,
                "demand_proxy": dp,
                "raw_gap": dp - supply_score,
            })

    gap_df = pd.DataFrame(records)

    if gap_df.empty:
        gap_df["gap_score"] = []
        gap_df["opportunity_tier"] = []
        return gap_df

    # Normalise gap to 0-100 range
    raw_min = gap_df["raw_gap"].min()
    raw_max = gap_df["raw_gap"].max()
    if raw_max == raw_min:
        gap_df["gap_score"] = 50.0
    else:
        gap_df["gap_score"] = (
            (gap_df["raw_gap"] - raw_min) / (raw_max - raw_min) * 100
        ).round(2)

    # Assign opportunity tiers
    gap_df["opportunity_tier"] = np.where(
        gap_df["gap_score"] > 70, "Gold",
        np.where(gap_df["gap_score"] >= 40, "Silver", "Bronze")
    )

    gap_df = gap_df.drop(columns=["raw_gap"])
    return gap_df


def get_top_opportunities(gap_df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Return the top N dark kitchen opportunities sorted by gap score.

    Args:
        gap_df: Full gap scores DataFrame.
        n: Number of top opportunities to return (default 10).

    Returns:
        DataFrame of top n rows sorted descending by gap_score.
    """
    return gap_df.nlargest(n, "gap_score").reset_index(drop=True)


def run_analysis() -> None:
    """Execute the full analysis pipeline: supply → demand → gaps → DB.

    Reads restaurant data from PostgreSQL, computes all metrics, persists
    results, and prints a summary of top opportunities.
    """
    console.print("\n[bold orange1]📊 Swiggy Dark Kitchen — Gap Analysis[/bold orange1]\n")

    create_tables()

    # Load restaurant data
    restaurants_df = get_all_restaurants()
    if restaurants_df.empty:
        console.print("[bold red]✗ No restaurant data found. Run ingest.py first.[/bold red]")
        sys.exit(1)

    console.print(f"[green]✓ Loaded {len(restaurants_df)} restaurants[/green]")

    # Load areas
    areas_df = pd.read_csv(CSV_PATH)

    # --- Compute supply ---
    console.print("[dim]Computing cuisine supply metrics...[/dim]")
    supply_df = compute_cuisine_supply(restaurants_df)

    # Persist supply to DB
    from src.db import upsert_cuisine_supply_batch
    upsert_cuisine_supply_batch(supply_df)
    console.print(f"[green]✓ {len(supply_df)} cuisine-supply rows computed[/green]")

    # --- Compute demand proxy ---
    console.print("[dim]Estimating demand proxies...[/dim]")
    demand_proxy = compute_demand_proxy(supply_df)
    console.print(f"[green]✓ Demand proxy for {len(demand_proxy)} cuisines[/green]")

    # --- Compute gap scores ---
    console.print("[dim]Computing gap scores...[/dim]")
    gap_df = compute_gap_scores(supply_df, demand_proxy, areas_df)

    # Persist gaps to DB
    upsert_gap_scores(gap_df)
    console.print(f"[green]✓ {len(gap_df)} gap scores computed & saved[/green]")

    # --- Print top opportunities ---
    top = get_top_opportunities(gap_df, n=15)
    table = Table(
        title="🏆 Top 15 Dark Kitchen Opportunities",
        title_style="bold orange1",
        show_lines=True,
    )
    table.add_column("Rank", justify="right", style="bold")
    table.add_column("Area", style="cyan", min_width=20)
    table.add_column("Cuisine", style="yellow")
    table.add_column("Gap Score", justify="right", style="green")
    table.add_column("Tier", justify="center")

    tier_style = {"Gold": "[bold orange1]Gold 🥇[/bold orange1]",
                  "Silver": "[bold white]Silver 🥈[/bold white]",
                  "Bronze": "[bold green]Bronze 🥉[/bold green]"}

    for i, (_, row) in enumerate(top.iterrows(), 1):
        table.add_row(
            str(i),
            row["area_name"],
            row["cuisine"],
            f"{row['gap_score']:.1f}",
            tier_style.get(row["opportunity_tier"], row["opportunity_tier"]),
        )

    console.print()
    console.print(table)

    gold_count = len(gap_df[gap_df["opportunity_tier"] == "Gold"])
    console.print(
        f"\n[bold green]✓ Analysis complete![/bold green] "
        f"Found [bold orange1]{gold_count}[/bold orange1] Gold-tier opportunities.\n"
    )


if __name__ == "__main__":
    run_analysis()
