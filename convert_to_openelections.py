import argparse
import csv
import io
import re
from pathlib import Path

YEAR_TO_ELECTION_DATE = {
    1986: "19861104",
    1988: "19881108",
    1990: "19901106",
    1992: "19921103",
    1994: "19941108",
    1996: "19961105",
    1998: "19981103",
    2000: "20001107",
    2002: "20021105",
    2012: "20121106",
    2014: "20141104",
    2016: "20161108",
    2018: "20181106",
    2020: "20201103",
    2022: "20221108",
    2024: "20241105",
}

OFFICE_CLEANUPS = {
    "President and Vice President of the United States": "President",
    "President / Vice President": "President",
    "President - Vice Pres": "President",
    "Governor / Lt. Governor": "Governor",
}

COUNTY_FIXES = {
    "Prince George`s": "Prince George's",
    "Queen Anne`s": "Queen Anne's",
    "St. Mary`s": "St. Mary's",
}

COUNTY_CODE_TO_NAME = {
    "01": "Allegany",
    "02": "Anne Arundel",
    "03": "Baltimore City",
    "04": "Baltimore",
    "05": "Calvert",
    "06": "Caroline",
    "07": "Carroll",
    "08": "Cecil",
    "09": "Charles",
    "10": "Dorchester",
    "11": "Frederick",
    "12": "Garrett",
    "13": "Harford",
    "14": "Howard",
    "15": "Kent",
    "16": "Montgomery",
    "17": "Prince George's",
    "18": "Queen Anne's",
    "19": "St. Mary's",
    "20": "Somerset",
    "21": "Talbot",
    "22": "Washington",
    "23": "Wicomico",
    "24": "Worcester",
}


def normalize_office(raw: str) -> str:
    office = raw.strip().strip('"')
    office = re.sub(r"\s*-\s*Vote For.*$", "", office, flags=re.I)
    office = re.sub(r"\s*-\s*\(Vote for.*$", "", office, flags=re.I)
    office = office.strip(" -")
    return OFFICE_CLEANUPS.get(office, office)


def parse_candidate(cell: str) -> tuple[str, str, str]:
    text = cell.strip().strip('"')
    winner = ""

    if text.endswith(" Winner"):
        winner = "TRUE"
        text = text[:-7].rstrip()

    party = ""
    match = re.search(r"\(([^()]*)\)\s*$", text)
    if match:
        party = match.group(1).strip()
        candidate = text[:match.start()].strip()
    else:
        candidate = text

    candidate = re.sub(r"\s+", " ", candidate).strip()
    party = re.sub(r"\s+", " ", party).strip()
    return candidate, party, winner


def normalize_county(raw: str) -> str:
    county = raw.strip().strip('"').strip()
    county = re.sub(r"\s+County$", "", county, flags=re.I)
    county = re.sub(r"\s+city$", " City", county, flags=re.I)
    county = COUNTY_FIXES.get(county, county)
    county = county.replace("`", "'")
    return county


def read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    # Last attempt, surface the real error context.
    return path.read_text(encoding="utf-8-sig")


def convert_csv_style_file(input_path: Path, output_path: Path) -> int:
    rows_out = []
    office = None
    candidates = []

    text = read_text_with_fallback(input_path)
    with io.StringIO(text, newline="") as f:
        reader = csv.reader(f)

        for row in reader:
            row = [x.strip() for x in row]
            if not any(row):
                continue

            first = row[0].strip('"').strip()

            if (
                first
                and len([x for x in row[1:] if x]) <= 1
                and any(
                    marker in first
                    for marker in (
                        "Vote For",
                        "Vote for",
                        "Vote For One",
                        "Vote For One Pair",
                        "Vote for One Pair",
                    )
                )
            ):
                office = normalize_office(first)
                candidates = []
                continue

            if (not first) and office:
                candidates = []
                for cell in row[1:]:
                    cell = cell.strip()
                    if not cell:
                        continue
                    candidate, party, winner = parse_candidate(cell)
                    if candidate:
                        candidates.append((candidate, party, winner))
                continue

            if office and candidates and first:
                county = normalize_county(first)
                for idx, (candidate, party, winner) in enumerate(candidates, start=1):
                    if idx >= len(row):
                        continue
                    vote_cell = row[idx].strip().strip('"')
                    if vote_cell == "":
                        continue
                    vote_cell = vote_cell.replace(",", "")
                    try:
                        votes = int(vote_cell)
                    except ValueError:
                        continue

                    rows_out.append(
                        {
                            "county": county,
                            "precinct": "",
                            "office": office,
                            "district": "",
                            "party": party,
                            "candidate": candidate,
                            "votes": votes,
                            "winner": winner,
                        }
                    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "county",
                "precinct",
                "office",
                "district",
                "party",
                "candidate",
                "votes",
                "winner",
            ],
        )
        writer.writeheader()
        writer.writerows(rows_out)

    return len(rows_out)


def convert_pipe_style_file(input_path: Path, output_path: Path) -> int:
    rows_out = []
    with input_path.open("r", encoding="utf-8-sig", newline="") as f:
        for line in f:
            raw = line.rstrip("\n")
            if not raw.strip():
                continue

            parts = [p.strip() for p in raw.split("|")]
            if len(parts) < 10:
                continue

            office_raw = parts[0]
            county_raw = parts[2]
            last = parts[3]
            middle = parts[4]
            first = parts[5]
            party = parts[6]
            winner_flag = parts[7]
            votes_raw = parts[9]

            if votes_raw in ("", r"\N"):
                continue

            try:
                votes = int(votes_raw.replace(",", ""))
            except ValueError:
                continue

            name_parts = [x for x in (first, middle, last) if x and x != r"\N"]
            candidate = " ".join(name_parts).strip()
            if not candidate:
                candidate = "Unknown"

            if candidate.lower() == "other write-ins" or last.lower() == "zz998":
                candidate = "Other Write-Ins"

            party = "" if party == r"\N" else party
            winner = "TRUE" if winner_flag == "1" else ""

            rows_out.append(
                {
                    "county": normalize_county(county_raw),
                    "precinct": "",
                    "office": normalize_office(office_raw),
                    "district": "",
                    "party": party,
                    "candidate": candidate,
                    "votes": votes,
                    "winner": winner,
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "county",
                "precinct",
                "office",
                "district",
                "party",
                "candidate",
                "votes",
                "winner",
            ],
        )
        writer.writeheader()
        writer.writerows(rows_out)
    return len(rows_out)


def parse_int(value: str) -> int:
    if value is None:
        return 0
    text = str(value).strip().strip('"')
    if not text:
        return 0
    text = text.replace(",", "")
    try:
        return int(text)
    except ValueError:
        return 0


def convert_modern_precinct_csv(input_path: Path, output_path: Path) -> int:
    rows_out = []
    text = read_text_with_fallback(input_path)
    with io.StringIO(text, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return 0

        vote_columns = [
            c for c in reader.fieldnames
            if c and "Votes" in c and "Against" not in c
        ]

        for row in reader:
            county_name = (row.get("County Name") or "").strip()
            county_code = (row.get("County") or "").strip().zfill(2)
            if not county_name:
                county_name = COUNTY_CODE_TO_NAME.get(county_code, county_code)
            county = normalize_county(county_name)

            precinct = ""
            ep = (row.get("Election District - Precinct") or "").strip()
            if ep:
                precinct = ep
            else:
                ed = (row.get("Election District") or "").strip()
                pr = (row.get("Election Precinct") or "").strip()
                if ed or pr:
                    precinct = f"{ed}-{pr}"

            office = normalize_office((row.get("Office Name") or "").strip())
            district = (row.get("Office District") or "").strip().strip('"')
            candidate = (row.get("Candidate Name") or "").strip().strip('"')
            party = (row.get("Party") or "").strip().strip('"')
            winner_cell = (row.get("Winner") or "").strip().upper()
            winner = "TRUE" if winner_cell in {"Y", "TRUE", "1"} else ""

            votes = sum(parse_int(row.get(col, "")) for col in vote_columns)

            rows_out.append(
                {
                    "county": county,
                    "precinct": precinct,
                    "office": office,
                    "district": district,
                    "party": party,
                    "candidate": candidate,
                    "votes": votes,
                    "winner": winner,
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "county",
                "precinct",
                "office",
                "district",
                "party",
                "candidate",
                "votes",
                "winner",
            ],
        )
        writer.writeheader()
        writer.writerows(rows_out)
    return len(rows_out)


def detect_csv_format(input_path: Path) -> str:
    text = read_text_with_fallback(input_path)
    with io.StringIO(text, newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
    normalized = {h.strip().strip('"') for h in header}
    if "Candidate Name" in normalized and "Office Name" in normalized:
        return "modern"
    return "legacy"


def convert_file(input_path: Path, output_path: Path) -> int:
    if input_path.suffix.lower() == ".txt":
        return convert_pipe_style_file(input_path, output_path)
    fmt = detect_csv_format(input_path)
    if fmt == "modern":
        return convert_modern_precinct_csv(input_path, output_path)
    return convert_csv_style_file(input_path, output_path)


def build_output_name(input_name: str) -> str:
    m = re.match(r"^(\d{4})\s+General\s+Election\.(csv|txt)$", input_name, flags=re.I)
    if not m:
        raise ValueError(f"Unrecognized filename format: {input_name}")
    year = int(m.group(1))
    date_part = YEAR_TO_ELECTION_DATE.get(year)
    if not date_part:
        raise ValueError(f"No election date mapping for year {year}")
    return f"{date_part}__md__general__county.csv"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert historical Maryland general election files into OpenElections-style county CSVs."
    )
    parser.add_argument(
        "--data-dir",
        default="Data",
        help="Directory containing source election CSVs.",
    )
    parser.add_argument(
        "--output-dir",
        default="Data/openelections",
        help="Directory for converted OpenElections-style CSVs.",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)

    input_paths = sorted(
        p for p in data_dir.iterdir()
        if p.is_file() and re.match(r"^\d{4}\s+General\s+Election\.(csv|txt)$", p.name, flags=re.I)
    )

    for input_path in input_paths:
        output_name = build_output_name(input_path.name)
        output_path = output_dir / output_name
        row_count = convert_file(input_path, output_path)
        print(f"Wrote {output_path} ({row_count} rows)")


if __name__ == "__main__":
    main()
