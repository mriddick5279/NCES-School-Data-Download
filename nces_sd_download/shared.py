"""Shared Selenium driver setup, per-state download loop, retry logic, and CSV
combining used for both public and private NCES school directory downloads."""

from __future__ import annotations

import logging, os, tempfile, time, shutil
import urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger("nces_sd_download")

DEFAULT_OUTPUT_DIR = Path.cwd() / ".output"

def has_downloaded_output() -> bool:
    """
    Determine if school data files have actually been downloaded

    Used by the Results page to show an empty state instead of trying to read
    files that aren't there.
    """
    return DEFAULT_OUTPUT_DIR.is_dir() and any(DEFAULT_OUTPUT_DIR.glob("*_sd.csv"))

def remove_output() -> None:
    """
    Delete output directory of files for when user choosed to 'Clear Downloads'
    """

    shutil.rmtree(DEFAULT_OUTPUT_DIR)

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

"""PipelineResult DataClass:

Represents the results of a pipeline run for a state/type pair.
Used to determine which states succeeded, failed, or were skipped (no results).
Contains the following attributes:
- type_name: str - "public" or "private", specifies type of school data downloaded
- downloads_root: Path - temporary directory where the state/type pair's Excel file was downloaded
- dataframes: dict[str, pd.DataFrame] - mapping of state name to its standardized DataFrame (only for states that succeeded)
- skipped_states: list[str] - list of state names that were skipped (no results found for this type)
- failed_states: list[str] - list of state names that failed to download or standardize after all retries were exhausted
"""
@dataclass
class PipelineResult:
    type_name: str
    downloads_root: Path
    dataframes: dict[str, pd.DataFrame] = field(default_factory=dict)
    skipped_states: list[str] = field(default_factory=list)
    failed_states: list[str] = field(default_factory=list)

"""StateOutcome DataClass:

Represents the outcome of processing a single state/type pair.
Contains the following attributes:
- state: str - name of the state/territory processed
- status: str - "ok", "skipped", or "failed", result of processing state/type pair
- dataframe: pd.DataFrame | None - the standardized DataFrame for this state/type pair, None value passed if state was skipped or failed
"""
@dataclass
class StateOutcome:
    state: str
    status: str  # "ok", "skipped", or "failed"
    dataframe: pd.DataFrame | None = None

# FIPS code used to build a throwaway probe URL for the reachability check below - DC,
# since it's always present in STATE_FIPS and returns a small result set either way.
PREFLIGHT_FIPS = "11"


def is_nces_reachable(url: str, timeout: float = 10) -> bool:
    """Check if NCES endpoints for state searches are available or not before scraping"""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except (urllib.error.URLError, OSError):
        return False


# Streamlit Community Cloud installs Chromium via packages.txt at these paths.
# When absent (local dev), fall back to Selenium Manager's own resolution instead.
CLOUD_CHROMIUM_BINARY = Path("/usr/bin/chromium")
CLOUD_CHROMEDRIVER_BINARY = Path("/usr/bin/chromedriver")

def build_chrome_options(download_dir: Path, headless: bool = True) -> webdriver.ChromeOptions:
    """Configure Chrome to auto-download into download_dir"""

    chrome_options = webdriver.ChromeOptions()
    prefs = {"download.default_directory": str(download_dir)}
    chrome_options.add_experimental_option("prefs", prefs)
    if headless:
        chrome_options.add_argument("--headless=new")

    if CLOUD_CHROMIUM_BINARY.exists():
        chrome_options.binary_location = str(CLOUD_CHROMIUM_BINARY)
        # Chrome refuses to run as root without --no-sandbox, and Streamlit Cloud's
        # container has too small a /dev/shm without --disable-dev-shm-usage.
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

    return chrome_options


def build_chrome_service() -> Service | None:
    """Point Selenium at the apt-installed chromedriver on Streamlit Community Cloud.
    Returns None locally so Selenium Manager resolves one as usual."""

    if CLOUD_CHROMEDRIVER_BINARY.exists():
        return Service(executable_path=str(CLOUD_CHROMEDRIVER_BINARY))
    return None


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
    this school type (i.e. terrirtories don't typically have private school data).
    """
    files_before = set(os.listdir(download_dir))

    # Fetch and wait for page with URL
    driver.get(url)
    wait = WebDriverWait(driver, action_timeout)

    # Determine if state/type pair has anything to download by waiting for the Excel link to appear
    try:
        excel_link = WebDriverWait(driver, no_results_timeout).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "excelclass"))
        )
    except TimeoutException:
        return None

    # Click Excel file link and wait for page to 'exist'
    excel_link.click()
    wait.until(EC.number_of_windows_to_be(2))

    # Switch to page and wait for 'Download Excel File' link to appear to downlaod state/type pair information
    driver.switch_to.window(driver.window_handles[-1])
    wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Download Excel File"))).click()

    # Wait for the download to complete by polling the download directory for a new Excel file
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

    # Determine if the download completed successfully or timed out
    if not new_files:
        raise TimeoutError(f"download did not complete within {download_timeout}s")

    return download_dir / new_files[0] # Return downloaded file path

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
    """Process the state/type pair by doing the following:

    1. Build download URL
    2. Download excel file into a temporary directory
    3. Transform the excel file into a DataFrame
    4. Write the DataFrame to a CSV file in the type_output_dir
    """

    # Build download URL for state/type pair
    url = type_config.URL_TEMPLATE.format(fips=fips)

    # Create temporary download directory for state/type pairs
    download_dir = downloads_root / state
    download_dir.mkdir(parents=True, exist_ok=True)

    attempt = 0
    while True:
        attempt += 1
        try:
            driver = None # Instantiate driver instance
            try:
                # Create the driver and download excel file to temporary download directory
                driver = webdriver.Chrome(
                    options=build_chrome_options(download_dir, headless),
                    service=build_chrome_service(),
                )
                excel_path = download_state_excel(driver, url, download_dir, **timeouts)

                if excel_path is None: # No data found for state/type pair (not a failure, just nothing to download)
                    logger.info("%s %s: no %s schools found, skipping", state, type_name, type_name)
                    return StateOutcome(state, "skipped")

                excel_tables = pd.read_html(excel_path) # Read state/type pair information into dataframes for standardization
            finally:
                if driver is not None:
                    driver.quit()

            # Standardize state/type pair information and save to CSV in temporary type output directory
            df = type_config.transform(excel_tables, state)
            df.to_csv(type_output_dir / f"{state}_sd.csv", index=False)

            # Log and return successful download and standardization of state/type pair information
            logger.info("%s %s: wrote %d rows", state, type_name, len(df))
            return StateOutcome(state, "ok", df)
        
        except Exception: # Error occurs: either attempt limit reach (failure) or download retry is needed
            logger.exception("%s %s: attempt %d/%d failed", state, type_name, attempt, retries + 1)
            if attempt > retries:
                return StateOutcome(state, "failed")

            # Backoff exponentially before retrying state/type pair download
            backoff = min(2 ** attempt, 30)
            logger.info("%s %s: retrying in %ds", state, type_name, backoff)
            time.sleep(backoff)


def run_pipeline(
    type_config,
    type_name: str,
    states: dict[str, str],
    output_dir: Path,
    retries: int = 2,
    headless: bool = True,
    max_workers: int = 5,
    **timeouts,
) -> PipelineResult:
    """Actual pipeline functionality for downloading, standardizing, and writing CSVs for state/type pairs.
    Achieved by doing the following:

    1. Create output directory for final output
    2. Create temporary download directory for state/territory files
    3. Create a thread pool and process each state/type pair concurrently
    4. Track results of each state/type pair download by determinnig whether it succeeded, failed, or skipped (no results)
    5. Return results to be used for reporting and merging
    """

    # Create absolute path to resolve with Chrome's download directory (which doesn't support relative paths)
    output_dir = Path(output_dir).resolve()

    type_output_dir = output_dir / type_name
    type_output_dir.mkdir(parents=True, exist_ok=True)

    # Create temp download directory for state/territory files
    downloads_root = Path(tempfile.mkdtemp(prefix=f"nces_{type_name}_"))
    logger.info("%s: downloads_root=%s", type_name, downloads_root)

    # Instantiate instance of PipelineResult to track results of each state/type pair download
    result = PipelineResult(type_name=type_name, downloads_root=downloads_root)

    # Create thread pool to execute state/type pair downloads concurrently
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                process_state, type_config, type_name, state, fips,
                type_output_dir, downloads_root, retries, headless, timeouts,
            )
            for state, fips in states.items()
        ]

        # As threads finish, store results of each state/type pair download in the PipelineResult instance
        for future in as_completed(futures):
            outcome = future.result()
            if outcome.status == "ok":
                assert outcome.dataframe is not None
                result.dataframes[outcome.state] = outcome.dataframe
            elif outcome.status == "skipped":
                result.skipped_states.append(outcome.state)
            else:
                result.failed_states.append(outcome.state)

    return result # Pass overall results back to caller for reporting and merging of public/private school information


def report_result(type_name: str, result: PipelineResult) -> None:
    """Log summary of a PipelineResult - succeeded/skipped/failed counts,
    plus the names of any failed states. Skipped states"""

    logger.info(
        "%s: %d succeeded, %d skipped, %d failed",
        type_name, len(result.dataframes), len(result.skipped_states), len(result.failed_states),
    )
    if result.failed_states:
        logger.warning("%s: failed states: %s", type_name, result.failed_states)


def combine_dataframes(dataframes: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge per-state DataFrames from one or more school types into a single DataFrame.

    Union of all columns to resolve schema differences between public and private school exports.
    Missing values filled with empty string
    """
    if not dataframes:
        return pd.DataFrame()
    combined = pd.concat(dataframes, ignore_index=True, sort=False)
    return combined.fillna("")


def merge_type_results(results: dict[str, PipelineResult], output_dir: Path) -> list[str]:
    """Merge results of public and private school information downloads into a single per-state CSV file.
    Cleans up subfolders created during pipeline execution
    """

    # Collect states/territories that succeeded across at least one type
    succeeded_states = {state for result in results.values() for state in result.dataframes}
    for state in sorted(succeeded_states):

        # Gather all dataframes for this state/territory for merging
        state_dataframes = [result.dataframes[state] for result in results.values() if state in result.dataframes]

        # Merge and write all dataframes for this state/territory into one CSV file
        combined = combine_dataframes(state_dataframes)

        combined['Billing City'] = combined['Billing City'].str.title()
        combined['County Name'] = combined['County Name'].str.title()

        combined['Account Name'] = combined['Account Name'].str.replace(',','')

        combined.to_csv(output_dir / f"{state}_sd.csv", index=False)

        # Remove downloaded per-type source files for this state
        for type_name in results:
            (output_dir / type_name / f"{state}_sd.csv").unlink(missing_ok=True)

    # Remove per-type subfolders
    for type_name in results:
        try:
            (output_dir / type_name).rmdir()
        except OSError:
            pass  # not empty (e.g. a stray leftover file) - leave it for inspection

    return sorted(succeeded_states) # Return states with successful downloads to caller for logging
