import os
import numpy as np
import pandas as pd
import psycopg
from catboost import CatBoostRegressor

from ml.features import FEATURES, build_features
from ml.run import load_frame

AS_OF = pd.Timestamp(os.environ.get("AS_OF_DATE", "2026-10-26"))

conn = psycopg.connect(
    host=os.environ["POSTGRES_HOST"],
    port=os.environ.get("POSTGRES_PORT", "5432"),
    dbname=os.environ["POSTGRES_DB"],
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
)

model = CatBoostRegressor()
model.load_model("artifacts/catboost_v1.cbm")


def predict_rub(X):
    # модель обучена на log1p(цены), поэтому возвращаем через expm1 (как в ml/run.py)
    return np.clip(np.expm1(model.predict(X[FEATURES])), 0, None)


feats = build_features(load_frame(conn))
conn.close()

cols = ["price_id", "loading_date", "l_city", "u_city", "body_group",
        "distance", "total_weight"]

# 1) Проверка на тестовом периоде: прогноз против факта
test = feats[(feats["loading_date"] > AS_OF - pd.Timedelta(weeks=3))
             & (feats["loading_date"] <= AS_OF)].sample(20, random_state=1).copy()
test["predicted_rub"] = np.round(predict_rub(test), 0)
test["actual_rub"] = np.round(test["price_rub"], 0)
test["err_pct"] = np.round((test["predicted_rub"] / test["actual_rub"] - 1) * 100, 1)
print("=== Тестовый период: прогноз vs факт ===")
print(test[cols + ["predicted_rub", "actual_rub", "err_pct"]].to_string(index=False))

# 2) Будущие заявки (после as_of): только прогноз
fut = feats[feats["loading_date"] > AS_OF].head(20).copy()
fut["predicted_rub"] = np.round(predict_rub(fut), 0)
print("\n=== Будущие заявки: прогноз ===")
print(fut[cols + ["predicted_rub"]].to_string(index=False))

pd.concat([test.assign(split="test"), fut.assign(split="future")])[
    cols + ["split", "predicted_rub", "actual_rub"]
].to_csv("artifacts/predictions_new.csv", index=False)
