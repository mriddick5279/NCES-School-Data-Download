"""Browse page - view the most recently downloaded per-state CSVs as a spreadsheet.

Reads from shared.DEFAULT_OUTPUT_DIR, the same fixed directory the Download page writes
to - neither page exposes it as a user-configurable path, so the two always agree on
where to look without the user having to keep them in sync. Files are named
{state}_sd.csv by shared.merge_type_results, so the state list is derived directly
from what's on disk rather than STATE_FIPS - only states that actually have a
downloaded file show up as selectable.
"""
import io
import zipfile
from datetime import datetime

import pandas as pd
import streamlit as st

from nces_sd_download import shared

st.title("Results")

output_dir = shared.DEFAULT_OUTPUT_DIR

if not output_dir.is_dir():
    st.info("No downloaded files yet. Run a download first.")
    st.stop()

state_files = {path.stem.removesuffix("_sd"): path for path in sorted(output_dir.glob("*_sd.csv"))}

if not state_files:
    st.info("No downloaded files yet. Run a download first.")
    st.stop()


def _zip_all(paths: list) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            zf.write(path, arcname=path.name)
    return buf.getvalue()


st.download_button(
    "Download All", data=_zip_all(list(state_files.values())),
    file_name="nces_downloads.zip", mime="application/zip",
)

selected_state = st.sidebar.selectbox("State", options=sorted(state_files))

selected_path = state_files[selected_state]
df = pd.read_csv(selected_path)
last_modified = datetime.fromtimestamp(selected_path.stat().st_mtime)

st.subheader(selected_state)
st.caption(
    f"{len(df)} rows x {len(df.columns)} columns - "
    f"last downloaded {last_modified:%Y-%m-%d %H:%M}"
)
st.download_button(
    "Download", data=selected_path.read_bytes(),
    file_name=selected_path.name, mime="text/csv",
)
st.dataframe(df, width='content')
