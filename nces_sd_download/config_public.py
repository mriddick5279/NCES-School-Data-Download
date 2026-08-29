"""Column config and data transform for NCES public-school directory downloads."""

import pandas as pd

URL_TEMPLATE = (
    "https://nces.ed.gov/ccd/schoolsearch/school_list.asp"
    "?Search=1&InstName=&SchoolID=&Address=&City=&State={fips}&Zip=&Miles=&County="
    "&PhoneAreaCode=&Phone=&DistrictName=&DistrictID=&SchoolType=1&SchoolType=2"
    "&SchoolType=3&SchoolType=4&SpecificSchlTypes=all&IncGrade=-1&LoGrade=-1&HiGrade=-1"
)

KEEP_COLS = [
    'NCES School ID', 'Low Grade', 'High Grade', 'School Name', 'District', 'County Name',
    'Street Address', 'City', 'State', 'ZIP', 'Phone', 'Locale Code', 'Charter', 'Students',
    'Teachers', 'Free Lunch', 'Reduced Lunch', 'Type', 'Status',
]

FINAL_COLS = [
    'NCES School ID', 'Low Grade', 'High Grade', 'Account Name', 'School District', 'County Name',
    'Billing Street', 'Billing City', 'Billing State', 'Billing ZIP', 'Phone', 'School Environment',
    'School Type', 'Number of Students Served', 'Number of Teachers', 'Free Lunch', 'Reduced Lunch',
    'Type', 'NCES Status',
]

# NCES locale codes: 11-13 urban, 21-23/31-33 suburban, 41-43 rural.
URBAN_CODES = [11, 12, 13]
SUBURBAN_CODES = [21, 22, 23, 31, 32, 33]
RURAL_CODES = [41, 42, 43]

_LEADING_ZERO_GRADES = ['01', '02', '03', '04', '05', '06', '07', '08', '09']


def transform(excel_tables, state):
    """Turn the raw tables from one state's public-school Excel export into a
    cleaned DataFrame matching FINAL_COLS. Does not write anything to disk."""
    df = pd.concat(excel_tables, ignore_index=True)

    df.columns = df.loc[5]
    # NCES flags a column with a trailing asterisk when that column's data comes from a
    # different (usually earlier) year than the rest of the row - strip it so column names
    # match KEEP_COLS regardless of whether this state's export has any flagged columns.
    df.columns = df.columns.astype(str).str.replace('*', '', regex=False)
    df = df[KEEP_COLS]
    df = df.loc[6:].reset_index(drop=True)

    free_lunch_empty_mask = (df['Free Lunch'] == '–') | (df['Free Lunch'] == '†') | (df['Free Lunch'] == '‡')
    reduced_lunch_empty_mask = (df['Reduced Lunch'] == '–') | (df['Reduced Lunch'] == '†') | (df['Reduced Lunch'] == '‡')
    num_students_empty_mask = (df['Students'] == '–') | (df['Students'] == '†') | (df['Students'] == '‡')
    num_teachers_empty_mask = (df['Teachers'] == '–') | (df['Teachers'] == '†') | (df['Teachers'] == '‡')
    county_name_empty_mask = (df['County Name'] == '–') | (df['County Name'] == '†') | (df['County Name'] == '‡')
    ungraded_grade_empty_mask = (df['Low Grade'] == '–') & (df['High Grade'] == '–')

    df.loc[free_lunch_empty_mask, 'Free Lunch'] = ''
    df.loc[~free_lunch_empty_mask, 'Free Lunch'] = df.loc[~free_lunch_empty_mask, 'Free Lunch'].astype(float).astype(str).str.replace(r'\.0$', '', regex=True)

    df.loc[reduced_lunch_empty_mask, 'Reduced Lunch'] = ''
    df.loc[~reduced_lunch_empty_mask, 'Reduced Lunch'] = df.loc[~reduced_lunch_empty_mask, 'Reduced Lunch'].astype(float).astype(str).str.replace(r'\.0$', '', regex=True)

    df.loc[num_students_empty_mask, 'Students'] = ''
    df.loc[~num_students_empty_mask, 'Students'] = df.loc[~num_students_empty_mask, 'Students'].astype(float).astype(str).str.replace(r'\.0$', '', regex=True)

    df.loc[num_teachers_empty_mask, 'Teachers'] = ''
    df.loc[~num_teachers_empty_mask, 'Teachers'] = df.loc[~num_teachers_empty_mask, 'Teachers'].astype(float).astype(str).str.replace(r'\.0$', '', regex=True)

    df.loc[county_name_empty_mask, 'County Name'] = ''

    df['Type'] = 'School'

    locale_code_numeric = pd.to_numeric(df['Locale Code'], errors='coerce')
    urban_mask = locale_code_numeric.isin(URBAN_CODES)
    suburban_mask = locale_code_numeric.isin(SUBURBAN_CODES)
    rural_mask = locale_code_numeric.isin(RURAL_CODES)

    df.loc[urban_mask, 'Locale Code'] = 'Urban'
    df.loc[suburban_mask, 'Locale Code'] = 'Suburban'
    df.loc[rural_mask, 'Locale Code'] = 'Rural'

    unrecognized_locale_mask = ~(urban_mask | suburban_mask | rural_mask)
    df.loc[unrecognized_locale_mask, 'Locale Code'] = ''

    df.loc[df['Low Grade'].isin(_LEADING_ZERO_GRADES), 'Low Grade'] = df['Low Grade'].str.lstrip('0')
    df.loc[df['High Grade'].isin(_LEADING_ZERO_GRADES), 'High Grade'] = df['High Grade'].str.lstrip('0')

    df.loc[ungraded_grade_empty_mask, ['Low Grade', 'High Grade']] = ''

    numeric_high_grade = pd.to_numeric(df['High Grade'], errors='coerce')
    df.loc[numeric_high_grade > 12, 'High Grade'] = '12'

    change_status_to_open_mask = df['Status'].isin(['Added', 'Changed Agency', 'Reopened'])
    df.loc[change_status_to_open_mask, 'Status'] = 'Open'

    charter_mask = df['Charter'] == 'Yes'
    df.loc[charter_mask, 'Charter'] = 'Charter'
    df.loc[~charter_mask, 'Charter'] = 'Public'

    df.loc['City'] = df['City'].str.title()
    df.loc['County Name'] = df['County Name'].str.title()

    df['State'] = state
    df.columns = FINAL_COLS

    return df
