"""Column config and data transform for NCES private-school directory downloads."""

import pandas as pd

URL_TEMPLATE = (
    "https://nces.ed.gov/surveys/pss/privateschoolsearch/school_list.asp"
    "?Search=1&SchoolName=&SchoolID=&Address=&City=&State={fips}&Zip=&Miles=&County="
    "&PhoneAreaCode=&Phone=&Religion=&Association=&SchoolType=&Coed=&NumOfStudents="
    "&NumOfStudentsRange=more&IncGrade=-1&LoGrade=-1&HiGrade=-1"
)

KEEP_COLS = [
    'PSS_SCHOOL_ID', 'PSS_INST', 'LoGrade', 'HiGrade', 'PSS_ADDRESS', 'PSS_CITY',
    'PSS_STABB', 'PSS_ZIP5', 'PSS_PHONE', 'PSS_ENROLL_T', 'PSS_FTE_TEACH', 'PSS_RELIG',
    'PSS_COMM_TYPE', 'PSS_COUNTY_NAME', 'PSS_ASSOC_1', 'PSS_ASSOC_2', 'PSS_ASSOC_3',
]

FINAL_COLS = [
    'NCES School ID', 'Account Name', 'Low Grade', 'High Grade', 'Billing Street',
    'Billing City', 'Billing State', 'Billing ZIP', 'Phone', 'Number of Students Served',
    'Number of Teachers', 'School Type', 'School Environment', 'County Name',
]

# NCES's codes for ungraded schools; anything else is grade N encoded as N + 5.
GRADE_MAP = {'-1': '', '1': '', '2': 'PK', '3': 'KG', '4': 'KG', '5': 'KG'}


def transform(excel_tables, state):
    """Turn the raw tables from one state's private-school Excel export into a
    cleaned DataFrame matching FINAL_COLS. Does not write anything to disk."""
    df = pd.concat(excel_tables, ignore_index=True)

    df.columns = df.loc[4]
    df = df[KEEP_COLS]
    df = df.loc[5:].reset_index(drop=True)

    num_students_empty_mask = (df['PSS_ENROLL_T'] == '–') | (df['PSS_ENROLL_T'] == '†') | (df['PSS_ENROLL_T'].isna())
    num_teachers_empty_mask = (df['PSS_FTE_TEACH'] == '–') | (df['PSS_FTE_TEACH'] == '†') | (df['PSS_FTE_TEACH'].isna())
    ungraded_grade_empty_mask = (df['LoGrade'] == '–') & (df['HiGrade'] == '–')

    df.loc[num_students_empty_mask, 'PSS_ENROLL_T'] = ''
    df.loc[~num_students_empty_mask, 'PSS_ENROLL_T'] = df.loc[~num_students_empty_mask, 'PSS_ENROLL_T'].astype(int).astype(str)

    df.loc[num_teachers_empty_mask, 'PSS_FTE_TEACH'] = ''
    df.loc[~num_teachers_empty_mask, 'PSS_FTE_TEACH'] = df.loc[~num_teachers_empty_mask, 'PSS_FTE_TEACH'].astype(float).astype(str)

    urban_mask = df['PSS_COMM_TYPE'] == '1'
    suburban_mask = df['PSS_COMM_TYPE'].isin(['2', '3'])
    rural_mask = df['PSS_COMM_TYPE'] == '4'

    df.loc[urban_mask, 'PSS_COMM_TYPE'] = 'Urban'
    df.loc[suburban_mask, 'PSS_COMM_TYPE'] = 'Suburban'
    df.loc[rural_mask, 'PSS_COMM_TYPE'] = 'Rural'

    low_grade_kg_and_lower_mask = df['LoGrade'].isin(list(GRADE_MAP.keys()))
    high_grade_kg_and_lower_mask = df['HiGrade'].isin(list(GRADE_MAP.keys()))

    df.loc[low_grade_kg_and_lower_mask, 'LoGrade'] = df.loc[low_grade_kg_and_lower_mask, 'LoGrade'].map(GRADE_MAP)
    df.loc[high_grade_kg_and_lower_mask, 'HiGrade'] = df.loc[high_grade_kg_and_lower_mask, 'HiGrade'].map(GRADE_MAP)

    df.loc[~low_grade_kg_and_lower_mask, 'LoGrade'] = (df.loc[~low_grade_kg_and_lower_mask, 'LoGrade'].astype(int) - 5).astype(str)
    df.loc[~high_grade_kg_and_lower_mask, 'HiGrade'] = (df.loc[~high_grade_kg_and_lower_mask, 'HiGrade'].astype(int) - 5).astype(str)

    phone_empty_mask = (df['PSS_PHONE'] == '–') | (df['PSS_PHONE'] == '†') | (df['PSS_PHONE'].isna())
    phone_valid_mask = ~phone_empty_mask & df['PSS_PHONE'].str.match(r'^[2-9]\d{9}$')

    df.loc[phone_empty_mask | ~phone_valid_mask, 'PSS_PHONE'] = ''
    df.loc[phone_valid_mask, 'PSS_PHONE'] = (
        '(' + df.loc[phone_valid_mask, 'PSS_PHONE'].str.slice(0, 3)
        + ') ' + df.loc[phone_valid_mask, 'PSS_PHONE'].str.slice(3, 6)
        + '-' + df.loc[phone_valid_mask, 'PSS_PHONE'].str.slice(6)
    )

    df.loc['PSS_CITY'] = df['PSS_CITY'].str.title()
    df.loc['PSS_COUNTY_NAME'] = df['PSS_COUNTY_NAME'].str.title()

    df['PSS_STABB'] = state

    religious_mask = df['PSS_RELIG'].isin(['1', '2'])
    independent_mask = (
        df['PSS_ASSOC_1'].str.lower().str.contains('independent', na=False)
        | df['PSS_ASSOC_2'].str.lower().str.contains('independent', na=False)
        | df['PSS_ASSOC_3'].str.lower().str.contains('independent', na=False)
    )

    df.loc[religious_mask, 'PSS_RELIG'] = 'Parochial'
    df.loc[independent_mask, 'PSS_RELIG'] = 'Independent'
    df.loc[~religious_mask & ~independent_mask, 'PSS_RELIG'] = 'Private'

    df.drop(columns=['PSS_ASSOC_1', 'PSS_ASSOC_2', 'PSS_ASSOC_3'], inplace=True)

    df.columns = FINAL_COLS
    df['Type'] = 'School'

    return df
