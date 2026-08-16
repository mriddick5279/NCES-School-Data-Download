# argparse CLI, orchestration entrypoint
import argparse, logging, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config_private, config_public, shared

parser = argparse.ArgumentParser(
    description="Download NCES School District data for all states and school types.")

parser.add_argument('--type',type=str,default='both',choices=['public','private','both'],
                    help="School type to download (default: both).")
parser.add_argument('--states',type=str,default='all',
                    help="'all' for every state and territory (default), 'states' for just the "
                         "50 states, 'territories' for DC plus the territories, or a comma-separated "
                         "list of specific state/territory names (e.g. \"California,Texas\").")
parser.add_argument('--output-dir',type=Path,default=Path.cwd() / '.output',
                    help="Directory to save downloaded files (default: current working directory).")

args = parser.parse_args()
logging.basicConfig(level='INFO', format="%(asctime)s %(levelname)s %(message)s")

states = {}
if args.states == 'all':
    states = shared.STATE_FIPS
elif args.states == 'states':
    states = {name: fips for name, fips in shared.STATE_FIPS.items() if name not in shared.TERRITORIES}
elif args.states == 'territories':
    states = {name: fips for name, fips in shared.STATE_FIPS.items() if name in shared.TERRITORIES}
else:
    requested = [s.strip() for s in args.states.split(',')]
    unknown = [s for s in requested if s not in shared.STATE_FIPS]
    if unknown:
        parser.error(f"Unknown state(s): {', '.join(unknown)}")
    states = {s: shared.STATE_FIPS[s] for s in requested}

TYPE_CONFIGS = {'public': config_public, 'private': config_private}
types_to_run = list(TYPE_CONFIGS) if args.type == 'both' else [args.type]

shared.logger.info(
    "Starting run: type=%s states=%d output_dir=%s",
    args.type, len(states), args.output_dir
)

# Run each requested school type concurrently rather than one after another - they're
# fully independent (own type_config, own output subfolder, own driver pool).
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

# Merge each state's own public + private DataFrames into one file per state, then remove
# the per-type source files now that they've been folded into the merged file.
succeeded_states = shared.merge_type_results(results, args.output_dir)

shared.logger.info("Wrote %d merged per-state file(s) to %s", len(succeeded_states), args.output_dir)

sys.exit(1 if any(result.failed_states for result in results.values()) else 0)