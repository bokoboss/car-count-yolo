# Vehicle Counter UI Guide

## 1. Product UX Goals
- Design for desktop-first use with mouse-driven setup and quick scan reading from medium-to-large windows.
- Support a traffic-monitoring workflow: load source, confirm preview, place or adjust lines, start counting, review results, export.
- Keep the interface compact and low-clutter so operators can read status and counts quickly while the preview stays dominant.
- Favor explicit user control over hidden automation. Recommendations are helpful; silent state changes are not.

## 2. Visual Hierarchy
- Most prominent: live preview, total count, run status, active line focus, start/stop actions.
- Secondary: all-lines overview, selected-line direction details, overall by-class counts, active run settings.
- Diagnostic only: event log, low-level hints, verbose status text, debug overlays such as dense track labels.

## 3. Layout Rules
- The preview must remain the dominant visual element and should take most horizontal space by default.
- The right panel should be dense but readable. Keep it as a vertical scan from setup to live dashboard to diagnostics.
- Right panel order:
  1. Run setup
  2. Dashboard summary
  3. All-lines overview
  4. Active-line details
  5. Overall by class
  6. Run snapshot
  7. Event log
- Scrollable content belongs only in the right panel. The preview area should not scroll.
- Use splitter defaults that preserve a large preview at first launch. Keep the preview side visibly larger.
- Minimum sizes should prevent line-edit controls or dashboard tables from collapsing into unreadable states.

## 4. Color Rules
- Use status colors consistently: neutral for waiting, blue for in-progress/setup, green for ready/success, amber/red for warnings or errors.
- Keep line colors consistent across preview and supporting UI. Line 1, Line 2, and Line 3 should not change color meaning between views.
- Color must never be the only meaning carrier. Pair it with labels such as `L1`, `A -> B`, `B -> A`, button text, or status text.
- Keep large surfaces neutral; reserve saturated colors for counts, status emphasis, and line overlays.

## 5. Typography And Spacing Rules
- KPI values should be the strongest text on the dashboard.
- Section titles should be clear and short. Small helper text is allowed only when it removes ambiguity.
- Use compact spacing, but preserve breathing room between sections, KPI blocks, and tables.
- Avoid long paragraphs inside cards. Favor short labels, chips, and concise status text.

## 6. Dashboard Rules
- Summary should answer first: What source is loaded, what is the run state, and how many crossings have been counted?
- All-lines overview should make cross-line comparison fast and keep A/B totals readable at a glance.
- Active-line details should reinforce that A/B is the fixed reference and custom direction names are user-facing labels layered on top.
- Overall by class should stay compact and support quick distribution checks, not compete with the top KPI.
- Event log should be useful for recent actions, warnings, and export outcomes, but it must remain visually secondary.

## 7. Preview Overlay Rules
- Default overlays for normal use: count lines, line labels, selected-line A/B markers, minimal track labels.
- Debug-only overlays: dense track IDs, always-on direction legends for every line, excessive handles or markers on inactive lines.
- Track label modes should default to the least cluttered useful mode; richer labels are opt-in.
- The active line should be visually emphasized with stronger weight and clearer A/B guidance.
- Anti-clutter rule: inactive lines should stay readable without showing every possible marker.

## 8. Direction UX Rules
- `A -> B` and `B -> A` are the primary semantic references.
- Custom direction names are secondary labels for operators and reports.
- Always show A/B orientation alongside custom names in detail panels or legends when needed.
- Never rely on line color alone to communicate direction.

## 9. Interaction Rules
- Line placement and editing must stay direct: click to place, drag to adjust, clear language for the current action.
- Line selection should update both preview emphasis and detail panels immediately.
- During counting, editing controls may be disabled, but focus changes for review can remain available if they do not alter results.
- Avoid over-automation such as auto-advancing focus, auto-renaming directions, or silently changing user selections.
- Action names should be plain and short: `Load Preview`, `Place Line`, `Adjust Line`, `Clear Selected Line`, `Start Counting`.

## 10. Preset And Settings Rules
- The default preset should be the safest general starting point for normal counting, not the most aggressive or technical one.
- Source-aware low-latency behavior should recommend itself for live-like sources but remain visible and user-controllable.
- Model names should be user-friendly and include speed/accuracy tradeoffs in plain language.

## 11. Anti-Patterns To Avoid
- Cluttered overlays that make the road scene harder to read than the counts.
- Overlong right-side panels with no clear scan order.
- Excessive auto-advance behavior after loading, placing, or editing lines.
- Technical wording that normal operators do not understand immediately.
- Hidden state changes, especially around presets, low-latency mode, and active-line focus.

## 12. Ready-To-Ship UX Checklist
- Is the preview still the dominant visual element?
- Are total count and run status the first metrics the eye lands on?
- Can a user understand active line, A/B meaning, and direction names without guessing?
- Are inactive overlays quieter than the selected-line overlay?
- Does the right panel read cleanly from setup to summary to details to diagnostics?
- Are labels and buttons plain-language and consistent?
- Does color support meaning instead of carrying meaning by itself?
- Are event logs useful without dominating the dashboard?
