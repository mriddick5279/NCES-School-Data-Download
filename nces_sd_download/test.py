"""Dev-only test harness for exercising the pipeline, including its multithreading
behavior. Not part of the public CLI - hits the live NCES site for real, so use
sparingly. Run directly:

    python -m nces_sd_download.test --size 1 --type both
    python -m nces_sd_download.test --no-headless --size 1 --type private
    python -m nces_sd_download.test --size 5 --type public --max-workers 5 --seed 42
"""

import argparse, logging ,random, shutil, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from . import config_private, config_public, shared


def pick_states(count: int, seed: int | None = None) -> list[str]:
    """Pick `count` random state/territory names from shared.STATE_FIPS.
    Pass the same seed to reproduce a specific selection (e.g. to re-run a failure)."""
    rng = random.Random(seed)
    return rng.sample(list(shared.STATE_FIPS.keys()), count)

def merge_test_assert(state: str, merged_states: list[str], output_dir: Path, results: dict) -> None:
    if state in merged_states:
            merged_path = output_dir / f"{state}_sd.csv"
            assert merged_path.exists(), f"merged file missing: {merged_path}"
            merged_df = pd.read_csv(merged_path, keep_default_na=False)
            expected_rows = sum(
                len(result.dataframes[state]) for result in results.values() if state in result.dataframes
            )
            assert len(merged_df) == expected_rows
    
            for type_name in results:
                assert not (output_dir / type_name / f"{state}_sd.csv").exists(), \
                    f"per-type source file for {type_name} should have been removed after merge"
    else:
        shared.logger.warning("%s: no data from either type - nothing to merge", state)

    shared.logger.info("%s: merge test passed", state)


def test_one_state_public_download(output_dir: Path, pub_config, state: str, headless: bool) -> None:
    result = shared.run_pipeline(
        pub_config, 'public', {state: shared.STATE_FIPS[state]}, output_dir,
        retries=2, headless=headless, max_workers=1,
    )
    try:
        shared.report_result('public', result)
        if state in result.dataframes:
            csv_path = output_dir / 'public' / f"{state}_sd.csv"
            assert csv_path.exists(), f"expected output file missing: {csv_path}"
    finally:
        shutil.rmtree(result.downloads_root, ignore_errors=True)


def test_one_state_private_download(output_dir: Path, priv_config, state: str, headless: bool) -> None:
    result = shared.run_pipeline(
        priv_config, 'private', {state: shared.STATE_FIPS[state]}, output_dir,
        retries=2, headless=headless, max_workers=1,
    )
    try:
        shared.report_result('private', result)
        if state in result.dataframes:
            csv_path = output_dir / 'private' / f"{state}_sd.csv"
            assert csv_path.exists(), f"expected output file missing: {csv_path}"
    finally:
        shutil.rmtree(result.downloads_root, ignore_errors=True)


def test_one_state_public_and_private_concurrent(output_dir: Path, type_configs: dict, state: str) -> None:
    """Runs the public and private pipelines for the same state at the same time, on
    separate threads. A single state within a single run_pipeline call has nothing to
    parallelize against (max_workers=1 is moot with one task) - running the two *types*
    concurrently against each other is what actually exercises multithreading here.

    Also exercises shared.merge_type_results, the same public+private merge step
    __main__.py runs after a real CLI invocation - otherwise nothing in the test suite
    would catch a regression there."""
    fips = {state: shared.STATE_FIPS[state]}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            type_name: executor.submit(
                shared.run_pipeline, type_config, type_name, fips, output_dir,
                retries=2, headless=True,
            )
            for type_name, type_config in type_configs.items()
        }
        results = {type_name: future.result() for type_name, future in futures.items()}

    try:
        for type_name, result in results.items():
            shared.report_result(type_name, result)

        merged_states = shared.merge_type_results(results, output_dir)

        merge_test_assert(state, merged_states, output_dir, results)
    finally:
        # Remove downloaded files for both types
        for result in results.values():
            shutil.rmtree(result.downloads_root, ignore_errors=True)


def test_states_concurrent_download(output_dir: Path, type_configs: dict, states: list[str], max_workers: int) -> None:
    """Runs multiple states for each requested school type - exercises run_pipeline's
    own ThreadPoolExecutor (multiple states, one type) with real work to actually
    parallelize, and, when more than one type is requested, also runs the types
    concurrently against each other (mirroring __main__.py's real orchestration).

    Then merges each state's per-type results together via shared.merge_type_results,
    the same step __main__.py runs after a real CLI invocation, so a multi-state run
    exercises that path too rather than just the size-1 concurrent test."""
    fips = {state: shared.STATE_FIPS[state] for state in states}

    with ThreadPoolExecutor(max_workers=len(type_configs)) as executor:
        futures = {
            type_name: executor.submit(
                shared.run_pipeline, type_config, type_name, fips, output_dir,
                retries=2, headless=True, max_workers=max_workers,
            )
            for type_name, type_config in type_configs.items()
        }
        results = {type_name: future.result() for type_name, future in futures.items()}

    try:
        for type_name, result in results.items():
            shared.report_result(type_name, result)
            for state in result.dataframes:
                csv_path = output_dir / type_name / f"{state}_sd.csv"
                assert csv_path.exists(), f"expected output file missing: {csv_path}"

        merged_states = shared.merge_type_results(results, output_dir)
        for state in states:
            merge_test_assert(state, merged_states, output_dir, results)
    finally:
        # Remove downloaded files for both types
        for result in results.values():
            shutil.rmtree(result.downloads_root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dev-only test harness for the NCES download pipeline. Hits the "
                    "live NCES site for real - not part of the public CLI.")
    parser.add_argument('--headless',dest='headless',action='store_true',
                        help="Run Chrome in headless mode (default).")
    parser.add_argument('--no-headless',dest='headless',action='store_false',
                        help="Run Chrome with a visible window, for local debugging.")
    parser.set_defaults(headless=True)
    
    parser.add_argument('--size', type=int, choices=[1, 5, 10], default=1,
                        help="How many states to test with (default: 1).")
    parser.add_argument('--type', type=str, choices=['public', 'private', 'both'], default='both',
                        help="Which school type(s) to test (default: both).")
    parser.add_argument('--seed', type=int, default=None,
                        help="Random seed for state selection, to reproduce a specific run.")
    parser.add_argument('--max-workers', type=int, default=10,
                        help="Worker count for the --size 5/10 cases (default: 10; ignored for --size 1).")
    parser.add_argument('--output-dir', type=Path, default=Path.cwd() / '.test',
                        help="Directory for test output (default: a fresh temp directory).")
    args = parser.parse_args()

    logging.basicConfig(level='INFO', format="%(asctime)s %(levelname)s %(message)s")
    output_dir = args.output_dir or Path(tempfile.mkdtemp(prefix="nces_test_"))

    states = pick_states(args.size, seed=args.seed)
    shared.logger.info("Testing with seed=%s size=%d states=%s output_dir=%s", args.seed, args.size, states, output_dir)

    if args.size == 1:
        state = states[0]
        if args.type == 'public':
            test_one_state_public_download(output_dir, config_public, state, args.headless)
        if args.type == 'private':
            test_one_state_private_download(output_dir, config_private, state, args.headless)
        if args.type == 'both':
            test_one_state_public_and_private_concurrent(output_dir, {'public': config_public, 'private': config_private}, state)
    else:
        all_type_configs = {'public': config_public, 'private': config_private}
        types_to_run = list(all_type_configs) if args.type == 'both' else [args.type]
        type_configs = {t: all_type_configs[t] for t in types_to_run}
        test_states_concurrent_download(output_dir, type_configs, states, args.max_workers)

    shared.logger.info("All tests passed.")


if __name__ == "__main__":
    main()
