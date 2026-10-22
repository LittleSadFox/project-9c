# Design guidelines

This file records the Liquid Glass theme for Climbing Coach.
Write visual changes only in `tokens.css` and `glass.css`.
`app.css` holds layout only.
`app.css` must use `--lg-*` tokens for colour, radius, and easing.

Write in ASD-STE100 Simplified Technical English.
Use short sentences.
Use active voice.
Give one instruction per sentence.

Sources: Apple Human Interface Guidelines and Apple Liquid Glass.

## 1. Two layers

Use glass only on controls that float above content.

Glass surfaces:

- Top bar
- Transport capsule
- Segmented controls
- Buttons
- Menus
- Sheets
- Tooltips

Use a calm, nearly opaque content layer for:

- Video
- Timeline
- Tables
- Cards
- Charts

Do not put glass on content.
Do not put glass on glass.
Keep sticky table cells opaque.

## 2. Glass recipe

Dark starting values live in `tokens.css`.

- Bar fill: `rgba(38, 42, 52, 0.52)`
- Sheet and menu fill: `rgba(30, 34, 43, 0.74)`
- Blur: `blur(22px) saturate(180%)` plus the `-webkit-` prefix
- Rim: `inset 0 1px 0 rgba(255, 255, 255, 0.16)`
- Edge: `1px solid rgba(255, 255, 255, 0.13)`
- Lift: `0 10px 30px rgba(0, 0, 0, 0.34)`

The light set uses white-tinted glass with dark labels.
Tune both sets on the Mac.

Glass needs something to refract.
Put a soft, low-contrast ambient gradient behind the app.
Do not put a busy wallpaper behind data.

## 3. Shape

Use capsules for anything the user presses or toggles.
Use circles for icon-only buttons.
Use concentric radii:

- Sheet: 28 px (`--lg-radius-sheet`)
- Card: 20 px (`--lg-radius-card`)
- Menu: 16 px (`--lg-radius-menu`)
- Control: 12 px (`--lg-radius-control`)
- Row: 8 px (`--lg-radius-row`)

## 4. Colour

Use Apple system colours.
Follow dark and light appearance through `prefers-color-scheme`.

- Blue `#0a84ff` / `#007aff` is only for the one primary action and the current selection.
- Green `#30d158` / `#34c759` means send or ok.
- Orange `#ff9f0a` / `#ff9500` means warning.
- Red `#ff453a` / `#ff3b30` means fall or error.
- Grey `#8e8e93` is the system grey.

Labels use full, 68 %, and 42 % opacity.
Do not use grey hex values for labels.

Each view has one blue primary action.

- Review: "Accept attempt", then "Finish review"
- Compare: "Export video"
- Models: "Train"

Put destructive confirmations in a `Sheet`.

## 5. Type

Font stack: `-apple-system, "SF Pro Text", system-ui, sans-serif`.
Headings use weight 600.
Use `font-variant-numeric: tabular-nums` for times, frame numbers, and scores.
Keep visible text short.
Put explanations in a `Hint`.
A `Hint` is a "?" button.
Keep a space between the page copy and the hint button.
The hint text shows on hover and on keyboard focus.

## 6. Motion

Use one spring curve: `cubic-bezier(0.34, 1.36, 0.64, 1)`.
Press feedback scales to 0.97.
Animate only `transform` and `opacity`.

## 7. Accessibility

Honour these media queries:

- `prefers-reduced-transparency: reduce` — solid fills and no blur
- `prefers-contrast: more` — stronger edges and labels
- `prefers-reduced-motion: reduce` — no transitions

Never remove the 3–4 px blue focus ring.

A modal dimmer must not use `backdrop-filter`.
The sheet inside would look flat.

A frosted element is the containing block of its fixed children.
Render menus in a portal at the app root.

Skeleton colours: left blue, right orange, centre grey.
Draw low confidence as a dashed line.
Difference heat uses colour and line width.
Colour is never the only signal.

## 8. Components

`glass.jsx` exports:

- `TopBar`
- `SegmentedNav`
- `Tabs`
- `IconButton`
- `Button` (primary, glass, danger)
- `Switch`
- `Slider`
- `Panel`
- `Sheet`
- `Menu`
- `Tooltip`

## 9. Mac visual checklist

Do this on a Mac after `git pull`.
Open the shell in Safari.
Check dark mode and light mode.

- [ ] The top bar looks like glass over the ambient gradient.
- [ ] Content panes look solid and calm.
- [ ] Video, tables, and charts have no glass.
- [ ] The current nav item uses the blue selection colour.
- [ ] One primary blue action is visible on each view that has an action.
- [ ] Headings use weight 600.
- [ ] Times and frame numbers use tabular numbers.
- [ ] Reduced transparency removes blur and uses solid fills.
- [ ] Increased contrast strengthens edges and labels.
- [ ] Reduced motion turns transitions off.
- [ ] The focus ring stays visible on keyboard move.
- [ ] A long table can scroll under the top bar without sticky glass cells.
- [ ] VoiceOver reads the brand, the nav items, the job tray, and the settings button.
