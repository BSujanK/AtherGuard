"""Exit 0 when every input of E1 and of the look panels exists, 1 otherwise (a job-runner gate, retried until it passes).

Inputs: the GFS 3-hour archive day of every June-September issue day 2021-2024, and the Early live window of each of those
days (study store for 2021-2023, the intensity store for 2024). Run with AETHERGUARD_DATA_DIR at the real data.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

from aetherguard.features import imerg_intensity as ii
from aetherguard.live import lead_intensity as li
from aetherguard.live import leads_v4_study as study


def main() -> int:
    missing = {}
    for year in (2021, 2022, 2023, 2024):
        days = study.season_days(year)
        gfs = [d for d in days if not li.store_path(li.default_store(), d).is_file()]
        early = [d for d in days if not (ii.imerg_hh._day_path(study.study_root(), li.EARLY, d).is_file()
                                         or ii.imerg_hh._day_path(ii.default_root(), li.EARLY, d).is_file())]
        if gfs or early:
            missing[year] = {"gfs3h": len(gfs), "early_live": len(early)}
    print("missing:", missing or "none", flush=True)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
