"""Streamlit entry point. Run with:

    streamlit run app.py

Pages live in pages/, wired up explicitly below via st.Page. Having a pages/
folder next to this script does NOT trigger Streamlit's legacy auto-discovery
once st.navigation is used here - pages/ is just a place to keep the files;
this list controls what shows up, in what order, and under what title/icon.
"""
import streamlit as st

from nces_sd_download import shared

st.set_page_config(page_title="NCES School Directory Downloader", layout="wide")

# home = st.Page("pages/home.py", title="Home", icon="🏠", default=True)
download = st.Page("pages/download.py", title="Download", icon="⬇️", default=True)

# Results only belongs in the nav once there's something for it to show - see
# shared.has_downloaded_output's docstring for why this checks disk, not session state.
pages = [download]
# pages = [home, download]
if shared.has_downloaded_output():
    pages.append(st.Page("pages/results.py", title="Results", icon="📊"))

pg = st.navigation(pages)
pg.run()
