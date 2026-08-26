# argparse CLI, orchestration entrypoint
import argparse, logging, shutil, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config_private, config_public, shared

parser = argparse.ArgumentParser(
    description="Download NCES School District data for all states and school types.")

# Arguments allowed when running main module
parser.add_argument('--type',type=str,default='both',choices=['public','private','both'],
                    help="School type to download (default: both).")
parser.add_argument('--states',type=str,default='all',
                    help="'all' for every state and territory (default), 'states' for just the "
                         "50 states, 'territories' for DC plus the territories, or a comma-separated "
                         "list of specific state/territory names (e.g. \"California,Texas\").")
parser.add_argument('--output-dir',type=Path,default=Path.cwd() / '.output',
                    help="Directory to save downloaded files (default: current working directory).")

args = parser.parse_args()

# Instantiate logging
logging.basicConfig(level='INFO', format="%(asctime)s %(levelname)s %(message)s")

# Determine option chosen for states download
states = {}
if args.states == 'all':
    states = shared.STATE_FIPS
elif args.states == 'states':
    states = {name: fips for name, fips in shared.STATE_FIPS.items() if name not in shared.TERRITORIES}
elif args.states == 'territories':
    states = {name: fips for name, fips in shared.STATE_FIPS.items() if name in shared.TERRITORIES}
else: # Custom list of states/territories
    requested = [s.strip() for s in args.states.split(',')]
    unknown = [s for s in requested if s not in shared.STATE_FIPS]
    if unknown:
        parser.error(f"Unknown state(s): {', '.join(unknown)}")
    states = {s: shared.STATE_FIPS[s] for s in requested}

# Setup types to download (public, private, or both)
TYPE_CONFIGS = {'public': config_public, 'private': config_private}
types_to_run = list(TYPE_CONFIGS) if args.type == 'both' else [args.type]

shared.logger.info(
    "Starting run: type=%s states=%d output_dir=%s",
    args.type, len(states), args.output_dir
)

# If state data cannot be reached, abort download process for state beforehand
unreachable_types = [
    type_name for type_name in types_to_run
    if not shared.is_nces_reachable(
        TYPE_CONFIGS[type_name].URL_TEMPLATE.format(fips=shared.PREFLIGHT_FIPS)
    )
]
if unreachable_types:
    shared.logger.error(
        "nces.ed.gov isn't responding right now for: %s (site outage or a connection "
        "reset on their end) - aborting before downloading anything.",
        ", ".join(unreachable_types),
    )
    sys.exit(1)

# Execute pipeline
results: dict[str, shared.PipelineResult] = {}
try:
    # Run each requested school type concurrently
    with ThreadPoolExecutor(max_workers=len(types_to_run)) as executor:
        futures = {
            type_name: executor.submit(
                shared.run_pipeline,
                TYPE_CONFIGS[type_name],
                type_name,
                states,
                args.output_dir
            )
            for type_name in types_to_run
        }
        results = {type_name: future.result() for type_name, future in futures.items()}

    for type_name, result in results.items():
        shared.report_result(type_name, result)

    # Merge public and private school information into a single per-state file
    succeeded_states = shared.merge_type_results(results, args.output_dir)

    shared.logger.info("Wrote %d merged per-state file(s) to %s", len(succeeded_states), args.output_dir)
finally:
    # Remove temporary download files for both types
    for result in results.values():
        shutil.rmtree(result.downloads_root, ignore_errors=True)

sys.exit(1 if any(result.failed_states for result in results.values()) else 0)