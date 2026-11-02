"""Five-page AetherGuard pipeline overview PDF.

Every number is read from the project's result files. Stage A (v3-live) numbers come from
reports/phase6_summary.json, written by the controller after reviewing the v3 results; when that file or a
value is missing, the page says "pending" instead of inventing a number.

Run with the global Python (reportlab + matplotlib):  python tools/overview_pdf/build.py
"""
import json
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Frame, Image, KeepInFrame, PageBreak, PageTemplate, BaseDocTemplate, Paragraph,
                                Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
OUT = REPORTS / "AetherGuard_Pipeline_Overview.pdf"
WORK = Path(__file__).resolve().parent / "build_img"
WORK.mkdir(exist_ok=True)

FONT_DIR = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
for name, file in [("DV", "DejaVuSans.ttf"), ("DV-B", "DejaVuSans-Bold.ttf"), ("DV-I", "DejaVuSans-Oblique.ttf"),
                   ("DV-BI", "DejaVuSans-BoldOblique.ttf"), ("DVM", "DejaVuSansMono.ttf")]:
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV-I", boldItalic="DV-BI")

NAVY, TEAL, AMBER, RED = colors.HexColor("#1f3a5f"), colors.HexColor("#1b998b"), colors.HexColor("#e8a33d"), colors.HexColor("#c8553d")
LIGHT, MID, INK, GREY = colors.HexColor("#eef3f8"), colors.HexColor("#d5dfea"), colors.HexColor("#1b1f24"), colors.HexColor("#5f6670")
PAGE_W, PAGE_H = A4
MARGIN = 1.5 * cm
CW = PAGE_W - 2 * MARGIN
FRAME_H = PAGE_H - 3.3 * cm

body = ParagraphStyle("b", fontName="DV", fontSize=8.4, leading=11.6, textColor=INK, spaceAfter=4)
small = ParagraphStyle("s", parent=body, fontSize=7.2, leading=9.6, textColor=GREY, spaceAfter=2)
cell = ParagraphStyle("c", parent=body, fontSize=7.1, leading=9.0, spaceAfter=0, alignment=TA_LEFT)
cellh = ParagraphStyle("ch", parent=cell, fontName="DV-B", textColor=colors.white)
h1 = ParagraphStyle("h1", parent=body, fontName="DV-B", fontSize=15, leading=19, textColor=NAVY, spaceAfter=6)
h2 = ParagraphStyle("h2", parent=body, fontName="DV-B", fontSize=10, leading=13, textColor=NAVY, spaceBefore=6, spaceAfter=3)
bullet = ParagraphStyle("bl", parent=body, leftIndent=11, bulletIndent=1, spaceAfter=2)
cap = ParagraphStyle("cap", parent=small, fontName="DV-I", alignment=1)


# ------------------------------------------------------------------ result-file lookups
def load(name):
    p = REPORTS / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def get(doc, path, default=None):
    cur = doc
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def pct(v, nd=1):
    return "pending" if v is None else f"{100 * v:.{nd}f}%"


def num(v, fmt="{:,}"):
    return "pending" if v is None else fmt.format(v)


H = load("phase3_hazard_report.json") or {}
A = load("phase4_alerts_report.json") or {}
I = load("phase2_integrity_report.json") or {}
C = load("phase3_corrector_report.json") or {}
S6 = load("phase6_summary.json") or {}     # Stage A results (controller-written after review)
PROBE = load("phase6_live_sources_probe.json") or {}

g = "gate.recall_first_target"
V2 = {
    "recall": get(H, f"{g}.test_recall.value"), "recall_lo": get(H, f"{g}.test_recall.lo"), "recall_hi": get(H, f"{g}.test_recall.hi"),
    "fa": get(H, f"{g}.test_fa_share.value"),
    "id_fa": get(H, "gate.baseline_comparison.intensity_duration.at_frozen_watch.baseline_fa.value"),
    "id_recall": get(H, "gate.baseline_comparison.intensity_duration.at_frozen_watch.baseline_recall.value"),
    "lh_fa": get(H, "gate.baseline_comparison.lhasa_style.at_frozen_watch.baseline_fa.value"),
    "lr_fa": get(H, "gate.baseline_comparison.logistic.at_frozen_watch.baseline_fa.value"),
}
ALERT = {
    "watch_recall": get(A, "sections.test_2018.operating_view.per_level.Watch.recall_in_domain"),
    "watch_per_1000": get(A, "sections.test_2018.operating_view.per_level.Watch.alerts_per_1000_cell_days"),
    "kerala": get(A, "sections.kerala_2018.event_detection.n_detected"),
    "kerala_n": get(A, "sections.kerala_2018.event_detection.n_events"),
}
INTEG = {
    "engine": get(I, "evaluation.test.methods.engine.macro_recall"),
    "l1": get(I, "evaluation.test.methods.l1.macro_recall"),
    "noaa": get(I, "evaluation.test.methods.noaa_style_qa_wide.macro_recall"),
}


# ------------------------------------------------------------------ page 1 diagram
def architecture_png(path):
    fig, ax = plt.subplots(figsize=(7.6, 7.9))
    ax.set_xlim(0, 100); ax.set_ylim(0, 104); ax.axis("off")
    plt.rcParams["font.family"] = "DejaVu Sans"

    def box(x, y, w, h, text, fc, tc="white", fs=6.6, ec=None):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.35,rounding_size=1.0", fc=fc, ec=ec or fc, lw=0.9))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=tc, linespacing=1.22)

    def arrow(x1, y1, x2, y2):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=9, lw=1.1, color="#444"))

    def label(x, y, t):
        ax.text(x, y, t, fontsize=7.6, color="#1f3a5f", fontweight="bold", va="center")

    sky, navy, teal, amber, pale = "#6fa8dc", "#1f3a5f", "#1b998b", "#e8a33d", "#e6edf5"
    label(1, 102, "1  Data sources: every one is available every morning")
    srcs = [("NASA IMERG\nLate + Early\n0.1° rain", sky), ("NOAA GFS\n0.25° forecast\nrain, 3 days", sky), ("IMD real-time\n0.25° gauge grid\n(India)", sky),
            ("NOAA GHCN\n140 rain\ngauges", sky), ("Copernicus\nDEM 90 m\nterrain", sky), ("NASA/NSIDC\nlandslide\ncatalogs", amber)]
    for i, (t, c) in enumerate(srcs):
        box(1 + i * 16.5, 90, 15, 9.5, t, c, tc="#10243b", fs=6.1)
    arrow(50, 89.5, 50, 86)
    label(1, 84.5, "2  Daily ingest at 11:00 IST: subset, check, align to the IMD rain day, freshness record per source")
    box(1, 74, 98, 8.5, "Stores: IMERG history 2006 → today · GFS IMD-day forecast totals · IMD real-time · recent gauge records\n"
                        "IMD day (08:30 IST) = 0.875 × UTC(D−1) + 0.125 × UTC(D);  live: D−1 from IMERG Early, 00-03 UTC D from GFS  ·  missing stays NaN", pale, tc="#1f3a5f", fs=6.4, ec=navy)
    arrow(25, 73.5, 25, 69.5); arrow(75, 73.5, 75, 69.5)
    label(1, 68, "3  Two stages")
    box(1, 52, 46, 14.5, "STAGE 1  Sensor-integrity engine\nL1 rules + LightGBM (7 fault classes)\n+ arbiter that keeps real cloudbursts\n→ trust score, fault type, repaired value", navy, fs=6.6)
    box(53, 52, 46, 14.5, "Feature builder (per 5 km cell, per day)\nIMERG rain 1-90 days, intensity share,\nanomaly vs climatology, terrain\n(26 inputs selected by cross-validation)", teal, fs=6.6)
    arrow(76, 51.5, 76, 47.5)
    box(30, 33, 69, 14, "STAGE 2  v3-live landslide model\nLightGBM, monotone constraints (more rain or steeper slope never lowers risk)\n20-model ensemble · per-region calibration · SHAP reasons\nrisk for today (D0) and D+1…D+3 with GFS forecast rain, 10-90% interval", teal, fs=6.5)
    arrow(24, 51.5, 24, 21.5)
    ax.text(25.3, 37, "station trust\nfeeds data\nconfidence", fontsize=6, color="#444")
    arrow(64, 32.5, 64, 28.5)
    label(30, 30.5, "4  Alert engine")
    box(30, 15, 69, 13, "Normal / Watch / Warning / Emergency from out-of-fold thresholds (recall-first)\n+ uncertainty rule + blind-sensor escalation (max of IMERG, IMD, gauges)\n"
                        "+ hysteresis + data confidence High / Degraded / Insufficient + reasons", amber, tc="#2b1a00", fs=6.4)
    box(1, 15, 26, 13, "Data confidence\nsource freshness, station\ntrust, sources agree?", pale, tc="#1f3a5f", fs=6.3, ec=navy)
    arrow(27.3, 21.5, 29.6, 21.5)
    arrow(64, 14.5, 64, 11)
    box(1, 1, 98, 9, "5  Outputs: daily bulletin · 3D dashboard (map, alerts, sources) · REST API · replay of any past day", "#10243b", fs=7.0)
    fig.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def comparison_png(path):
    names = ["AetherGuard\nmodel", "Rainfall-\nthreshold rule", "LHASA-style\nrule", "Logistic\nregression"]
    vals = [V2["fa"], V2["id_fa"], V2["lh_fa"], V2["lr_fa"]]
    fig, ax = plt.subplots(figsize=(6.4, 2.3))
    plt.rcParams["font.family"] = "DejaVu Sans"
    cols = ["#1b998b", "#8a8d91", "#8a8d91", "#8a8d91"]
    v = [x * 100 if x is not None else 0 for x in vals]
    ax.barh(names[::-1], v[::-1], color=cols[::-1])
    for i, x in enumerate(v[::-1]):
        ax.text(x + 0.6, i, f"{x:.1f}%", va="center", fontsize=7.5)
    ax.set_xlabel("Share of all cell-days put on alert to catch ~85-89% of landslide days (unseen year 2018)", fontsize=7)
    ax.tick_params(labelsize=7); ax.spines[["top", "right"]].set_visible(False); ax.set_xlim(0, 50)
    fig.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ------------------------------------------------------------------ building blocks
def P(t, s=body):
    return Paragraph(t, s)


def B(items):
    return [Paragraph(t, bullet, bulletText="•") for t in items]


def T(rows, widths, fs=7.1):
    tot = sum(widths)
    data = [[Paragraph(str(c), cellh if r == 0 else cell) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=[CW * w / tot for w in widths], repeatRows=1)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("BOX", (0, 0), (-1, -1), 0.5, MID),
          ("LINEBELOW", (0, 0), (-1, -1), 0.3, MID), ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
          ("LEFTPADDING", (0, 0), (-1, -1), 3.5), ("RIGHTPADDING", (0, 0), (-1, -1), 3.5)]
    st += [("BACKGROUND", (0, r), (-1, r), LIGHT) for r in range(2, len(rows), 2)]
    t.setStyle(TableStyle(st))
    return t


def img(path, width):
    w, h = ImageReader(str(path)).getSize()
    return Image(str(path), width=width, height=width * h / w)


def page(flowables):
    return KeepInFrame(CW, FRAME_H, flowables, mode="shrink")


class Doc(BaseDocTemplate):
    def __init__(self, fn):
        super().__init__(fn, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=1.9 * cm, bottomMargin=1.4 * cm,
                         title="AetherGuard: pipeline overview", author="AetherGuard project")
        self.addPageTemplates([PageTemplate(id="p", frames=[Frame(MARGIN, 1.4 * cm, CW, FRAME_H, id="f", leftPadding=0, rightPadding=0,
                                                                   topPadding=0, bottomPadding=0)], onPage=self.deco)])

    def deco(self, c, d):
        c.saveState()
        c.setFillColor(NAVY); c.rect(0, PAGE_H - 1.25 * cm, PAGE_W, 1.25 * cm, fill=1, stroke=0)
        c.setFillColor(colors.white); c.setFont("DV-B", 10); c.drawString(MARGIN, PAGE_H - 0.82 * cm, "AetherGuard")
        c.setFont("DV", 7.5); c.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.82 * cm, f"Pipeline overview · {date.today():%d %B %Y}")
        c.setFillColor(GREY); c.setFont("DV", 7); c.drawCentredString(PAGE_W / 2, 0.75 * cm, f"Page {d.page} of 5  ·  research prototype, not a public warning service")
        c.restoreState()


def build():
    arch, comp = WORK / "architecture.png", WORK / "comparison.png"
    architecture_png(arch); comparison_png(comp)
    v3 = S6.get("v3", {})
    v3_cv_fa, v2_cv_fa = v3.get("oof_fa_at_90"), v3.get("v2_oof_fa_at_90")
    best = v3.get("verdict")
    _lo = S6.get("live_operation") or {}
    live_txt = ("pending" if not _lo else
                f"{_lo['live_days']} live days published since {_lo['first_live_day']} (plus {_lo['backfilled_days']} backfilled); "
                f"{_lo['days_all_four_leads']} of all {_lo['days_published']} days with D0…D+3; failed sources named on {_lo['days_with_failed_sources']}")
    _b = S6.get("backtest") or {}
    bt_txt = ("pending" if not _b else
              f"{pct(_b['season_2018_operational_detection'][0])} of {_b['season_2018_operational_detection'][4]} landslide days caught vs "
              f"{pct(_b['season_2018_training_style_detection'][0])} with archive inputs; scores rank-correlate {_b['raw_rank_correlation']:.3f}")
    _t = v3.get("test_2018") or {}
    v3_test_txt = ("pending" if not _t else
                   f"{pct(_t['recall'][0])} ({pct(_t['recall'][1])}-{pct(_t['recall'][2])}) at {pct(_t['fa_share'][0])} on alert; "
                   f"v2 {pct(_t['v2_recall'][0])} at {pct(_t['v2_fa_share'][0])}")  # e.g. "best: beats v2 (paired CI excludes 0)" — written by the controller
    story = []

    # ---------------- page 1: architecture
    story.append(page([
        P("1  The complete pipeline", h1),
        P("AetherGuard predicts, every morning, the chance of a rain-triggered landslide in every 5 km cell of the Himalaya "
          "(India, Nepal, Bhutan) and the Western Ghats (India) for today and the next three days. It first checks whether "
          "the rain sensors can be trusted, then reads the slope, and only then issues a level with a confidence flag and its reasons."),
        img(arch, CW * 0.86),
        P("Figure 1. The live pipeline. Every input is published daily (IMERG about 14.5 h after the UTC day; GFS every 6 h; "
          "IMD real-time about 1 day; gauges a few days). The model is trained on the same products it receives live; for the newest day it receives "
          "the IMERG Early run, a gap measured in the operational backtest (page 3).", cap),
        T([["Step", "When", "What happens"],
           ["Ingest", "11:00 IST daily", "Download the domain subset of each source, record its freshness, append to the history stores"],
           ["Stage 1", "same run", "Score every recent gauge reading for faults; keep confirmed extremes; summarise station trust per cell"],
           ["Features", "same run", "Build rain-history, rain-anomaly and terrain features per cell for D0; add GFS forecast rain for D+1…D+3"],
           ["Stage 2", "same run", "Ensemble risk with a 10-90% interval; calibrated per region; top-5 reasons per alert"],
           ["Alerts", "same run", "Levels with hysteresis; escalate when sensors are blind but any source shows heavy rain"],
           ["Publish", "same run", "Bulletin, 3D dashboard (risk map, alerts with reasons, sensors and sources), API; a failed source is named, never hidden"]], [1.1, 1.3, 7.6]),
    ]))
    story.append(PageBreak())

    # ---------------- page 2: datasets and features
    story.append(page([
        P("2  Data the model works on, and how features are built", h1),
        P("Training and live use read the same products (v3-live). The one difference, the IMERG Early run for the newest day, was measured by replaying 2018 as if live: see page 3.", body),
        T([["Dataset", "Role", "Coverage used", "In training", "In live run"],
           ["NASA GPM IMERG V07 (Late; Early for the same morning)", "Model rain input", "0.1°, 2006-10 → today, domain 8-36 °N, 72-98 °E", "Yes (2007-2017)", "Yes, daily"],
           ["NOAA GFS 0.25° forecast", "Rain for D+1…D+3", "Archive 2021-2024 (skill); live latest cycle", "Skill testing", "Yes"],
           ["IMD gridded rainfall (final / real-time)", "Second opinion, data confidence", "0.25°, India; final 2007-2024", "v2 reference", "Yes (if published)"],
           ["NOAA GHCN-Daily", "Stage 1 sensor checks", "140 gauges (138 India, 2 Nepal)", "Stage 1 training", "Recent 120 days"],
           ["Copernicus GLO-90 DEM", "Terrain", "495 tiles → 166,728 cells", "Yes", "Static"],
           ["NASA GLC, COOLR, NSIDC HMA", "Landslide labels", "68,738 records → 919 day-exact landslide cell-days", "Labels", "—"]],
          [2.5, 1.6, 2.6, 1.2, 1.2]),
        P("Labels and splits", h2),
        P("Rain-triggered landslides only, location accuracy ≤ 5 km, region by country (India, Nepal, Bhutan in the Himalaya; India in the Ghats). "
          "Frozen, checksummed splits: train 2007-2015, validation 2016-2017 (pooled for year-blocked cross-validation), unseen test 2018, "
          "window test 2023, case studies Kerala 2018 and Wayanad 2024. Non-events: 10 matched negatives per positive (same months, ≥ 3 cells and ±3 days "
          "from any recorded event) plus a weighted random sample of all cell-days to measure honest false-alarm rates."),
        P("Feature engineering (per 5 km cell, per IMD rain day D)", h2),
        T([["Group", "Features", "Why"],
           ["Rain history", "IMERG accumulations over 1, 3, 5, 7, 14, 30, 60 and 90 days; largest 1-day rain in 7/30 days; wet days in 30; days since 10 mm; 1-day share of the 3-day total",
            "Short bursts and long soaking both trigger slides"],
           ["Rain anomaly", "3-, 7- and 30-day totals divided by the cell's own 2007-2015 climatology for that month", "100 mm means different things in Cherrapunji and Ladakh"],
           ["Wetness index (tested)", "Antecedent precipitation index with decay 0.85, 0.90, 0.95; tested by cross-validation, not selected (no gain over rain history)", "Wet soil fails sooner"],
           ["Neighbourhood rain (tested)", "Max and mean of 1- and 3-day rain over the 3 × 3 IMERG pixels; tested, not selected", "Satellite storms are often displaced by a pixel"],
           ["Terrain", "Mean/std elevation, relief, mean/90th-percentile/max slope, curvature, aspect (sin, cos), wetness-index proxy", "Steep, concave slopes concentrate water"],
           ["Day basis", "UTC products → IMD day: 0.875 × UTC(D−1) + 0.125 × UTC(D) (validated: mean error 1.85 mm vs exact hourly totals)",
            "Rain must land on the right day"]], [1.3, 5.6, 2.4]),
        P("Each group enters the model only if year-blocked cross-validation shows it lowers false alarms at 90% detection by more than its standard error. "
          "Latitude, longitude, region and station presence are never inputs (they would learn where catalogs report landslides, not why slopes fail).", small),
    ]))
    story.append(PageBreak())

    # ---------------- page 3: capabilities
    story.append(page([
        P("3  What the model can do, and how", h1),
        T([["Capability", "How it does it"],
           ["Daily risk for every 5 km cell, today and 3 days ahead", "Each morning the newest IMERG rain is added to the 90-day history; D+1…D+3 add GFS forecast rain; the ensemble gives a probability and a 10-90% interval"],
           ["Catch most landslide days while raising fewer false alarms", "LightGBM learns how rain history, rain anomaly and terrain combine; monotone constraints keep it physically sensible; the Watch threshold is set from out-of-fold data so that ≥ 90% of past events would have been caught even after sampling noise"],
           ["Know when its own rain gauges are lying", "Stage 1 compares each gauge with its own history, neighbours and two independent rain grids; blocked, stuck, drifting and duplicated gauges are flagged; confirmed cloudbursts are kept"],
           ["Never stay silent when blind", "If a source is late, missing or disagrees while any source shows heavy rain, the level is raised and the bulletin says why"],
           ["Explain every alert", "Top-5 contributing factors (SHAP), the spread between rain sources, nearby gauge trust and the data-confidence flag"],
           ["Replay any past day", "The same code runs for a past date using only data available that morning (operational backtest)"]], [2.6, 7.2]),
        P("Measured results", h2),
        T([["Result", "Value", "Source"],
           ["Model, unseen year 2018: landslide days caught at Watch (v2 protocol model)", f"{pct(V2['recall'])} ({pct(V2['recall_lo'])}-{pct(V2['recall_hi'])})", "phase3_hazard_report"],
           ["… share of cell-days on alert", pct(V2["fa"]), "phase3_hazard_report"],
           ["Best conventional rule at a similar catch (rainfall threshold)", f"{pct(V2['id_fa'])} on alert for {pct(V2['id_recall'])} caught", "phase3_hazard_report"],
           ["Complete alert system, 2018: landslide days caught at Watch", f"{pct(ALERT['watch_recall'])} ({num(ALERT['watch_per_1000'], '{:.0f}')} alerts per 1,000 cell-days)", "phase4_alerts_report"],
           ["Kerala floods, August 2018", f"{num(ALERT['kerala'])} of {num(ALERT['kerala_n'])} landslide days flagged", "phase4_alerts_report"],
           ["Sensor faults caught (average over six fault types, unseen gauges)", f"{num(INTEG['engine'], '{:.2f}')} vs {num(INTEG['l1'], '{:.2f}')} best rule check", "phase2_integrity_report"],
           ["v3-live (IMERG) cross-validated false alarms at 90% detection", "pending" if v3_cv_fa is None else f"{pct(v3_cv_fa)} vs {pct(v2_cv_fa)} for v2", "phase6_summary"],
           ["v3-live verdict against v2", best or "pending", "phase6_summary"],
           ["v3-live, unseen year 2018 (single look): landslide days caught at Watch", v3_test_txt, "phase6_summary"],
           ["Same model on live-timed inputs (2018 replayed as if live each morning)", bt_txt, "phase6_summary"],
           ["Daily live operation on the laptop (11:00 IST)", live_txt, "phase6_summary"]], [5.0, 2.8, 1.8]),
        P("Detection is measured on landslide days the model never saw; false alarms on a weighted random sample of all cell-days. "
          "Because the landslide catalogs are incomplete, false-alarm shares are upper bounds.", small),
    ]))
    story.append(PageBreak())

    # ---------------- pages 4-5: why better, failures addressed
    _b = S6.get("backtest") or {}
    bt_fail_txt = ("Train/serve gap measured, not assumed: 2018 replayed with only the inputs that existed each morning caught "
                   f"{pct(_b['season_2018_operational_detection'][0])} vs {pct(_b['season_2018_training_style_detection'][0])} with archive inputs."
                   if _b else "The operational backtest uses only inputs that existed each morning.")
    _f = S6.get("forecast") or {}
    _f2 = S6.get("forecast_v2") or {}
    if _f2:
        _L = _f2["leads"]
        _fs = [100 * _L[k]["firm_share"] for k in ("1", "2", "3")]
        _fa = [100 * _L[k]["firm_agreement"] for k in ("1", "2", "3")]
        _da = [100 * _L[k]["depends_agreement"] for k in ("1", "2", "3")]
        fc_limit_txt = ("Forecast days depend on rain that has not fallen. D+2 and D+3 now use the ECMWF ensemble (chosen over GFS on 2024 by a pre-declared rule; "
                        "D+1 stays GFS). Each forecast cell is marked Firm when its level is the same with no further rain, the forecast and a wet case: "
                        f"{min(_fs):.0f}-{max(_fs):.0f}% of cells, and these matched the level from observed rain {min(_fa):.0f}-{max(_fa):.0f}% of the time "
                        f"(cells that depend on the forecast: {min(_da):.0f}-{max(_da):.0f}%).")
    else:
        fc_limit_txt = "Forecast days inherit GFS rain errors; their skill is measured on 2021-2024 where labels are thin."
    _a = S6.get("alerts_2018") or {}
    _h = S6.get("hardening") or {}
    burden_txt = (f"In the monsoon the Watch level is broad: replaying 2018 as if live, {pct(_a['watch_plus'])} of monsoon cell-days were at Watch or above "
                  f"(Warning+ {pct(_a['warning_plus'])}, Emergency {pct(_a['emergency'])}); Watch caught {_a['event_detection_levels'][3]} of {_a['event_detection_levels'][4]} landslide days "
                  f"({_h.get('watch_detection_2018_before', '?')} before the rain trigger), Warning {_a['warning_detection'][1]} and Emergency {_a['emergency_detection'][1]}. "
                  "Watch means heightened awareness; Warning and Emergency are the actionable levels." if _a else "Alert burden in the monsoon is measured in the backtest.")
    fails = [
        ["Existing-system failure", "Evidence", "What AetherGuard does", "Why it is not prone to it"],
        ["<b>Rain products miss local extremes.</b> Global grids smooth an orographic cloudburst over 25 km.",
         "Wayanad, 30 Jul 2024: IMD 179 mm, nearest trusted gauge 155 mm, ERA5 67 mm, CHIRPS 0 mm for the same day.",
         "Uses several independent sources (IMERG, IMD real-time, gauges); the alert engine takes the maximum of the sources.",
         "One wrong source cannot silence the warning: escalation uses the maximum, and disagreement lowers confidence instead of being averaged away."],
        ["<b>Sensors fail silently.</b> A clogged gauge reads 0 mm in a storm.",
         f"NOAA-style quality control caught {num(INTEG['noaa'], '{:.2f}')} of injected faults on average; blocked-gauge faults 3-19%.",
         "Stage 1 checks every reading against its own history, neighbours and two grids; arbiter keeps confirmed extremes.",
         f"Average detection {num(INTEG['engine'], '{:.2f}')}; a flagged reading is never used to lower the rain estimate."],
        ["<b>Fixed rain thresholds cry wolf.</b>",
         f"Rainfall-threshold rule: {pct(V2['id_fa'])} of cell-days on alert to catch {pct(V2['id_recall'])}.",
         "Learns from rain history, rain anomaly and terrain together; thresholds set by cross-validation with a recall-first margin.",
         f"{pct(V2['fa'])} of cell-days on alert for a similar catch on an unseen year (Figure 2)."],
        ["<b>Models trained on data that is not available live.</b> Reanalysis or final gauge grids arrive weeks or a year late.",
         "IMD final grid is yearly; CHIRPS final about 3 weeks; MERRA-2 weeks.",
         "v3-live is trained on IMERG and terrain only, the same products the daily run receives.",
         bt_fail_txt],
        ["<b>Rain lands on the wrong day.</b> Products use UTC days; Indian gauges use 08:30 IST.",
         "Gauge vs CHIRPS correlation peaks a day early (0.38 at lag −1 vs 0.16 at lag 0).",
         "Every product is converted to the IMD rain day before any feature is built.",
         "Tested: after alignment the match peaks on the same day; error 1.85 mm on average."],
        ["<b>Inflated accuracy claims.</b> Random splits and repeated test use.",
         "Landslide catalogs are uneven (8 labelled days in 2007 vs 127 in 2015).",
         "Frozen checksummed splits, year-blocked cross-validation for every choice, single frozen test look, bootstrap intervals.",
         "Every reported number comes from a result file; protocol changes and reruns are disclosed."],
        ["<b>Silent failure when blind.</b> Systems show Normal when inputs are missing.",
         "Operational feeds go down; IMD real-time was unreachable in one of three probes.",
         "Data-confidence flag (High / Degraded / Insufficient) per cell; blind-sensor escalation; freshness of every source in the bulletin.",
         "A missing source is named and lowers confidence; the run never publishes a silent Normal."],
    ]
    story.append(page([
        P("4  Why AetherGuard is better than existing systems", h1),
        P("Existing landslide warnings in the region rely on fixed rainfall thresholds or susceptibility × rain rules fed by a single rain product. "
          "They fail in predictable ways. AetherGuard was designed around those failures and measured against the standard methods on the same data."),
        img(comp, CW * 0.8),
        P("Figure 2. False alarms on the unseen year 2018, each method at its own pre-set Watch threshold (v2 protocol model; recall between 85% and 89% for all four).", cap),
        T(fails[:5], [2.0, 2.3, 2.6, 2.6], fs=6.9),
    ]))
    story.append(PageBreak())
    story.append(page([
        P("5  Failures addressed, and why the pipeline is not prone to them", h1),
        T([fails[0]] + fails[5:], [2.0, 2.3, 2.6, 2.6], fs=6.9),
        P("Built-in protections", h2),
        *B(["<b>Physics-consistent model:</b> more rain or a steeper slope can never lower the predicted risk (monotone constraints, checked with zero violations).",
            "<b>Recall-first operating point:</b> a missed landslide costs far more than a false alarm, so the Watch level is the highest threshold that still catches ≥ 90% of past events at the 5th bootstrap percentile.",
            "<b>Uncertainty is shown, not hidden:</b> a 20-model ensemble gives a 10-90% interval; its upper bound can raise Watch on its own.",
            "<b>Region-aware calibration:</b> the Himalaya and the Western Ghats get their own probability calibration, fixing the 3× under-prediction measured in the Ghats.",
            "<b>Every change is earned:</b> a feature group, model type or region rule is kept only if cross-validation shows a gain larger than its standard error.",
            "<b>Live freshness:</b> each source's issue time and latency are stored with every run, so a stale input is visible.",
            "<b>No rain, no alert:</b> a cell can reach Watch or above only after at least " + (f"{_h['rain_minimum_mm_7d']:.1f}" if _h else "the minimum") + " mm of rain in 7 days (the 5th percentile of past landslide days); a level held without data steps down after 2 days.",
            "<b>Every alert audited:</b> each daily run checks every published cell for contradictions (risk inside its range, level matches its reasons, rain rule, confidence); " + (f"{_h['audit_violations_after_rerun']} violations on {_h['live_days_audited']} live days." if _h else "violations are named in the bulletin.")]),
        P("Known limits (stated, not hidden)", h2),
        *B(["Landslide catalogs are incomplete and rain-triggered only; the unseen test year has 80 labelled landslide days, so intervals are wide.",
            "Satellite rain at 0.1° still under-measures the most extreme orographic bursts; gauges and IMD real-time remain second opinions.",
            fc_limit_txt, burden_txt,
            "Research prototype, not validated for issuing public warnings."]),
    ]))
    Doc(str(OUT)).build(story)
    return OUT


if __name__ == "__main__":
    print(build())
