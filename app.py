"""Streamlit entry point. Run with:

    streamlit run app.py

Pages live in pages/, wired up explicitly below via st.Page. Having a pages/
folder next to this script does NOT trigger Streamlit's legacy auto-discovery
once st.navigation is used here - pages/ is just a place to keep the files;
this list controls what shows up, in what order, and under what title/icon.
"""
import streamlit as st

st.set_page_config(page_title="NCES School Directory Downloader", layout="wide")

home = st.Page("pages/home.py", title="Home", icon="🏠", default=True)
download = st.Page("pages/download.py", title="Download", icon="⬇️")

pg = st.navigation([home, download])
pg.run()
