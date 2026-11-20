"""Correction C03: narrow contract amendment recording the accepted F07 date-capacity timezone interpretation.

Writes resource_contract_R3_F07_amendment.json. resource_contract.json (R1) and the R2 addendum are not
modified. Worked examples are computed with zoneinfo, so their UTC boundaries are exact.
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
COR = HERE.parent
PKG = HERE.parents[2]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def span(day, tz):
    zone = ZoneInfo(tz)
    a = datetime.fromisoformat(day).replace(tzinfo=zone)
    b = (datetime.fromisoformat(day) + timedelta(days=1)).replace(tzinfo=zone)
    return {"date": day, "timezone": tz, "local_start": a.isoformat(timespec="minutes"),
            "local_end": b.isoformat(timespec="minutes"),
            "utc_start": a.astimezone(ZoneInfo("UTC")).isoformat(timespec="minutes"),
            "utc_end": b.astimezone(ZoneInfo("UTC")).isoformat(timespec="minutes"),
            "minutes": int((b.timestamp() - a.timestamp()) // 60)}


def main():
    examples = [
        {"case": "Working-time resource whose calendar is in Europe/London (project in Europe/Madrid)",
         "capacity_by_date": {"2027-03-29": 0}, "applies": span("2027-03-29", "Europe/London")},
        {"case": "Continuous reusable asset (no calendar): project timezone Europe/Madrid, spring DST day",
         "capacity_by_date": {"2027-03-28": 0}, "applies": span("2027-03-28", "Europe/Madrid")},
        {"case": "Continuous reusable asset: autumn DST day", "capacity_by_date": {"2027-10-31": 1},
         "applies": span("2027-10-31", "Europe/Madrid")},
        {"case": "Ordinary day, project calendar", "capacity_by_date": {"2027-01-11": 2},
         "applies": span("2027-01-11", "Europe/Madrid")},
    ]
    assert [e["applies"]["minutes"] for e in examples] == [1440, 1380, 1500, 1440]
    amendment = {
        "_meta": {"contract": "PMI Stage 5.4B resource contract", "version": "5.4B-R3-F07",
                  "amends": {"resource_contract.json": {"version": "5.4B-R1-draft", "sha256": sha(PKG / "resource_contract.json"),
                                                        "section": "entities.Resource.fields.capacity_by_date", "modified": False},
                             "resource_contract_R2_addendum.json": {"sha256": sha(PKG / "resource_contract_R2_addendum.json"),
                                                                    "modified": False}},
                  "origin": "Stage 5.4B.2 final verification finding F07, accepted interpretation",
                  "status": "PROPOSED clarification of an existing field; no new capability; not an engineering approval"},
        "capacity_by_date": {
            "type": "object: ISO calendar date (YYYY-MM-DD) -> nonnegative integer in the resource's declared unit",
            "date_timezone": {
                "calendar_resources": "The timezone of the resource's own calendar (calendar.timezone). 'project' "
                                      "calendars use the project timezone.",
                "continuous_resources": "The project timezone (resources with availability 'continuous' have no "
                                        "calendar of their own)."},
            "date_span": "From local midnight of the date to local midnight of the next date in that timezone, "
                         "half-open. On DST transition days the span is 23 h or 25 h, never a fixed 24 h.",
            "effect": "Replaces the declared capacity for every tick inside the span. Calendar availability still "
                      "governs working-time occupancy; continuous reservations are checked across the whole span, "
                      "including capacity changes inside a reservation interval.",
            "constraints": [
                "Date keys must be canonical ISO dates; values nonnegative integers (rates use the m3/h unit, scaled exactly with nominal and drawn rates).",
                "Span boundaries must align to the scheduling tick (TICK_MISALIGNED otherwise).",
                "An explicit-none resource may only declare 0.",
                "The resource must declare a unit compatible with its class.",
                "Duplicate date keys are invalid input."],
            "invalid": "INVALID_CAPACITY_OVERRIDE (MODEL_INVALID) before solving."},
        "worked_examples": examples,
        "acceptance_additions": [
            {"criterion_id": "AC-C03-1", "requirement": "Override span uses the resource calendar timezone",
             "pass_condition": "Europe/London resource override for 2027-03-29 applies from 2027-03-28T23:00Z to 2027-03-29T23:00Z"},
            {"criterion_id": "AC-C03-2", "requirement": "Continuous resources use the project timezone and DST-length days",
             "pass_condition": "Europe/Madrid 2027-03-28 spans 1380 minutes; 2027-10-31 spans 1500 minutes"},
            {"criterion_id": "AC-C03-3", "requirement": "Invalid overrides rejected before solving",
             "pass_condition": "non-ISO keys, negative/fractional values, missing unit, explicit-none > 0, duplicate keys -> MODEL_INVALID"}],
        "verified_by": "Stage 5.4B.2 final verification (verification_evidence.json timezone_checks and date_capacity)"}
    out = COR / "resource_contract_R3_F07_amendment.json"
    out.write_text(json.dumps(amendment, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"written": out.name, "examples": [(e["applies"]["date"], e["applies"]["timezone"], e["applies"]["utc_start"],
                                                        e["applies"]["utc_end"], e["applies"]["minutes"]) for e in examples]}, indent=1))


if __name__ == "__main__":
    main()
