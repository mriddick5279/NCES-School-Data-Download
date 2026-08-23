"""Browse page - view the most recently downloaded per-state CSVs as a spreadsheet.

Reads from the same output directory the Download page writes to (remembered in
session_state after a run, defaulting to .output otherwise). Files are named
{state}_sd.csv by shared.merge_type_results, so the state list is derived directly
from what's on disk rather than STATE_FIPS - only states that actually have a
downloaded file show up as selectable.
"""
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

st.title("Browse")

default_output_dir = st.session_state.get("download_output_dir", Path.cwd() / ".output")
output_dir = Path(st.text_input("Output directory", value=str(default_output_dir)))

if not output_dir.is_dir():
    st.info(f"No output directory found at {output_dir}. Run a download first.")
    st.stop()

state_files = {path.stem.removesuffix("_sd"): path for path in sorted(output_dir.glob("*_sd.csv"))}

if not state_files:
    st.info(f"No downloaded files found. Run a download first.")
    st.stop()

selected_state = st.sidebar.selectbox("State", options=sorted(state_files))

selected_path = state_files[selected_state]
df = pd.read_csv(selected_path)
last_modified = datetime.fromtimestamp(selected_path.stat().st_mtime)

st.subheader(selected_state)
st.caption(
    f"{len(df)} rows x {len(df.columns)} columns - "
    f"last downloaded {last_modified:%Y-%m-%d %H:%M}"
)
st.dataframe(df, use_container_width=True)
