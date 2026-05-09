"""
Data ingestion pipeline for Swiggy Dark Kitchen Opportunity Finder.

Reads NCR areas from CSV, queries the Swiggy MCP API (or generates mock data),
upserts results into PostgreSQL, and prints a rich summary table.

Usage:
    python src/ingest.py
"""

import os
import sys

import pandas as pd
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.api_client import SwiggyMCPClient, AuthError
from src.db import create_tables, upsert_restaurant

console = Console()

# The 6 most underrepresented cuisines to probe specifically
UNDERREPRESENTED_CUISINES: list[str] = [
    "Korean", "Japanese", "Mexican", "Italian", "Healthy", "Desserts",
]

CSV_PATH: str = os.path.join(os.path.dirname(__file__), "..", "data", "ncr_areas.csv")


def load_areas() -> pd.DataFrame:
    """Load NCR areas from the hardcoded CSV file.

    Returns:
        DataFrame with columns: area_name, pincode, latitude, longitude.

    Raises:
        FileNotFoundError: If data/ncr_areas.csv is missing.
    """
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f"Area CSV not found at {CSV_PATH}")
    return pd.read_csv(CSV_PATH)


def ingest_area(
    client: SwiggyMCPClient,
    area_name: str,
    pincode: str,
    latitude: float,
    longitude: float,
) -> dict:
    """Ingest all restaurant data for a single area.

    Calls the Dineout search by locality, plus targeted cuisine searches
    for underrepresented categories. De-duplicates by restaurant ID before
    upserting to the database.

    Args:
        client: Initialised SwiggyMCPClient.
        area_name: Human-readable area name.
        pincode: Area postal code.
        latitude: Area centroid latitude.
        longitude: Area centroid longitude.

    Returns:
        Summary dict with keys: area, count, cuisines, mock_used.
    """
    seen_ids: set[str] = set()
    all_restaurants: list[dict] = []
    mock_used: bool = False

    # --- Primary area search ---
    area_results = client.search_restaurants_by_area(area_name, latitude, longitude)
    for r in area_results:
        if r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            all_restaurants.append(r)
        if r["id"].startswith("mock_"):
            mock_used = True

    # --- Targeted underrepresented cuisine searches ---
    for cuisine in UNDERREPRESENTED_CUISINES:
        cuisine_results = client.search_cuisine_in_area(cuisine, latitude, longitude)
        for r in cuisine_results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                all_restaurants.append(r)
            if r["id"].startswith("mock_"):
                mock_used = True

    # --- Upsert to database ---
    all_cuisines: set[str] = set()
    records_to_insert = []
    for r in all_restaurants:
        all_cuisines.update(r.get("cuisines", []))
        records_to_insert.append({
            "id": r["id"],
            "name": r["name"],
            "area_name": area_name,
            "pincode": str(pincode),
            "latitude": latitude,
            "longitude": longitude,
            "cuisines": r.get("cuisines", []),
            "rating": r.get("rating", 0),
            "rating_count": r.get("rating_count", 0),
            "cost_for_two": r.get("cost_for_two", 0),
            "is_mock": r["id"].startswith("mock_"),
        })
        
    if records_to_insert:
        from src.db import upsert_restaurants_batch
        upsert_restaurants_batch(records_to_insert)

    return {
        "area": area_name,
        "count": len(all_restaurants),
        "cuisines": len(all_cuisines),
        "mock_used": "Y" if mock_used else "N",
    }


def run_ingestion() -> None:
    """Execute the full ingestion pipeline across all 20 NCR areas.

    Creates database tables, iterates through areas with a rich progress bar,
    and prints a summary table at the end.
    """
    console.print("\n[bold orange1]🍳 Swiggy Dark Kitchen — Data Ingestion[/bold orange1]\n")

    # --- Initialise ---
    console.print("[dim]Creating database tables...[/dim]")
    create_tables()

    console.print("[dim]Initialising Swiggy MCP client...[/dim]")
    try:
        client = SwiggyMCPClient()
    except ValueError as e:
        console.print(f"[bold red]✗ {e}[/bold red]")
        sys.exit(1)

    areas_df = load_areas()
    console.print(f"[green]✓ Loaded {len(areas_df)} NCR areas[/green]\n")

    # --- Ingest with progress ---
    summaries: list[dict] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Ingesting areas…", total=len(areas_df))

        for _, row in areas_df.iterrows():
            progress.update(task, description=f"[cyan]{row['area_name']}[/cyan]")
            summary = ingest_area(
                client,
                row["area_name"],
                str(row["pincode"]),
                row["latitude"],
                row["longitude"],
            )
            summaries.append(summary)
            progress.advance(task)

    # --- Summary table ---
    console.print()
    table = Table(
        title="📊 Ingestion Summary",
        title_style="bold orange1",
        show_lines=True,
    )
    table.add_column("Area", style="cyan", min_width=25)
    table.add_column("Restaurants Found", justify="right", style="green")
    table.add_column("Cuisine Variety", justify="right", style="yellow")
    table.add_column("Mock Data Used", justify="center", style="magenta")

    total_restaurants = 0
    total_mock = 0
    for s in summaries:
        table.add_row(s["area"], str(s["count"]), str(s["cuisines"]), s["mock_used"])
        total_restaurants += s["count"]
        if s["mock_used"] == "Y":
            total_mock += 1

    console.print(table)
    console.print(
        f"\n[bold green]✓ Done![/bold green] "
        f"Total: {total_restaurants} restaurants across {len(summaries)} areas. "
        f"Mock data used in {total_mock} areas.\n"
    )
    console.print("[dim]Next: run [bold]python src/analysis.py[/bold] or "
                  "[bold]streamlit run src/streamlit_app.py[/bold][/dim]\n")


if __name__ == "__main__":
    run_ingestion()
