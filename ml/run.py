"""Обучение (time split), оценка и batch-скоринг с записью в mart.ml_price_predictions."""
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from etl.config import ROOT
from etl.db import get_logger
from ml.features import (CAT_FEATURES, FEATURES, NUM_FEATURES, build_features,
                         split_bounds, time_split_masks)

log = get_logger("ml")
PRIMARY = "catboost_v1"

SQL_FRAME = """
SELECT c.price_id, c.loading_date, c.loading_city_gcid, c.unloading_city_gcid,
       c.distance::float8 AS distance, c.total_weight::float8 AS total_weight,
       c.total_volume::float8 AS total_volume,
       c.weight_category, c.volume_category, c.price_type::text AS price_type,
       c.price_rub::float8 AS price_rub, c.is_fact, c.is_complex, c.outlier_mark,
       lc.city_name AS l_city, lc.region_name AS l_region,
       lc.latitude AS l_lat, lc.longitude AS l_lon,
       uc.city_name AS u_city, uc.region_name AS u_region,
       uc.latitude AS u_lat, uc.longitude AS u_lon,
       COALESCE(bg.body_group, 'Не указан') AS body_group
FROM core.prices_clean c
JOIN core.dim_city lc ON lc.gc_id = c.loading_city_gcid
JOIN core.dim_city uc ON uc.gc_id = c.unloading_city_gcid
LEFT JOIN core.v_price_body_group_primary bg ON bg.price_id = c.price_id
WHERE c.is_fact AND NOT c.is_complex
"""


def load_frame(conn) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(SQL_FRAME)
        cols = [d.name for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
    for c in ("l_lat", "l_lon", "u_lat", "u_lon"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["loading_date"] = pd.to_datetime(df["loading_date"])
    return df


def metrics(y_true, y_pred) -> dict:
    err = y_pred - y_true
    return {
        "r2": float(r2_score(y_true, y_pred)),
        "mape_pct": float(np.mean(np.abs(err) / y_true) * 100),
        "rmse_rub": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae_rub": float(mean_absolute_error(y_true, y_pred)),
    }


def make_models(seed: int) -> dict:
    cat = CatBoostRegressor(iterations=800, learning_rate=0.08, depth=6, loss_function="RMSE",
                            random_seed=seed, verbose=False, allow_writing_files=False)
    ridge = Pipeline([
        ("prep", ColumnTransformer([
            ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                              ("sc", StandardScaler())]), NUM_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CAT_FEATURES),
        ])),
        ("reg", Ridge(alpha=1.0, random_state=seed)),
    ])
    return {PRIMARY: cat, "ridge_baseline": ridge}


def _fit(name, model, X, y_log):
    if name == PRIMARY:
        model.fit(X, y_log, cat_features=CAT_FEATURES)
    else:
        model.fit(X, y_log)  # импутер/скейлер/энкодер обучаются только на train
    return model


def _predict_rub(model, X) -> np.ndarray:
    return np.clip(np.expm1(model.predict(X)), 0, None)


def _records(df: pd.DataFrame):
    out = []
    for row in df.itertuples(index=False, name=None):
        out.append(tuple(None if (v is None or (not isinstance(v, (str, date)) and pd.isna(v)))
                         else (v.item() if hasattr(v, "item") else v) for v in row))
    return out


def run_ml(conn, as_of: date, seed: int = 42) -> None:
    raw = load_frame(conn)
    feats = build_features(raw)
    log.info("ML frame: %d rows (fact, non-complex, DQ-clean)", len(feats))

    # target cleaning строго по входному outlier_mark; сам флаг НЕ признак
    hist = feats[(~feats["outlier_mark"]) & (feats["price_rub"] > 0)]
    tr_m, te_m = time_split_masks(hist["loading_date"], as_of)
    train, test = hist[tr_m], hist[te_m]
    if train.empty or test.empty:
        raise RuntimeError(f"empty split: train={len(train)} test={len(test)}")
    b = split_bounds(as_of)
    log.info("train [%s, %s): %d | test [%s, %s]: %d", b["train_start"].date(),
             b["train_end_excl"].date(), len(train), b["train_end_excl"].date(),
             b["test_end"].date(), len(test))

    X_tr, X_te = train[FEATURES], test[FEATURES]
    y_tr_log = np.log1p(train["price_rub"].values)
    y_te = test["price_rub"].values

    now = datetime.now(timezone.utc)
    models, all_metrics = make_models(seed), {}
    for name, model in models.items():
        _fit(name, model, X_tr, y_tr_log)
        m = metrics(y_te, _predict_rub(model, X_te))
        all_metrics[name] = m
        log.info("%-15s R2=%.4f MAPE=%.2f%% RMSE=%.0f MAE=%.0f", name,
                 m["r2"], m["mape_pct"], m["rmse_rub"], m["mae_rub"])

    models[PRIMARY].save_model(str(ROOT / "artifacts" / f"{PRIMARY}.cbm"))

    future = feats[feats["loading_date"] > pd.Timestamp(as_of)]
    model = models[PRIMARY]

    def part(df, split):
        p = df[["price_id", "loading_date", "loading_city_gcid", "unloading_city_gcid",
                "body_group"]].copy()
        p["split_name"] = split
        p["predicted_price_rub"] = np.round(_predict_rub(model, df[FEATURES]), 2)
        if split == "test":
            p["actual_price_rub"] = df["price_rub"].values
            p["abs_error_rub"] = np.round((p["predicted_price_rub"] - p["actual_price_rub"]).abs(), 2)
            p["ape_pct"] = np.round(p["abs_error_rub"] / p["actual_price_rub"] * 100, 4)
        else:  # будущие заявки: факт не используем даже если price заполнен
            p["actual_price_rub"] = np.nan
            p["abs_error_rub"] = np.nan
            p["ape_pct"] = np.nan
        return p

    pred = pd.concat([part(test, "test"), part(future, "future")], ignore_index=True)
    pred["loading_date"] = pred["loading_date"].dt.date
    pred["model_name"] = PRIMARY
    pred["scored_at"] = now
    cols = ["price_id", "loading_date", "loading_city_gcid", "unloading_city_gcid", "body_group",
            "split_name", "actual_price_rub", "predicted_price_rub", "abs_error_rub", "ape_pct",
            "model_name", "scored_at"]
    pred = pred[cols].astype(object)

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mart.ml_price_predictions WHERE model_name = %s", (PRIMARY,))
        with conn.cursor() as cur:
            with cur.copy(f"COPY mart.ml_price_predictions ({', '.join(cols)}) FROM STDIN") as cp:
                for rec in _records(pred):
                    cp.write_row(rec)
        with conn.cursor() as cur:
            for name, m in all_metrics.items():
                cur.execute(
                    """INSERT INTO mart.ml_model_metrics
                       (model_name, as_of, train_start, train_end_excl, test_start, test_end,
                        n_train, n_test, r2, mape_pct, rmse_rub, mae_rub, trained_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (model_name, as_of) DO UPDATE SET
                         train_start=EXCLUDED.train_start, train_end_excl=EXCLUDED.train_end_excl,
                         test_start=EXCLUDED.test_start, test_end=EXCLUDED.test_end,
                         n_train=EXCLUDED.n_train, n_test=EXCLUDED.n_test, r2=EXCLUDED.r2,
                         mape_pct=EXCLUDED.mape_pct, rmse_rub=EXCLUDED.rmse_rub,
                         mae_rub=EXCLUDED.mae_rub, trained_at=EXCLUDED.trained_at""",
                    (name, as_of, b["train_start"].date(), b["train_end_excl"].date(),
                     b["train_end_excl"].date(), b["test_end"].date(), len(train), len(test),
                     m["r2"], m["mape_pct"], m["rmse_rub"], m["mae_rub"], now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    log.info("predictions saved: test=%d future=%d (model=%s)", len(test), len(future), PRIMARY)
