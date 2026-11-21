# Chaos Loss Aversion (CLA)

**Path of Exile 2 | Windows 10/11 (64-bit)**

**Step 1:** Waste Less Chaos Orbs  
**Step 2:** ?  
**Step 3:** Profit

Chaos Loss Aversion (CLA) is a lightweight Windows utility for *Path of Exile 2*. It uses the game's stash search capabilities to provide visual and audio notifications when the item in the **center slot of the Currency Tab** matches your search criteria.

CLA monitors a small calibrated area of your screen. It does **not** perform crafting actions for you.

## Features

- **Visual match detection** based on the active in-game stash search.
- **Guided calibration** for the Currency Tab's center item slot.
- **Stoplight overlay** with adjustable thickness and opacity.
- **Randomized audio notifications** with adjustable volume, when audio clips are included.
- **Rebindable hotkeys** for monitoring, overlay visibility, and calibration capture.
- **Saved calibration and preferences** between sessions.
- **Crafting resource links**, including PoE2DB, Waystone and Tablet regex tools, and Renly's Tools.

## Getting started

1. Download an official Windows release from the [Releases page](https://github.com/tiertwolongs/chaos-loss-aversion/releases), when available.
2. Extract the release package and run the application.
3. Open *Path of Exile 2* and navigate to the Currency Tab.
4. Click **Calibrate** and follow the instructions in the CLA window: hover the slot's upper-left and lower-right corners pressing **F9** each time, confirm the detected slot, then capture a nonmatching and a matching example with **F9**. **Esc** cancels at any step.
5. Enter your desired search in the game's stash search field, then press **F8** to begin monitoring.

Calibration works in **Windowed** and **Borderless Windowed** modes. If you play in Fullscreen, calibrate in Borderless Windowed first. Recalibrate when your resolution, display mode, or monitored slot position changes.

## Controls

| Default key | Action |
| --- | --- |
| **F7** | Show or hide the stoplight overlay |
| **F8** | Start or stop monitoring |
| **F9** | Capture a calibration sample |

All three hotkeys can be rebound.

### Stoplight colors

| Color | Meaning |
| --- | --- |
| **Yellow** | Not monitoring |
| **Green** | No match detected; safe to continue spamming |
| **Red** | Match detected; stop Chaos spamming |

When CLA detects a match, it updates its visual indicator (if visible) and plays a randomly selected audio notification (if available). CLA keeps the red MATCH notification visible until you left-click inside the monitored item slot. This helps prevent the notification from disappearing when another item's tooltip temporarily obscures the monitored slot.

## Limitations

- CLA monitors only the center item slot of the Currency Tab.
- Detection accuracy depends on successful calibration and consistent screen conditions.
- CLA uses visual screen capture; it does not read game memory, modify game files, or communicate with game servers.
- CLA does not click, move items, use currency, or send keyboard inputs to *Path of Exile 2*.
- Notifications cannot guarantee that every overroll will be prevented. All crafting decisions and actions remain yours.

## Documentation

See [`README.txt`](README.txt) for the user-facing guide and the text displayed in CLA's About window.

## About Tier Twolongs

Chaos Loss Aversion is an independent, Kyle-developed utility created for the **Tier Twolongs** *Path of Exile 2* community.

**Website:** https://www.tiertwolongs.com  
**Source:** https://github.com/tiertwolongs/chaos-loss-aversion

CLA is not affiliated with or endorsed by Grinding Gear Games.

**Built by Tier Twolongs for Tier Twolongs.**  
*We put the mid in pyramid.*


## Development (v1.2)

| Path | Purpose |
| --- | --- |
| `main.py` | Entry point |
| `cla/detection.py` | Calibration signature, slot-border detection, per-frame classifier |
| `cla/monitor.py` | dxcam capture thread with click-to-clear match latch |
| `cla/calibration.py` | Non-blocking calibration state machine |
| `cla/capture.py` | One-shot calibration capture (worker thread) |
| `cla/hotkeys.py` | Edge-triggered, modifier-agnostic global hotkeys |
| `cla/winapi.py` | Read-only cursor/button queries. CLA never sends input. |
| `cla/ui/` | Qt window, settings dialog, widgets |
| `tests/` | pytest suite; `test_cla_contains_no_input_injection` guards the no-input promise |

Test locally on Windows:

```powershell
git clone --branch dev/cla-1.2 https://github.com/zavenoa/chaos-loss-aversion "F:\CLA-dev"
Set-Location "F:\CLA-dev"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py
```

Build with `powershell -ExecutionPolicy Bypass -File .\build_windows.ps1`. It produces a portable `--onedir` ZIP in `release/CLA_1.2.zip`. The full production `Images` folder must be present; audio clips are optional and never committed. Keep `_internal` beside the executable. Test with Microsoft Defender and validate calibration/hotkeys before promoting to production.
