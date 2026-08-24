"""Download page - pick school type(s) and states, then run the pipeline and show a
summary. Writes to shared.DEFAULT_OUTPUT_DIR (not user-configurable here, unlike
__main__.py's --output-dir flag) so the Browse page always knows where to look.
Mirrors __main__.py's CLI orchestration (same shared.run_pipeline /
shared.merge_type_results calls), just driven by Streamlit widgets instead of argparse.

Runs each selected type sequentially rather than concurrently (unlike __main__.py's
ThreadPoolExecutor over types) - simpler to reason about for a first pass, at the
cost of taking longer when both types are selected. The whole run blocks this script
until done (Streamlit has no built-in background-job UI), so a full all-states run
will sit at the spinner for several minutes - a background task queue would be the
natural next step if that's too slow to work with interactively.
"""
import shutil

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

output_dir = shared.DEFAULT_OUTPUT_DIR

retries = int(st.number_input("Retries per state", min_value=0, max_value=5, value=2))

run_clicked = st.button(
    "Run pipeline", type="primary", disabled=not selected_types or not states,
)

if run_clicked:
    with st.spinner("Checking nces.ed.gov is reachable..."):
        unreachable_types = [
            type_name for type_name in selected_types
            if not shared.is_nces_reachable(
                TYPE_CONFIGS[type_name].URL_TEMPLATE.format(fips=shared.PREFLIGHT_FIPS)
            )
        ]

    if unreachable_types:
        st.error(
            f"nces.ed.gov isn't responding right now for: {', '.join(unreachable_types)}. "
            "The run was skipped before downloading anything. This is on their end "
            "(site outage or a connection reset) rather than a problem with the app - "
            "wait a bit and try again."
        )
    else:
        results: dict[str, shared.PipelineResult] = {}
        try:
            with st.spinner(
                f"Downloading {len(states)} state(s)/territory(ies) for "
                f"{len(selected_types)} type(s) - this can take a while..."
            ):
                for type_name in selected_types:
                    results[type_name] = shared.run_pipeline(
                        TYPE_CONFIGS[type_name], type_name, states, output_dir,
                        retries=retries,
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

        # Without this, app.py's nav (built before this page runs, on the same rerun
        # that handled the button click) wouldn't pick up shared.has_downloaded_output()
        # flipping to true until some later, unrelated interaction. Forcing a fresh
        # rerun now re-evaluates it immediately, so Results shows up in the sidebar
        # right away rather than only after the next click.
        st.rerun()

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
        'Download successful! Navigate to "Results" to view the data.'
    )
