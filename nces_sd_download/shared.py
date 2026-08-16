"""Shared Selenium driver setup, per-state download loop, retry logic, and CSV
combining used by both the public and private NCES school directory downloads."""

from __future__ import annotations

import logging, os, shutil, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger("nces_sd_download")

# State/territory -> FIPS code. Identical between the public and private NCES search forms.
STATE_FIPS = {
    'Alabama': '01',
    'Alaska': '02',
    'Arizona': '04',
    'Arkansas': '05',
    'California': '06',
    'Colorado': '08',
    'Connecticut': '09',
    'Delaware': '10',
    'DC': '11',
    'Florida': '12',
    'Georgia': '13',
    'Hawaii': '15',
    'Idaho': '16',
    'Illinois': '17',
    'Indiana': '18',
    'Iowa': '19',
    'Kansas': '20',
    'Kentucky': '21',
    'Louisiana': '22',
    'Maine': '23',
    'Maryland': '24',
    'Massachusetts': '25',
    'Michigan': '26',
    'Minnesota': '27',
    'Mississippi': '28',
    'Missouri': '29',
    'Montana': '30',
    'Nebraska': '31',
    'Nevada': '32',
    'New Hampshire': '33',
    'New Jersey': '34',
    'New Mexico': '35',
    'New York': '36',
    'North Carolina': '37',
    'North Dakota': '38',
    'Ohio': '39',
    'Oklahoma': '40',
    'Oregon': '41',
    'Pennsylvania': '42',
    'Rhode Island': '44',
    'South Carolina': '45',
    'South Dakota': '46',
    'Tennessee': '47',
    'Texas': '48',
    'Utah': '49',
    'Vermont': '50',
    'Virginia': '51',
    'Washington': '53',
    'West Virginia': '54',
    'Wisconsin': '55',
    'Wyoming': '56',
    'American Samoa': '60',
    'Guam': '66',
    'Northern Mariana Islands': '69',
    'Puerto Rico': '72',
    'U.S. Virgin Islands': '78',
}

# Entries in STATE_FIPS that aren't one of the 50 states: DC plus the five inhabited territories.
TERRITORIES = {'DC', 'American Samoa', 'Guam', 'Northern Mariana Islands', 'Puerto Rico', 'U.S. Virgin Islands'}

@dataclass
class PipelineResult:
    type_name: str
    dataframes: dict[str, pd.DataFrame] = field(default_factory=dict)
    skipped_states: list[str] = field(default_factory=list)
    failed_states: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return not self.failed_states


@dataclass
class StateOutcome:
    state: str
    status: str  # "ok", "skipped", or "failed"
    dataframe: pd.DataFrame | None = None

def build_chrome_options(download_dir: Path, headless: bool = True) -> webdriver.ChromeOptions:
    """Configure Chrome to auto-download into download_dir, matching the notebooks' setup."""
    chrome_options = webdriver.ChromeOptions()
    prefs = {"download.default_directory": str(download_dir)}
    chrome_options.add_experimental_option("prefs", prefs)
    if headless:
        chrome_options.add_argument("--headless=new")
    return chrome_options


def download_state_excel(
    driver: webdriver.Chrome,
    url: str,
    download_dir: Path,
    no_results_timeout: float = 5,
    action_timeout: float = 20,
    download_timeout: float = 30,
    poll_interval: float = 0.5,) -> Path | None:

    """Navigate to a state's search results and download its Excel export.

    Returns the downloaded file's path, or None if the state has no results for
    this school type (not an error - some states/territories genuinely have zero).
    """
    files_before = set(os.listdir(download_dir))
    driver.get(url)

    wait = WebDriverWait(driver, action_timeout)

    # Check quickly whether this state has any results before committing to the full
    # click/wait sequence - states with zero results won't have an Excel export link at all.
    try:
        excel_link = WebDriverWait(driver, no_results_timeout).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "excelclass"))
        )
    except TimeoutException:
        return None

    excel_link.click()
    wait.until(EC.number_of_windows_to_be(2))
    driver.switch_to.window(driver.window_handles[-1])
    wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Download Excel File"))).click()

    elapsed = 0.0
    new_files: list[str] = []
    while elapsed < download_timeout:
        new_files = [
            f for f in os.listdir(download_dir)
            if f not in files_before and f.endswith((".xlsx", ".xls"))
        ]
        if new_files:
            break
        time.sleep(poll_interval)
        elapsed += poll_interval

    if not new_files:
        raise TimeoutError(f"download did not complete within {download_timeout}s")

    return download_dir / new_files[0]

def remove_download_file(excel_path: Path) -> None:
    attempts = 5
    delay = 1.0

    for attempt in range(attempts):
        try:
            excel_path.unlink(missing_ok=True)
            return
        except PermissionError as e:
            logger.warning(f"Attempt {attempt + 1} to delete {excel_path} failed: {e}")
            time.sleep(delay)

def process_state(
    type_config,
    type_name: str,
    state: str,
    fips: str,
    type_output_dir: Path,
    downloads_root: Path,
    retries: int,
    headless: bool,
    timeouts: dict,
) -> StateOutcome:
    """Attempt one state up to retries+1 times, in its own isolated download
    directory so concurrent workers never collide over the same folder.

    download_dir is keyed by state name (unique per worker) rather than
    tempfile.mkdtemp, and lives under downloads_root, which the caller
    (run_pipeline) owns and removes once the whole pipeline run is done.
    """
    url = type_config.URL_TEMPLATE.format(fips=fips)
    download_dir = downloads_root / state
    download_dir.mkdir(parents=True, exist_ok=True)

    try:
        attempt = 0
        while True:
            attempt += 1
            driver = None
            try:
                driver = webdriver.Chrome(options=build_chrome_options(download_dir, headless))
                excel_path = download_state_excel(driver, url, download_dir, **timeouts)

                if excel_path is None:
                    logger.info("%s %s: no %s schools found, skipping", state, type_name, type_name)
                    return StateOutcome(state, "skipped")
                
                excel_tables = pd.read_html(excel_path)
                try:
                    df = type_config.transform(excel_tables, state)
                    df.to_csv(type_output_dir / f"{state}_sd.csv", index=False)
                    logger.info("%s %s: wrote %d rows", state, type_name, len(df))
                finally:
                    remove_download_file(excel_path)
                return StateOutcome(state, "ok", df)
            except Exception:
                logger.exception("%s %s: attempt %d/%d failed", state, type_name, attempt, retries + 1)
                if attempt > retries:
                    return StateOutcome(state, "failed")
            finally:
                if driver is not None:
                    driver.quit()
    finally:
        shutil.rmtree(download_dir, ignore_errors=True)


def run_pipeline(
    type_config,
    type_name: str,
    states: dict[str, str],
    output_dir: Path,
    retries: int = 2,
    headless: bool = True,
    max_workers: int = 10,
    **timeouts,
) -> PipelineResult:
    """Download and transform every state for one school type, concurrently.

    type_config must expose URL_TEMPLATE (a str with a {fips} placeholder) and
    transform(excel_tables, state) -> pd.DataFrame.

    Runs up to max_workers states at once, each with its own Chrome driver and its
    own isolated download directory. Writes one CSV per successful state to
    output_dir/type_name/{state}_sd.csv and returns a PipelineResult with the
    collected DataFrames plus which states were skipped (zero results) or failed
    (after exhausting retries). Extra keyword args are forwarded to
    download_state_excel as timeout overrides.
    """
    # Chrome's download.default_directory pref requires an absolute path - a
    # relative one (e.g. --output-dir test) can't be resolved against Chrome's
    # own working directory, so it silently falls back to the real Downloads
    # folder instead of raising, and the poller in download_state_excel then
    # times out watching a directory nothing ever gets written to.
    output_dir = Path(output_dir).resolve()

    type_output_dir = output_dir / type_name
    type_output_dir.mkdir(parents=True, exist_ok=True)

    # Base folder for this run's per-state download dirs. Each worker gets its
    # own state-named subfolder (see process_state) and cleans that subfolder
    # up as it finishes; this rmtree in the finally below is the one true
    # end-of-process cleanup, run once all workers have completed or failed.
    downloads_root = type_output_dir / ".downloads"
    downloads_root.mkdir(parents=True, exist_ok=True)

    result = PipelineResult(type_name=type_name)

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    process_state, type_config, type_name, state, fips,
                    type_output_dir, downloads_root, retries, headless, timeouts,
                )
                for state, fips in states.items()
            ]
            for future in as_completed(futures):
                outcome = future.result()
                if outcome.status == "ok":
                    assert outcome.dataframe is not None
                    result.dataframes[outcome.state] = outcome.dataframe
                elif outcome.status == "skipped":
                    result.skipped_states.append(outcome.state)
                else:
                    result.failed_states.append(outcome.state)
    finally:
        shutil.rmtree(downloads_root, ignore_errors=True)

    return result


def report_result(type_name: str, result: PipelineResult) -> None:
    """Log a summary of one type's PipelineResult - succeeded/skipped/failed counts,
    plus the names of any failed states so they're not just a number. Skipped states
    aren't warning-worthy (a state genuinely having zero results for a type is valid
    data, not an error) but failed ones usually indicate something worth a look."""
    logger.info(
        "%s: %d succeeded, %d skipped, %d failed",
        type_name, len(result.dataframes), len(result.skipped_states), len(result.failed_states),
    )
    if result.failed_states:
        logger.warning("%s: failed states: %s", type_name, result.failed_states)


def combine_dataframes(dataframes: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge per-state DataFrames from one or more school types into a single DataFrame.

    Column sets don't need to match - pd.concat unions them, and any column a given
    row's type doesn't have gets filled blank instead of left as NaN.
    """
    if not dataframes:
        return pd.DataFrame()
    combined = pd.concat(dataframes, ignore_index=True, sort=False)
    return combined.fillna("")


def merge_type_results(results: dict[str, PipelineResult], output_dir: Path) -> list[str]:
    """Merge each state's per-type results (e.g. public + private) into one
    {state}_sd.csv per state directly under output_dir, then remove the now-redundant
    per-type source files and, once empty, the per-type subfolders themselves.

    results maps type_name -> that type's PipelineResult, as returned by run_pipeline.
    Returns the sorted list of states that had at least one successful result to merge.
    """
    succeeded_states = {state for result in results.values() for state in result.dataframes}
    for state in sorted(succeeded_states):
        state_dataframes = [result.dataframes[state] for result in results.values() if state in result.dataframes]
        combined = combine_dataframes(state_dataframes)
        combined.to_csv(output_dir / f"{state}_sd.csv", index=False)

        for type_name in results:
            (output_dir / type_name / f"{state}_sd.csv").unlink(missing_ok=True)

    for type_name in results:
        try:
            (output_dir / type_name).rmdir()
        except OSError:
            pass  # not empty (e.g. a stray leftover file) - leave it for inspection rather than force-delete

    return sorted(succeeded_states)
