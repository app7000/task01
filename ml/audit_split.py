import pandas as pd

from ml.features import split_bounds, time_split_masks

as_of = pd.Timestamp("2026-10-26")

dates = pd.Series(pd.to_datetime([
    "2026-07-25",
    "2026-07-26",
    "2026-10-04",
    "2026-10-05",
    "2026-10-26",
    "2026-10-27",
]))

train, test = time_split_masks(dates, as_of)

print("BOUNDS:")
print(split_bounds(as_of))

print("\nBOUNDARY CHECK:")
print(pd.DataFrame({
    "date": dates,
    "train": train,
    "test": test,
}))
