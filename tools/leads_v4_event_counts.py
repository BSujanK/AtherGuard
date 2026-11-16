"""Leads v4 preflight addendum: assembly v2 events dated on each lead's target days (dates only, no level is read)."""
import json
import sys

from aetherguard.live import leads_v4_heldout as lh
from aetherguard.verify import heldout as vh

out = {}
for name, events in {"w1": lh.w1_events(), **lh.v2_event_sets()}.items():
    out[name] = {}
    for lead in lh.LEADS:
        days = [d for year in lh.YEARS for d in lh.target_days(year, lead)]
        kept, outside = vh.events_on_days(events, days)
        out[name][str(lead)] = {"events_on_days": int(len(kept.drop_duplicates(["cell_id", "date"]))),
                                "events_outside_days": int(outside),
                                "independent_slides_on_days": int(vh.distinct_events(kept)) if len(kept) else 0}
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), indent=1)
print(json.dumps(out))
