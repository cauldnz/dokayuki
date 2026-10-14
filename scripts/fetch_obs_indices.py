"""Fetch the AO and MJO RMM indices into state/obs_indices.parquet (merged daily table)."""
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from dokayuki.fetch.obs_indices import fetch_ao, fetch_rmm, mjo_features
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
ao = fetch_ao(Path("state/ao.parquet"))
rmm = fetch_rmm(Path("state/rmm.parquet"))
df = pd.concat([ao, mjo_features(rmm)], axis=1).sort_index()
df.index.name = "time"
df.to_parquet("state/obs_indices.parquet")
logging.info("obs_indices: %s .. %s, %d rows", df.index[0].date(), df.index[-1].date(), len(df))
