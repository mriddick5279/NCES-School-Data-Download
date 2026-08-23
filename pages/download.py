"""Download page - pick school type(s), states, and an output directory, then run
the pipeline and show a summary. Mirrors __main__.py's CLI orchestration (same
shared.run_pipeline / shared.merge_type_results calls), just driven by Streamlit
widgets instead of argparse.

Runs each selected type sequentially rather than concurrently (unlike __main__.py's
ThreadPoolExecutor over types) - simpler to reason about for a first pass, at the
cost of taking longer when both types are selected. The whole run blocks this script
until done (Streamlit has no built-in background-job UI), so a full all-states run
will sit at the spinner for several minutes - a background task queue would be the
natural next step if that's too slow to work with interactively.
"""
import shutil
from pathlib import Path

import streamlit as st

from nces_sd_download import config_private, config_public, shared

TYPE_CONFIGS = {"public": config_public, "private": config_private}

st.title("Download")

selected_types = st.multiselect(
    "School type(s)", options=list(TYPE_CONFIGS), default=list(TYPE_CONFIGS),
)

state_scope = st.radio(
    "States", options=["All", "States only", "Territories only", "Custom"], horizontal=True,
)

if state_scope == "All":
    states = shared.STATE_FIPS
elif state_scope == "States only":
    states = {name: fips for name, fips in shared.STATE_FIPS.items() if name not in shared.TERRITORIES}
elif state_scope == "Territories only":
    states = {name: fips for name, fips in shared.STATE_FIPS.items() if name in shared.TERRITORIES}
else:
    chosen = st.multiselect("Pick specific states/territories", options=sorted(shared.STATE_FIPS))
    states = {name: shared.STATE_FIPS[name] for name in chosen}

output_dir = Path(st.text_input("Output directory", value=str(Path.cwd() / ".output")))

with st.expander("Advanced options"):
    retries = int(st.number_input("Retries per state", min_value=0, max_value=5, value=2))
    max_workers = int(st.number_input("Max concurrent workers per type", min_value=1, max_value=25, value=10))
    headless = st.checkbox("Headless Chrome", value=True)

run_clicked = st.button(
    "Run pipeline", type="primary", disabled=not selected_types or not states,
)

if run_clicked:
    results: dict[str, shared.PipelineResult] = {}
    try:
        with st.spinner(
            f"Downloading {len(states)} state(s)/territory(ies) for "
            f"{len(selected_types)} type(s) - this can take a while..."
        ):
            for type_name in selected_types:
                results[type_name] = shared.run_pipeline(
                    TYPE_CONFIGS[type_name], type_name, states, output_dir,
                    retries=retries, headless=headless, max_workers=max_workers,
                )

            for type_name, result in results.items():
                shared.report_result(type_name, result)

            succeeded_states = shared.merge_type_results(results, output_dir)
    finally:
        # Deferred until download AND merge are both done - see run_pipeline's
        # docstring for why (cleaning up right after each type's own states finish
        # was racing a transient Windows file lock).
        for result in results.values():
            shutil.rmtree(result.downloads_root, ignore_errors=True)

    st.session_state["download_results"] = results
    st.session_state["download_succeeded_states"] = succeeded_states
    st.session_state["download_output_dir"] = output_dir

if "download_results" in st.session_state:
    st.subheader("Results")
    for type_name, result in st.session_state["download_results"].items():
        st.write(
            f"**{type_name}**: {len(result.dataframes)} succeeded, "
            f"{len(result.skipped_states)} skipped, {len(result.failed_states)} failed"
        )
        if result.failed_states:
            st.warning(f"Failed: {', '.join(result.failed_states)}")

    st.success(
        f"Wrote {len(st.session_state['download_succeeded_states'])} merged file(s) "
        f"to {st.session_state['download_output_dir']}"
    )
