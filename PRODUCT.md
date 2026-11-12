# Product

AetherGuard is a sensor-integrity and landslide / extreme-weather early-warning prototype for the Himalaya and the
Western Ghats. It is a research prototype and is not validated for issuing real public warnings; every surface says so.

## Platform

web

## Stack

React 19, TypeScript, Vite, react-three-fiber and drei over three.js, framer-motion, zustand, react-router, CSS
modules with tokens in `dashboard/src/styles/tokens.css`. Served locally by the Python API (`aetherguard.serve.api`).

## Users

The person who built it and the people they show it to: reviewers, teachers and peers who need to understand in a few
minutes what the system watches, how a warning is made, and what today's run says. They sit at a laptop, usually in a
lit room, often with the builder talking beside them.

## Product Purpose

Show where rain is likely to bring slopes down in the next days, on a 0.05-degree grid, and show honestly how much the
inputs can be trusted. A visitor should leave able to read an alert: what Watch, Warning and Emergency mean, what
drives them, and how fresh the data is.

## Positioning

An honest research instrument. It shows its measured skill and its gaps instead of claiming accuracy.

## Operating Context

One daily run publishes alert levels for today and the next days. The dashboard has three working views: Live map
(3D terrain with alert levels and rain), Alerts (the list and the reasons behind each alert), Sensors and sources
(station trust and source health). Data can be live or a replay set; the interface always says which.

## Capabilities and Constraints

- Real data only: terrain, rain fields, alert levels and counts come from the API. No invented numbers or claims.
- The 3D terrain scene, rain particles, alert columns and camera moves already exist and must keep working.
- WebGL may be unavailable; everything must degrade to a readable page. Reduced-motion preferences are honoured.
- Runs on a mid-range laptop GPU; the scene has quality steps (`scene/perf.ts`).
- No personal data anywhere in the repository; it is public.

## Brand Commitments

- The research-prototype disclaimer stays visible.
- Measurements read as measurements: numbers in a tabular face, units present, dates explicit.
- User decision 2026-11-12: the experience is a scroll-driven 3D story that is the spine of the product; Live map,
  Alerts and Sensors stay full working views entered from the story. A new look replaces the earlier pinned palette
  and typefaces.

## Evidence on Hand

Live alert counts, per-cell reasons, rain fields, station trust scores, source health, the held-out skill reports in
`reports/`. Generated media (Higgsfield) may be added for chapter backdrops once the account has credits.

## Product Principles

1. The terrain is the protagonist; interface chrome steps back.
2. Never make the prototype look more certain than it is.
3. A story chapter must teach how to read the instrument, not decorate it.

## Accessibility & Inclusion

WCAG 2.2 AA contrast, full keyboard reach, visible focus, reduced-motion support, no information carried by colour
alone (levels have names and positions as well as colours).
