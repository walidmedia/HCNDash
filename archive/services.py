import json

import pandas as pd

ALLOWED_EXTENSIONS = ("csv", "xlsx")


def parse_uploaded_file(uploaded_file):
    """Parse an uploaded .csv/.xlsx file into (columns, records).

    columns is an ordered list of column name strings.
    records is a list of dicts (one per row) with JSON-safe values,
    ready to store directly in Row.data.

    Raises ValueError with a user-facing message on any problem.
    """
    filename = uploaded_file.name or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file type. Please upload a .csv or .xlsx file.")

    try:
        if ext == "csv":
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file, engine="openpyxl")
    except pd.errors.EmptyDataError:
        raise ValueError("The uploaded file is empty.")
    except Exception as exc:
        raise ValueError(f"Could not parse the file: {exc}")

    df = df.dropna(axis=0, how="all")
    df.columns = [str(c).strip() for c in df.columns]

    if len(df.columns) == 0:
        raise ValueError("No columns were found in the uploaded file.")

    if len(set(df.columns)) != len(df.columns):
        raise ValueError("The uploaded file has duplicate column names.")

    columns = list(df.columns)
    # Round-tripping through JSON converts numpy/pandas scalar types (int64,
    # float64, Timestamp, NaN, ...) into plain JSON-safe Python values.
    records = json.loads(df.to_json(orient="records", date_format="iso"))
    return columns, records
