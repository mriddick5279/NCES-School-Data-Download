import streamlit as st

st.title("NCES School Directory Downloader")
st.write(
    "Downloads and merges NCES public and private school directory data for every "
    "U.S. state and territory into one CSV per state."
)
st.markdown(
    """
    **Phases**
    1. **Download** - scrape, transform, and merge per-state school directory data. *(this page is live - see the Download page in the sidebar)*
    2. **Standardize** *(planned)* - clean up billing city/county/name fields.
    """
)
