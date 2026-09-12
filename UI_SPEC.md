# Raphe Board Flasher — UI Specification

Mockup-ready spec. Every number here is a real pixel value at 100% scale, so a mockup built
to these numbers can be implemented 1:1.

---

## 1. Design tokens

### Colours — taken from raphe.com

Pulled from the live stylesheet at `raphe.com`. **Bold rows are the company's exact published
values**; the rest are derived from them to fill out a desktop UI (a website only needs two
surface levels, an app needs four).

| Token | Hex | Source | Use |
|---|---|---|---|
| **`bg`** | **`#0A131A`** | `--brand-background` | window background |
| `surface` | `#101C25` | derived +1 step | header, status bar, cards |
| `surface-raised` | `#16242F` | derived +2 steps | inputs, dropdowns, pills |
| `border` | `#22323F` | derived +3 steps | 1px borders and dividers |
| **`text`** | **`#FCFCFC`** | `--white` | primary text |
| **`text-dim`** | **`#848484`** | brand grey | labels, secondary text |
| **`text-faint`** | **`#505050`** | brand grey | footer credit, disabled text |
| **`accent`** | **`#01B4EA`** | `--gradient-blue-white` | primary button, links, progress fill |
| `accent-hi` | `#3DCBF5` | derived | hover |
| **`success`** | **`#00FFB2`** | brand gradient mint | verified, done |
| `warning` | `#F59E0B` | *not in brand set* | ISP bootloader warning |
| **`danger`** | **`#EA384C`** | brand stylesheet | errors, cancel |
| `log-bg` | `#060D12` | derived −1 step | log panel background |

**Three signature moves to carry over from the site:**

1. **0.5px cyan hairlines.** raphe.com uses `border: .5px solid #01b4ea` — much finer than a
   normal UI border. Use it on focus rings, the active segmented-control segment, and the
   drop zone on drag-over. It is the single most recognisable detail of their visual language.
2. **White → cyan gradients**, e.g. `linear-gradient(97deg, #FFFFFF 0%, #01B4EA 131%)`.
   Use on the header wordmark (as a text gradient) and the progress-bar fill.
   For the primary button, darken it to `linear-gradient(135deg, #01B4EA, #0193C4)` so white
   label text stays legible.
3. **Mint `#00FFB2` as the second accent**, from their hero gradient. This is why success is
   mint rather than a generic green — it keeps the palette to two hues.

Light theme swaps `bg`→`#F7F9FA`, `surface`→`#FFFFFF`, `surface-raised`→`#EDF1F4`,
`border`→`#D6DEE4`, `text`→`#0A131A`, `text-dim`→`#5A6773`. Accent and status colours are
unchanged. Mint `#00FFB2` fails contrast on white, so light theme uses `#00A874` for success.

### Type — matching raphe.com

The site loads **Poppins** and **Inter**, with **Bebas Neue** for display.

| Role | Font | Size / weight | Notes |
|---|---|---|---|
| App wordmark | Bebas Neue | 20 Regular | uppercase, letter-spacing 2px, white→cyan text gradient |
| Card / step label | Poppins | 11 SemiBold | uppercase, letter-spacing 1.2px, `text-dim` |
| Field label | Inter | 11 Medium | `text-dim` |
| Body / control | Inter | 13 Regular | |
| Button | Poppins | 14 SemiBold | primary 15 |
| Meta / helper | Inter | 11 Regular | `text-dim` |
| Log | Cascadia Mono / Consolas | 12 Regular | line-height 18 |

Bundle Bebas Neue and Poppins with the app (Qt loads them via `QFontDatabase`) so it renders
identically on a PC that has neither installed. Inter falls back to Segoe UI Variable.

### Geometry

- 8px base grid. Window padding **24**, card padding **20**, gap between cards **16**.
- Radius: cards **12**, inputs/buttons **8**, pills **10**, progress track **4**.
- Control height **38** (inputs, dropdowns, secondary buttons). Primary button **52**.

---

## 2. Window

**980 × 720** default, min **900 × 660**, resizable, not maximised on launch.
Vertical stack, no scrolling at default size.

```
┌──────────────────────────────────────────────────────────────────────┐
│  HEADER                                                        64px  │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌── CARD 1 · FIRMWARE ──────────────────────────────────┐   168px   │
│  └───────────────────────────────────────────────────────┘           │
│                                                     16px gap         │
│  ┌── CARD 2 · TARGET ────────────────────────────────────┐   200px   │
│  └───────────────────────────────────────────────────────┘           │
│                                                     16px gap         │
│  ┌── CARD 3 · FLASH ─────────────────────────────────────┐   180px   │
│  └───────────────────────────────────────────────────────┘           │
│                                                                      │
│  ▸ Show details                                  [ Save log ]  40px  │
├──────────────────────────────────────────────────────────────────────┤
│  STATUS BAR                                                    32px  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Header — 64px, `surface`, 1px bottom `border`

**Left** (24px from edge): logo mark **32×32** → 12px gap → wordmark
`RAPHE BOARD FLASHER` (16 SemiBold, uppercase, `text`) → 10px gap → version pill
`v1.0.0` (11 Regular, `text-dim`, bg `surface-raised`, radius 10, padding 3×9).

**Right** (24px from edge): two **32×32** ghost icon buttons, 8px apart — gear (Settings),
question mark (Help). Icon 18px, `text-dim`; on hover bg `surface-raised`, icon `text`.

---

## 4. Card 1 — FIRMWARE

Card: `surface`, radius 12, 1px `border`, padding 20.

**Header row:** step badge **24×24** circle, bg `accent`, white `1` (12 Bold) → 10px gap →
`FIRMWARE` step label.

**Source toggle** (16px below): segmented control, **260 × 32**, radius 8, bg
`surface-raised`, 3px inner padding. Two equal segments: `From library` · `From file`.
Active segment: bg `accent`, text white, radius 6. Inactive: `text-dim`.

**Then, depending on mode:**

**File mode, nothing chosen** — drop zone, full width × **88**, radius 10, **1.5px dashed**
`border`, bg transparent. Centred column: 24px chip-with-arrow icon (`text-dim`) → 6px →
`Drag a .hex or .bin file here` (13, `text`) → 4px → `or` (11, `text-faint`) → 8px →
`Browse…` secondary button (110 × 32). On drag-over: border becomes solid `accent`,
bg `rgba(27,168,240,0.06)`.

**File mode, file chosen** — file chip, full width × **56**, radius 10, bg `surface-raised`,
padding 12. Left: 20px document icon in `accent`. Middle, two lines:
- `firmware.hex` — 13 Medium, `text`
- `248 KB · CRC32 9A3F21E8 · Intel HEX · 94% of 256 KB flash` — 11, `text-dim`

Right: **24×24** ghost ✕ to clear.

If the file fails validation the second line turns `danger`, e.g.
`Not a valid Intel HEX file — line 412 has a bad checksum`.

**Library mode** — a single full-width dropdown (**38** tall) listing the `firmware/` folder,
items rendered as `MainBoard v2.3` with `2026-08-14 · 248 KB` right-aligned in `text-dim`.

---

## 5. Card 2 — TARGET

Header row: badge `2` + `TARGET`.

**Row A** — two columns, 16px gap, each 50%:

| Left | Right |
|---|---|
| label `Board` | label `Upload method` |
| dropdown `Arduino Mega 2560` | dropdown `UNO as ISP programmer` |
| | link `ⓘ Show wiring` — 11, `accent`, 6px below |

**Row B** (16px below) — full width, 8px gaps:
`Port` label, then a row of: dropdown (flex, `COM5 — Arduino Uno`) · **38×38** refresh icon
button · `Detect board` secondary button (**130 × 38**).

After a successful detect, an 11px line appears 6px under the port row:
`✔ Detected ATmega2560 — matches selected board` in `success`.
On mismatch: `✕ Detected ATmega328P — you selected Arduino Mega 2560` in `danger`.

**Row C — ISP warning strip.** Visible **only** when method is `UNO as ISP programmer`.
Full width × **52**, radius 8, bg `rgba(245,158,11,0.10)`, **3px left border** `warning`,
padding 12×14. 16px ⚠ icon in `warning` → 10px gap → 12px text:
`ISP flashing erases the bootloader. This board won't accept USB uploads until it's re-burned.`
On the right edge, a checkbox + `I understand` (12, `text-dim`).

This card grows to ~200px with the strip, ~136px without it.

---

## 6. Card 3 — FLASH

Header row: badge `3` + `FLASH`.

**Primary button** — centred horizontally, **280 × 52**, radius 10.
Linear gradient `#1BA8F0 → #0E8FD4` (180°), white text, 18px bolt icon + 10px gap +
`FLASH BOARD` (15 SemiBold). Subtle glow: `0 4px 16px rgba(27,168,240,0.30)`.

| State | Appearance |
|---|---|
| Disabled | bg `surface-raised`, text `text-faint`, no glow, plus an 11px `warning` line 8px beneath: `Select a firmware file to continue` |
| Hover | gradient lightens to `accent-hi`, glow grows |
| Running | becomes `Cancel` — transparent bg, 1.5px `danger` border, `danger` text |

**Progress area** — replaces the empty space beneath the button while running.
- Track: full width × **8**, radius 4, bg `surface-raised`. Fill: `accent` gradient, animated.
- 8px below, a row: left `Writing 248 KB to flash…` (12, `text`), right `62%` (12 mono, `text-dim`).
- Write maps to 0–80% of the bar, verify to 80–100%, so it reads as one continuous pass.

**Result banner** — replaces the progress area when finished. Full width × **56**, radius 10,
3px left border, padding 14.

- **Success:** bg `rgba(34,197,94,0.10)`, border `success`, 20px ✔ circle. Two lines —
  `Flash complete` (13 SemiBold, `text`) / `248 KB written and verified in 41.2 s` (11, `text-dim`).
- **Failure:** bg `rgba(239,68,68,0.10)`, border `danger`, 20px ✕ circle. Two lines —
  the friendly message (13 SemiBold) / the fix (11, `text-dim`), e.g.
  `No reply from the UNO` / `Check the ArduinoISP sketch is loaded and the 10 µF capacitor is fitted between RESET and GND.`
  Right side: `View log →` link (11, `accent`) which expands the details panel.

---

## 7. Details panel

**Collapsed** — a 40px row, no card: `▸ Show details` (12, `accent`) on the left,
`Save log` ghost button (**100 × 30**) right-aligned, disabled until a run has produced output.

**Expanded** — `▾ Hide details`, and a log panel beneath: full width × **200**, radius 8,
bg `log-bg`, 1px `border`, padding 12, 12px monospace, line-height 18, auto-scrolling,
text-selectable.

Line colouring:

| Line | Colour |
|---|---|
| normal | `text-dim` |
| the command line we invoked (first line, prefixed `$`) | `text-faint` |
| `Writing \| ##… \| 62%` | `accent` |
| `19278 bytes of flash verified` | `success` |
| any `Error:` line | `danger` |

Expanding the panel grows the window content by 208px; the window scrolls rather than resizes.

---

## 8. Status bar — 32px, `surface`, 1px top `border`

Left (24px in): `Raphe mPhibr · Nitish Sharma` — 11, `text-faint`.
Right (24px in): 8px status dot + 11px label.

| State | Dot | Label |
|---|---|---|
| Idle | `text-faint` | `Ready` |
| Running | `accent`, pulsing | `Flashing…` |
| Done | `success` | `Done` |
| Failed | `danger` | `Failed` |

---

## 9. Screens to mock

Mock these five — they cover every visual state:

1. **Idle** — nothing selected, drop zone empty, FLASH disabled with its helper line, status `Ready`.
2. **Ready** — file chip filled, board + port set, ISP warning strip visible and checked, FLASH enabled.
3. **Flashing** — progress bar at 62%, button showing `Cancel`, details panel expanded with live log, status `Flashing…`.
4. **Success** — green result banner, details collapsed, status `Done`.
5. **Error** — red result banner with `View log →`, details expanded showing red `Error:` lines, status `Failed`.

---

## 10. Modals

### Wiring help — 560 × 520

Title `Wiring the UNO as an ISP programmer`. A diagram at the top (two board outlines, six
coloured jumpers), then this table:

| From (UNO) | To (Mega 2560) |
|---|---|
| D10 | RESET |
| D11 (MOSI) | D51 |
| D12 (MISO) | D50 |
| D13 (SCK) | D52 |
| 5V | 5V |
| GND | GND |

Below it, a `warning`-styled note:
`Upload the ArduinoISP sketch to the UNO first, then fit a 10 µF capacitor between the UNO's RESET and GND. Without the capacitor the UNO resets itself and flashing fails.`

For **UNO / Nano targets** the table swaps to D11→D11, D12→D12, D13→D13, D10→RESET. The
dialog reads the pin map from the board's JSON profile, so new boards bring their own.

### Settings — 520 × 420

Rows: avrdude path (read-only, with `Use bundled` / `Browse…`) · firmware library folder ·
default board · default upload method · theme (System / Dark / Light) ·
`Verify after writing` checkbox (on) · `Keep log files` checkbox.
Footer: `Raphe Board Flasher v1.0.0 · avrdude 8.0-arduino.1`.
