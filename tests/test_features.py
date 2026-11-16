import numpy as np
import pandas as pd

from ml.features import FEATURES, add_time_features, time_split_masks

AS_OF = "2026-10-26"


def test_time_split_boundaries():
    dates = pd.Series(pd.to_datetime(
        ["2026-07-25", "2026-07-26", "2026-10-04", "2026-10-05", "2026-10-26", "2026-10-27"]))
    tr, te = time_split_masks(dates, AS_OF)
    assert tr.tolist() == [False, True, True, False, False, False]
    assert te.tolist() == [False, False, False, True, True, False]


def test_cyclical_features():
    df = pd.DataFrame({"loading_date": ["2026-01-01", "2026-07-01"]})
    out = add_time_features(df)
    assert np.isclose(out.loc[0, "month_sin"], np.sin(2 * np.pi / 12))
    assert np.isclose(out.loc[1, "month_cos"], np.cos(2 * np.pi * 7 / 12))
    assert np.isclose(out.loc[0, "doy_sin"] ** 2 + out.loc[0, "doy_cos"] ** 2, 1.0)


def test_no_leaky_features():
    banned = ("price", "profit", "cost", "outlier", "group_id", "avg_price", "km_price")
    assert not [f for f in FEATURES if any(b in f for b in banned) and f != "price_type"]
