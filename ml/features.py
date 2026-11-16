"""Чистые функции признаков и временного разбиения (без обращения к БД)."""
import numpy as np
import pandas as pd

CAT_FEATURES = ["l_city", "u_city", "l_region", "u_region", "body_group",
                "weight_category", "volume_category", "price_type"]
NUM_FEATURES = ["distance", "total_weight", "total_volume",
                "l_lat", "l_lon", "u_lat", "u_lon",
                "year", "month", "dow", "doy",
                "month_sin", "month_cos", "dow_sin", "dow_cos", "doy_sin", "doy_cos"]
FEATURES = NUM_FEATURES + CAT_FEATURES
# Запрещено (leakage): price, price_rub, price_with_vat, price/distance, price/weight,
# customer_cost/profit/carrier_cost, price_group_stats.*, price_group_id, outlier_mark.


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    d = pd.to_datetime(out["loading_date"])
    out["year"] = d.dt.year
    out["month"] = d.dt.month
    out["dow"] = d.dt.dayofweek
    out["doy"] = d.dt.dayofyear
    for name, period in (("month", 12.0), ("dow", 7.0), ("doy", 365.25)):
        angle = 2 * np.pi * out[name] / period
        out[f"{name}_sin"] = np.sin(angle)
        out[f"{name}_cos"] = np.cos(angle)
    return out


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = add_time_features(df)
    for c in CAT_FEATURES:
        out[c] = out[c].astype("object").where(out[c].notna(), "UNKNOWN").astype(str)
    return out


def split_bounds(as_of) -> dict:
    as_of = pd.Timestamp(as_of)
    return {
        "train_start": as_of - pd.DateOffset(months=3),   # 2026-07-26
        "train_end_excl": as_of - pd.Timedelta(weeks=3),  # 2026-10-05
        "test_end": as_of,                                 # 2026-10-26 включительно
    }


def time_split_masks(dates: pd.Series, as_of):
    b = split_bounds(as_of)
    d = pd.to_datetime(dates)
    train = (d >= b["train_start"]) & (d < b["train_end_excl"])
    test = (d >= b["train_end_excl"]) & (d <= b["test_end"])
    return train, test
