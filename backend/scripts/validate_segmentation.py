"""Validate workout-structure detection and structure inference against
sessions whose Garmin activity name records the prescribed workout.

Run manually from backend/ (application code never imports this module):

    python scripts/validate_segmentation.py ../dataset/<export>.zip

The expected answer for each session (scripts/segmentation_labels.json) was
read off its activity name -- e.g. "400 x 10 組休1分鐘 84/圈" -> ten 400 m
reps -- and confirmed by the athlete. Sessions whose name does not state
every rep were left out. For every labelled session this reports:

  rep count   detection found as many reps as the name states
  exact       ... and every rep landed on the stated distance, in order
  inferred    the structure inferred from the run (workout_prescription.
              infer) expands to the same rep distances
  aligned     the label, used as the prescription, lines up with the
              detected reps without a distance mismatch (the 20 % tolerance
              in workout_prescription._distance_matches)

These are the evidence for the detection and inference settings listed in
WORKOUT_ANALYSIS_EVIDENCE.md. Detection uses the athlete's easy pace exactly
as import_garmin_fit_telemetry.py computes it.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from import_garmin_fit_telemetry import _iter_fit_files, _load_runs  # noqa: E402
from app.activity_structure import moving_median_speed  # noqa: E402

from app import workout_prescription  # noqa: E402
from app.fit_telemetry import FitParseError, parse_fit  # noqa: E402
from app.workout_segmentation import build_grid, detect_workout  # noqa: E402
from app.workout_analysis import segment_stats  # noqa: E402

LABELS = Path(__file__).with_name("segmentation_labels.json")


def _expanded(prescription: dict | None) -> list[int | None]:
    return [r.get("distance_m") for r in workout_prescription.expand(prescription)] if prescription else []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--out", type=Path, default=None, help="also write per-session results as JSON")
    args = parser.parse_args()
    labels = json.loads(args.labels.read_text(encoding="utf-8"))["sessions"]

    with zipfile.ZipFile(args.zip_path) as archive:
        runs = _load_runs(archive)
        by_start = {int(a["beginTimestamp"]) // 1000: a for a in runs}
        teles: dict[int, dict] = {}
        for _name, data in _iter_fit_files(archive):
            try:
                tele = parse_fit(data)
            except FitParseError:
                continue
            key = int(tele["start_time"].timestamp())
            if tele["sport"] == "running" and key in by_start:
                teles[by_start[key]["activityId"]] = tele

    easy = [s for t in teles.values() if detect_workout(t)["kind"] == "continuous"
            for s in [moving_median_speed(t)] if s]
    easy_speed = statistics.median(easy) if easy else None

    results = []
    for lab in labels:
        tele = teles.get(lab["activity_id"])
        row = {"review_no": lab["review_no"], "start_local": lab["start_local"], "name": lab["name"],
               "expected_m": lab["expected_m"]}
        if tele is None:
            row["missing_fit"] = True
            results.append(row)
            continue
        det = detect_workout(tele, easy_speed)
        g = build_grid(tele["samples"], tele.get("timer_events") or [])
        stats = [segment_stats(g, s, i) for i, s in enumerate(det["segments"])]
        reps = [s for s in stats if s["role"] == "work"]
        rests = [s for s in stats if s["role"] in ("rest", "set_rest")]
        detected = [r.get("nominal_m") for r in reps]
        inferred = workout_prescription.infer(reps, rests, "intervals") if reps else None
        label_presc = {"source": "activity_name", "blocks": [
            {"reps": 1, "distance_m": d, "duration_s": None, "targets_s_per_km": [], "rest_s": None}
            for d in lab["expected_m"]]}
        alignment = workout_prescription.align(label_presc, reps)
        row.update({
            "detected_m": detected,
            "rep_count": len(detected) == len(lab["expected_m"]),
            "exact": detected == lab["expected_m"],
            "inferred": _expanded(inferred) == lab["expected_m"],
            "aligned": len(reps) == len(lab["expected_m"]) and not alignment["blocking"],
        })
        results.append(row)

    checked = [r for r in results if not r.get("missing_fit")]
    for r in results:
        if r.get("missing_fit"):
            print(f"#{r['review_no']:>2} {r['start_local']}  no .fit file in the export")
            continue
        mark = "OK " if r["exact"] else "-- "
        print(f"{mark}#{r['review_no']:>2} {r['start_local']}  expected {r['expected_m']}  detected {r['detected_m']}")
    n = len(checked)
    print()
    print(f"labelled sessions: {len(results)}, with a .fit file: {n}, easy-pace baseline from {len(easy)} runs")
    for key, label in (("rep_count", "rep count matches"), ("exact", "exact (count and every distance)"),
                       ("inferred", "inferred structure matches"), ("aligned", "label aligns with detected reps")):
        print(f"  {label}: {sum(1 for r in checked if r[key])}/{n}")
    if args.out:
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
