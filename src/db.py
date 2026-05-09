"""
Database layer for Swiggy Dark Kitchen Opportunity Finder.

Manages PostgreSQL connections, schema creation, and all CRUD operations
for restaurants, cuisine supply metrics, and gap scores.
"""

import os
from typing import Optional

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/swiggy_dk")


def get_connection() -> psycopg2.extensions.connection:
    """Return a new PostgreSQL connection using DATABASE_URL from .env.

    Returns:
        psycopg2 connection object.

    Raises:
        psycopg2.OperationalError: If the database is unreachable.
    """
    return psycopg2.connect(DATABASE_URL)


def create_tables() -> None:
    """Create all required tables if they do not already exist.

    Tables created:
        - restaurants: Raw restaurant data per area.
        - cuisine_supply: Aggregated cuisine supply metrics per area.
        - gap_scores: Computed opportunity gap scores per area × cuisine.
    """
    ddl = """
    CREATE TABLE IF NOT EXISTS restaurants (
        id TEXT PRIMARY KEY,
        name TEXT,
        area_name TEXT,
        pincode TEXT,
        latitude FLOAT,
        longitude FLOAT,
        cuisines TEXT[],
        rating FLOAT,
        rating_count INT,
        cost_for_two INT,
        is_mock BOOLEAN DEFAULT FALSE,
        ingested_at TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS cuisine_supply (
        area_name TEXT,
        cuisine TEXT,
        restaurant_count INT,
        avg_rating FLOAT,
        total_rating_count INT,
        weighted_supply_score FLOAT,
        PRIMARY KEY (area_name, cuisine)
    );

    CREATE TABLE IF NOT EXISTS gap_scores (
        area_name TEXT,
        pincode TEXT,
        latitude FLOAT,
        longitude FLOAT,
        cuisine TEXT,
        supply_score FLOAT,
        demand_proxy FLOAT,
        gap_score FLOAT,
        opportunity_tier TEXT,
        PRIMARY KEY (area_name, cuisine)
    );
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def upsert_restaurants_batch(restaurants: list[dict]) -> None:
    """Bulk upsert multiple restaurant records in a single connection."""
    if not restaurants:
        return
        
    sql = """
    INSERT INTO restaurants (id, name, area_name, pincode, latitude, longitude,
                             cuisines, rating, rating_count, cost_for_two, is_mock)
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        area_name = EXCLUDED.area_name,
        pincode = EXCLUDED.pincode,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        cuisines = EXCLUDED.cuisines,
        rating = EXCLUDED.rating,
        rating_count = EXCLUDED.rating_count,
        cost_for_two = EXCLUDED.cost_for_two,
        is_mock = EXCLUDED.is_mock,
        ingested_at = NOW();
    """
    
    values = [
        (
            r["id"], r["name"], r["area_name"], r["pincode"], r["latitude"], r["longitude"],
            r["cuisines"], r["rating"], r["rating_count"], r["cost_for_two"], r["is_mock"]
        ) for r in restaurants
    ]
    
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, values)
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def upsert_restaurant(r: dict) -> None:
    """Insert or update a single restaurant record.

    Args:
        r: Restaurant dict with keys: id, name, area_name, pincode,
           latitude, longitude, cuisines, rating, rating_count,
           cost_for_two, is_mock.

    Raises:
        psycopg2.Error: On database write failure.
    """
    sql = """
    INSERT INTO restaurants (id, name, area_name, pincode, latitude, longitude,
                             cuisines, rating, rating_count, cost_for_two, is_mock)
    VALUES (%(id)s, %(name)s, %(area_name)s, %(pincode)s, %(latitude)s, %(longitude)s,
            %(cuisines)s, %(rating)s, %(rating_count)s, %(cost_for_two)s, %(is_mock)s)
    ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        area_name = EXCLUDED.area_name,
        pincode = EXCLUDED.pincode,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        cuisines = EXCLUDED.cuisines,
        rating = EXCLUDED.rating,
        rating_count = EXCLUDED.rating_count,
        cost_for_two = EXCLUDED.cost_for_two,
        is_mock = EXCLUDED.is_mock,
        ingested_at = NOW();
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, r)
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def upsert_cuisine_supply_batch(supply_df: pd.DataFrame) -> None:
    """Bulk upsert cuisine supply aggregate rows.

    Args:
        supply_df: DataFrame with columns: area_name, cuisine,
                   restaurant_count, avg_rating, total_rating_count,
                   weighted_supply_score.
    """
    if supply_df.empty:
        return
        
    sql = """
    INSERT INTO cuisine_supply (area_name, cuisine, restaurant_count, avg_rating,
                                total_rating_count, weighted_supply_score)
    VALUES %s
    ON CONFLICT (area_name, cuisine) DO UPDATE SET
        restaurant_count = EXCLUDED.restaurant_count,
        avg_rating = EXCLUDED.avg_rating,
        total_rating_count = EXCLUDED.total_rating_count,
        weighted_supply_score = EXCLUDED.weighted_supply_score;
    """
    
    values = [
        (
            row["area_name"], row["cuisine"], int(row["restaurant_count"]),
            float(row["avg_rating"]), int(row["total_rating_count"]),
            float(row["weighted_supply_score"])
        ) for _, row in supply_df.iterrows()
    ]
    
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, values)
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def upsert_gap_scores(df: pd.DataFrame) -> None:
    """Bulk upsert gap score rows from a DataFrame.

    Args:
        df: DataFrame with columns: area_name, pincode, latitude, longitude,
            cuisine, supply_score, demand_proxy, gap_score, opportunity_tier.

    Raises:
        psycopg2.Error: On database write failure.
    """
    if df.empty:
        return
        
    sql = """
    INSERT INTO gap_scores (area_name, pincode, latitude, longitude, cuisine,
                            supply_score, demand_proxy, gap_score, opportunity_tier)
    VALUES %s
    ON CONFLICT (area_name, cuisine) DO UPDATE SET
        pincode = EXCLUDED.pincode,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        supply_score = EXCLUDED.supply_score,
        demand_proxy = EXCLUDED.demand_proxy,
        gap_score = EXCLUDED.gap_score,
        opportunity_tier = EXCLUDED.opportunity_tier;
    """
    
    values = [
        (
            row["area_name"], row["pincode"], row["latitude"], row["longitude"],
            row["cuisine"], row["supply_score"], row["demand_proxy"],
            row["gap_score"], row["opportunity_tier"]
        ) for _, row in df.iterrows()
    ]
    
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, values)
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def get_gap_scores() -> pd.DataFrame:
    """Fetch all gap scores from the database.

    Returns:
        DataFrame with all gap_scores rows, or an empty DataFrame
        if the table is empty or does not exist.
    """
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT * FROM gap_scores ORDER BY gap_score DESC", conn)
        return df
    except psycopg2.Error:
        return pd.DataFrame()
    finally:
        conn.close()


def get_all_restaurants() -> pd.DataFrame:
    """Fetch all restaurant records from the database.

    Returns:
        DataFrame with all restaurant rows.
    """
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT * FROM restaurants ORDER BY area_name, name", conn)
        return df
    except psycopg2.Error:
        return pd.DataFrame()
    finally:
        conn.close()


def get_cuisine_supply() -> pd.DataFrame:
    """Fetch all cuisine supply records from the database.

    Returns:
        DataFrame with all cuisine_supply rows.
    """
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT * FROM cuisine_supply ORDER BY area_name, cuisine", conn)
        return df
    except psycopg2.Error:
        return pd.DataFrame()
    finally:
        conn.close()
