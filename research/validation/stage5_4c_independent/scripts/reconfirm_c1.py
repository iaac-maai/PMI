"""Independent C1 reconfirmation attacks against the committed IFC4D exporter (IFC interpreter, repo root)."""

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO))
from pmi_core.adapters.ifc4d import _export_live, export_controlled_ifc4d  # noqa: E402  (system under test)

IFCPY, PLAN = REPO / ".venv/Scripts/python.exe", REPO / ".venv-planning/Scripts/python.exe"
SOURCE = REPO / "research/implementation/stage5_2/controlled_frame.ifc"
ACC = REPO / "research/implementation/stage5_4b_integration"
CONFIG = ACC / "r0_config.json"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def attempt(fn, out):
    try:
        fn()
        return {"accepted": True, "message": "", "output_created": out.exists()}
    except Exception as e:  # noqa: BLE001
        return {"accepted": False, "message": f"{type(e).__name__}: {e}"[:160], "output_created": out.exists()}


def shift_last(s, days=1):
    last = max(s["activities"], key=lambda a: a["optimized"]["finish"])
    st, fi = (datetime.fromisoformat(last["optimized"][k]) + timedelta(days=days) for k in ("start", "finish"))
    last["optimized"].update(start=st.isoformat(timespec="minutes"), finish=fi.isoformat(timespec="minutes"),
                             segments=[[st.isoformat(timespec="minutes"), fi.isoformat(timespec="minutes")]])
    return s


def main():
    tmp = Path(tempfile.mkdtemp(prefix="pmi_c1_"))
    res = {"head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()}
    try:
        # a genuine live schedule (with evidence) from the application, 5-min
        live = tmp / "live5"
        p = subprocess.run([str(PLAN), "-B", "-m", "pmi_core.application", "--config", str(CONFIG), "--output", str(live),
                            "--tick", "5", "--ifc4d", "--ifc-python", str(IFCPY), "--planning-python", str(PLAN)],
                           cwd=REPO, capture_output=True, text=True)
        res["live_run_exit"] = p.returncode
        live_bytes = (live / "schedule.json").read_bytes()
        genuine = json.loads(live_bytes)
        base = json.loads((ACC / "r0_5_schedule.json").read_bytes())
        n = [0]

        def write(obj):
            n[0] += 1
            f = tmp / f"s{n[0]}.json"
            f.write_bytes(json.dumps(obj, indent=2).encode())
            return f, tmp / f"o{n[0]}"

        a1 = shift_last(copy.deepcopy(base))
        a2 = copy.deepcopy(a1)
        newspan = a2["proof"]["project_makespan_minutes"] + 1440
        a2["proof"]["project_makespan_minutes"] = newspan
        a2["proof"]["makespan_by_scope_minutes"]["complete_project"] = newspan
        a3 = copy.deepcopy(a2)
        a3["proof"]["lower_bound_minutes"] = newspan
        att = {}
        for name, obj in (("A1 shift, proof unchanged (standalone)", a1), ("A2 shift + makespan adjusted (standalone)", a2),
                          ("A3 shift + makespan + lower bound adjusted (standalone)", a3)):
            f, o = write(obj)
            att[name] = attempt(lambda: export_controlled_ifc4d(SOURCE, f, o), o)
        # A4: live path with a caller-generated digest of the forged bytes (no evidence)
        f, o = write(a3)
        att["A4 A3 via live path with caller-generated digest"] = attempt(lambda: _export_live(SOURCE, f, o, sha(f.read_bytes())), o)
        # A5: forged content carrying genuine application evidence + caller digest
        a5 = shift_last(copy.deepcopy(genuine))
        a5["proof"]["project_makespan_minutes"] += 1440
        a5["proof"]["makespan_by_scope_minutes"]["complete_project"] += 1440
        a5["proof"]["lower_bound_minutes"] += 1440
        f, o = write(a5)
        att["A5 forged content + genuine evidence, live path, caller digest"] = attempt(lambda: _export_live(SOURCE, f, o, sha(f.read_bytes())), o)
        # A6: genuine content, digest of different bytes
        f, o = write(genuine)
        att["A6 genuine content, mismatching run digest"] = attempt(lambda: _export_live(SOURCE, f, o, "0" * 64), o)
        # A7: genuine content, only runtimes changed (expected accepted: excluded by design)
        a7 = copy.deepcopy(genuine)
        a7["proof"]["runtime_seconds"] = 123.0
        f, o = write(a7)
        att["A7 genuine content, runtime fields altered (live)"] = attempt(lambda: _export_live(SOURCE, f, o, sha(f.read_bytes())), o)
        # A8: genuine content, interpreter metadata spoofed (expected accepted: excluded by design)
        a8 = copy.deepcopy(genuine)
        a8["evidence"]["runtimes"]["planning"]["version"] = "0.0.0-spoofed"
        f, o = write(a8)
        att["A8 genuine content, interpreter metadata spoofed (live)"] = attempt(lambda: _export_live(SOURCE, f, o, sha(f.read_bytes())), o)
        # A9: registered artifact bytes but a different source IFC
        alt = tmp / "alt.ifc"
        alt.write_bytes(SOURCE.read_bytes().replace(b"ENDSEC;", b"/*x*/ENDSEC;", 1))
        o = tmp / "o_alt"
        att["A9 registered schedule with altered IFC"] = attempt(lambda: export_controlled_ifc4d(alt, ACC / "r0_5_schedule.json", o), o)
        # A10: forged activity duration consistent with baseline edits (baseline also edited) + proof adjusted
        a10 = copy.deepcopy(a3)
        last = max(a10["activities"], key=lambda a: a["optimized"]["finish"])
        last["baseline"]["start"], last["baseline"]["finish"] = last["optimized"]["start"], last["optimized"]["finish"]
        f, o = write(a10)
        att["A10 A3 + matching baseline edits (standalone)"] = attempt(lambda: export_controlled_ifc4d(SOURCE, f, o), o)
        res["attacks"] = att
        # Replay of registered artifacts (LF and CRLF)
        rep = {}
        for tick in (5, 15):
            src = ACC / f"r0_{tick}_schedule.json"
            o = tmp / f"rep{tick}"
            rep[f"r0_{tick} as committed"] = attempt(lambda: export_controlled_ifc4d(SOURCE, src, o), o)
            crlf = tmp / f"crlf{tick}.json"
            crlf.write_bytes(src.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            o = tmp / f"repc{tick}"
            rep[f"r0_{tick} CRLF copy"] = attempt(lambda: export_controlled_ifc4d(SOURCE, crlf, o), o)
        res["replay"] = rep
        # Live digest chain
        ev = json.loads((live / "pipeline_evidence.json").read_bytes())
        rt = json.loads((live / "ifc4d/round_trip.json").read_bytes())
        res["live_digest_chain"] = {"schedule_json": sha(live_bytes), "pipeline_evidence": ev["stage_payload_sha256"].get("schedule"),
                                    "round_trip_provenance": rt["provenance"]["ScheduleSha256"],
                                    "all_equal": sha(live_bytes) == ev["stage_payload_sha256"].get("schedule") == rt["provenance"]["ScheduleSha256"]}
        # CLI exit codes for A1
        f, o = write(a1)
        cli = subprocess.run([str(IFCPY), "-B", "-m", "pmi_core.adapters.ifc4d", "--source", str(SOURCE), "--schedule", str(f), "--output", str(o)],
                             cwd=REPO, capture_output=True, text=True)
        res["A1_cli"] = {"exit": cli.returncode, "message": (cli.stderr or cli.stdout).strip()[-160:], "output_created": o.exists()}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    (OUT / "c1_reconfirmation_results.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
