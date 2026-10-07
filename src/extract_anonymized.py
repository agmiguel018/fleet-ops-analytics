"""Build the anonymized, money-indexed dataset from the private Vemov operations workbooks.

The private workbooks (one per vehicle and platform period) and a private JSON
config stay on the owner's machine. This script reads them and writes only
anonymized tables to data/anonymized/:

- vehicles, drivers and platforms become IDs (V01, D01, ...);
- no names, plates, phone numbers, pick-up locations, fuel stations or free-text
  notes are exported; notes are mapped to neutral stop categories;
- every monetary value is multiplied by a confidential factor (money index), so
  ratios, percentages and payback months are exact but amounts are not;
- fuel litres are not exported (with the public fuel price they would reveal the factor).

Before indexing, trips and net revenue are reconciled with each workbook's TOTAL row.

Usage (paths are given on the command line, never stored in the repo):

    python src/extract_anonymized.py --config <private.json> \
        --v1 <vehicle-1.xlsx> --v2-heetch <vehicle-2-heetch.xlsx> --v2-yango <vehicle-2-yango.xlsx>

Private config keys: money_factor, weekly_minimum_aoa, vehicles (acquisition and
insurance per vehicle), v01_routine_costs (wash and parking prices).
"""

import argparse
import json
import re
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "anonymized"

# Each source workbook = one vehicle, one driver, one platform, one settlement model
SOURCES = {
    "v1": {"vehicle_id": "V01", "driver_id": "D01", "platform": "Yango", "layout": "yango",
           "settlement": "weekly_minimum"},
    "v2_heetch": {"vehicle_id": "V02", "driver_id": "D02", "platform": "Heetch", "layout": "heetch",
                  "settlement": "full_remittance"},
    "v2_yango": {"vehicle_id": "V02", "driver_id": "D03", "platform": "Yango", "layout": "yango",
                 "settlement": "weekly_minimum"},
}
VEHICLE_INFO = {
    "V01": {"model": "Compact city car (automatic)", "financing": "finance lease"},
    "V02": {"model": "Compact city car", "financing": "cash"},
}

# Free-text notes -> neutral categories (order matters: first match wins)
STOP_RULES = [
    (r"descanso", "rest_day"),
    (r"ausente", "driver_absence"),
    (r"SEM MOTORISTA|DEMISSAO", "no_driver"),
    (r"rede", "network_outage"),
]
DATA_GAP = r"Capturas incompletas|Nao ha captura"
MONTHS = {"Julho": 7, "Agosto": 8, "Setembro": 9, "Outubro": 10}
MONEY = {
    "daily": ["gross_fares_aoa", "bonus_aoa", "platform_fees_aoa", "net_revenue_aoa", "wash_aoa", "fuel_aoa"],
    "trips": ["net_value_aoa"],
    "costs": ["amount_aoa"],
    "vehicles": ["acquisition_aoa", "insurance_annual_aoa"],
    "drivers": ["weekly_minimum_aoa"],
}


def table(path: Path, sheet: str, header: int = 3) -> pd.DataFrame:
    """Read a formatted sheet: header on row 4, keep only rows whose first column is a date."""
    df = pd.read_excel(path, sheet_name=sheet, header=header)
    first_col = df.columns[0]
    end = df[first_col].isna().idxmax() if df[first_col].isna().any() else len(df)
    df = df.iloc[:end]
    return df[pd.to_datetime(df[first_col], errors="coerce").notna()].copy()


def workbook_totals(path: Path) -> tuple[float, float]:
    """Trips and net revenue from the TOTAL row of the daily summary."""
    d = pd.read_excel(path, sheet_name="Resumo diario", header=3)
    total = d[d["Data"].astype(str).str.upper() == "TOTAL"].iloc[0]
    return float(total["Viagens"]), float(total["Ganho liquido"])


def classify(note, trips) -> tuple[str, bool]:
    note = "" if pd.isna(note) else str(note)
    for pattern, status in STOP_RULES:
        if re.search(pattern, note, re.I):
            return status, False
    gap = bool(re.search(DATA_GAP, note, re.I))
    return ("operated" if (trips or 0) > 0 or gap else "no_activity"), gap


def daily(path: Path, src: dict) -> pd.DataFrame:
    d = table(path, "Resumo diario")
    out = pd.DataFrame({"date": pd.to_datetime(d["Data"]).dt.date})
    out["trips"] = d["Viagens"].fillna(0).astype(int).values
    if src["layout"] == "yango":
        out["gross_fares_aoa"] = d["Numerario"].values
        out["bonus_aoa"] = d["Bonus"].values
        out["platform_fees_aoa"] = -(d["Taxa de servico"] + d["Servicos adic."] + d["Taxas de parceiro"]).values
        out["wash_aoa"] = 0.0
    else:
        out["gross_fares_aoa"] = d["Tarifa de viagem"].values
        out["bonus_aoa"] = 0.0
        out["platform_fees_aoa"] = -d["Comissao Heetch"].values
        out["wash_aoa"] = -d["Lavagem"].fillna(0).values
    out["net_revenue_aoa"] = d["Ganho liquido"].values
    out["fuel_aoa"] = -d["Combustivel"].fillna(0).values
    out["first_trip"] = d["1.a viagem"].astype(str).replace({"nan": None}).values
    out["last_trip"] = d["Ultima viagem"].astype(str).replace({"nan": None}).values
    status = [classify(n, t) for n, t in zip(d["Observacao"], out["trips"])]
    out["status"] = [s for s, _ in status]
    out["data_gap"] = [g for _, g in status]
    for key in ("vehicle_id", "driver_id", "platform"):
        out[key] = src[key]
    return out


def trips(path: Path, src: dict) -> pd.DataFrame:
    t = table(path, "Viagens")
    time_col = "Hora" if src["layout"] == "yango" else "Hora de inicio"
    value_col = "Valor" if src["layout"] == "yango" else "Valor liquido"
    out = pd.DataFrame({
        "date": pd.to_datetime(t["Data"]).dt.date.values,
        "start_time": t[time_col].astype(str).values,
        "net_value_aoa": t[value_col].values,
    })
    out = out[out["start_time"].str.match(r"^\d{1,2}:\d{2}")]  # pick-up location is never exported
    for key in ("vehicle_id", "driver_id", "platform"):
        out[key] = src[key]
    return out


def odometer(path: Path, src: dict) -> pd.DataFrame:
    k = table(path, "Quilometragem")
    out = pd.DataFrame({"date": pd.to_datetime(k.iloc[:, 0]).dt.date.values,
                        "odometer_km": pd.to_numeric(k.iloc[:, 1], errors="coerce").values})
    out["vehicle_id"] = src["vehicle_id"]
    return out.dropna()


def costs(path: Path, src: dict, days: pd.DataFrame, routine: dict) -> pd.DataFrame:
    """Dated cost events from the 'Custos' sheet (fuel and Heetch washes are in the daily table)."""
    raw = pd.read_excel(path, sheet_name="Custos", header=None)
    cell = lambda r, c: raw.iat[r, c] if c < raw.shape[1] else None
    rows = []
    if src["layout"] == "yango":
        section, event = None, None
        for i in range(len(raw)):
            c0, c3 = str(cell(i, 0)), str(cell(i, 3))
            if c0.startswith(("MANUTENCAO", "ORDENADOS", "LAVAGENS")):
                section = c0.split()[0]
            elif section == "MANUTENCAO" and c0.startswith("Revisao dos"):
                event = {"date": pd.to_datetime(cell(i, 1)).date(), "documented": True}
            if section == "MANUTENCAO" and event and "SEM FACTURA" in c3:
                event["documented"] = False
            if section == "MANUTENCAO" and event and c3 == "TOTAL DA INTERVENCAO":
                rows.append({**event, "category": "maintenance", "amount_aoa": float(cell(i, 4))})
                event = None
            if section == "ORDENADOS" and isinstance(cell(i, 3), (int, float)) and pd.notna(cell(i, 3)):
                month = MONTHS[str(cell(i, 2)).split()[0]]
                paid = pd.to_datetime(c0, errors="coerce")
                date = paid.date() if pd.notna(paid) else (pd.Timestamp(2026, month, 1) + pd.offsets.MonthEnd()).date()
                rows.append({"date": date, "category": "driver_salary", "amount_aoa": float(cell(i, 3)),
                             "documented": pd.notna(paid)})
            if c0.startswith("(-) Ordenado por vencer") and float(cell(i, 1) or 0) != 0:
                rows.append({"date": max(days["date"]), "category": "driver_salary",
                             "amount_aoa": -float(cell(i, 1)), "documented": False})
        if src["vehicle_id"] == "V01":
            # Washes (Wednesday and Saturday of operated weeks) and weekly parking: no receipts
            for d in days.itertuples():
                wd = pd.Timestamp(d.date).weekday()
                if d.status == "operated" and wd in (2, 5):
                    price = routine["wash_wednesday"] if wd == 2 else routine["wash_saturday"]
                    rows.append({"date": d.date, "category": "wash", "amount_aoa": float(price), "documented": False})
                rows.append({"date": d.date, "category": "parking", "amount_aoa": routine["parking_per_week"] / 7,
                             "documented": False})
    else:
        mapping = {"(-) Parqueamento": ("parking", "2026-08-31"), "(-) Suporte de telemovel": ("equipment", "2026-08-18"),
                   "(-) Ordenado pago": ("driver_salary", "2026-08-31"),
                   "(-) Manutencao preventiva": ("maintenance", "2026-09-03"),
                   "(-) Ordenado de 09/2026": ("driver_salary", "2026-09-03")}
        for i in range(len(raw)):
            c0 = str(cell(i, 0))
            for prefix, (category, date) in mapping.items():
                if c0.startswith(prefix):
                    rows.append({"date": pd.Timestamp(date).date(), "category": category,
                                 "amount_aoa": -float(cell(i, 1)), "documented": str(cell(i, 3)) in ("Sim", "Talao")})
    out = pd.DataFrame(rows, columns=["date", "category", "amount_aoa", "documented"])
    out["vehicle_id"] = src["vehicle_id"]
    return out


def fill_calendar(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Add the days a vehicle sat idle between two drivers (no workbook covers them)."""
    parts = []
    for vehicle, g in daily_df.groupby("vehicle_id"):
        g = g.set_index(pd.to_datetime(g["date"]))
        full = pd.date_range(g.index.min(), g.index.max(), freq="D")
        missing = full.difference(g.index)
        filler = pd.DataFrame({
            "date": missing.date, "vehicle_id": vehicle, "driver_id": None, "platform": None,
            "trips": 0, "gross_fares_aoa": 0.0, "bonus_aoa": 0.0, "platform_fees_aoa": 0.0,
            "net_revenue_aoa": 0.0, "wash_aoa": 0.0, "fuel_aoa": 0.0,
            "first_trip": None, "last_trip": None, "data_gap": False,
            "status": ["rest_day" if d.weekday() == 6 else "no_driver" for d in missing],
        })
        parts += [g.reset_index(drop=True), filler]
    return pd.concat(parts, ignore_index=True).sort_values(["vehicle_id", "date"]).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True, help="private JSON config (never commit it)")
    ap.add_argument("--v1", type=Path, required=True)
    ap.add_argument("--v2-heetch", type=Path, required=True)
    ap.add_argument("--v2-yango", type=Path, required=True)
    args = ap.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    paths = {"v1": args.v1, "v2_heetch": args.v2_heetch, "v2_yango": args.v2_yango}

    OUT.mkdir(parents=True, exist_ok=True)
    frames = {"daily": [], "trips": [], "odometer": [], "costs": []}
    for key, path in paths.items():
        src = SOURCES[key]
        days = daily(path, src)
        # Reconcile with the workbook's own TOTAL row before anything is transformed
        exp_trips, exp_net = workbook_totals(path)
        ok = days["trips"].sum() == exp_trips and abs(days["net_revenue_aoa"].sum() - exp_net) < 0.01
        print(("✅" if ok else "❌"), f"{src['driver_id']}: trips and net revenue match the workbook TOTAL row")
        assert ok, key
        frames["daily"].append(days)
        frames["trips"].append(trips(path, src))
        frames["odometer"].append(odometer(path, src))
        frames["costs"].append(costs(path, src, days, config["v01_routine_costs"]))

    tables = {name: pd.concat(parts, ignore_index=True) for name, parts in frames.items()}
    tables["odometer"] = tables["odometer"].drop_duplicates(["vehicle_id", "date"]).sort_values(["vehicle_id", "date"])
    tables["daily"] = fill_calendar(tables["daily"])
    tables["trips"] = tables["trips"].sort_values(["vehicle_id", "date", "start_time"])
    tables["vehicles"] = pd.DataFrame([
        {"vehicle_id": v["vehicle_id"], **VEHICLE_INFO[v["vehicle_id"]], "acquisition_date": v["acquisition_date"],
         "acquisition_aoa": v["acquisition_aoa"], "insurance_annual_aoa": v["insurance_annual_aoa"]}
        for v in config["vehicles"]
    ])
    drivers = (tables["daily"][tables["daily"]["status"] == "operated"]
               .groupby(["driver_id", "vehicle_id", "platform"], as_index=False)
               .agg(first_day=("date", "min"), last_day=("date", "max")))
    drivers["settlement_model"] = drivers["driver_id"].map({s["driver_id"]: s["settlement"] for s in SOURCES.values()})
    drivers["weekly_minimum_aoa"] = drivers["settlement_model"].map(
        {"weekly_minimum": config["weekly_minimum_aoa"], "full_remittance": None})
    tables["drivers"] = drivers

    # Money index: one confidential factor for every monetary column
    factor = config["money_factor"]
    for name, cols in MONEY.items():
        tables[name][cols] = tables[name][cols].astype(float) * factor

    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv", index=False, float_format="%.2f")
        print(f"{name:9s} {len(df):>5,} rows")


if __name__ == "__main__":
    main()
