"""
Results page - view the most recently downloaded per-state CSVs as a spreadsheet.

Reads downloaded files from default output directory and presents them to the user within
dataframe container. User can select which state files to view by using the dropdown in
the navigation pane under the 'Results' page tab. They also have the option to download the
current file they are looking at or all files that were downloaded (packaged into zip file).
"""
import io
import zipfile
from datetime import datetime

import pandas as pd
import streamlit as st

from nces_sd_download import shared

st.title("Results")

output_dir = shared.DEFAULT_OUTPUT_DIR

# app.py already keeps this page out of the nav until shared.has_downloaded_output()
# is true, but it's still directly reachable by URL, so show this just in case
if not shared.has_downloaded_output():
    st.info("No downloaded files yet. Run a download first.")
    st.stop()

state_files = {path.stem.removesuffix("_sd"): path for path in sorted(output_dir.glob("*_sd.csv"))}


def _zip_all(paths: list) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            zf.write(path, arcname=path.name)
    return buf.getvalue()

with st.container(width='content',height='content',horizontal=True,gap='small'):
    st.download_button(
        "Download All", data=_zip_all(list(state_files.values())),
        file_name="nces_downloads.zip", mime="application/zip",
    )

    clear_button = st.button('Clear Downloads')

if clear_button:
    st.success('Clear button clicked')

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
st.dataframe(df, width='content', height='content')
