CHAOS LOSS AVERSION v1.1
=======================
Windows 10/11 (64-bit)

Step 1: Waste Less Chaos Orbs
Step 2: ?
Step 3: Profit

ABOUT
-----
Chaos Loss Aversion (CLA) is a lightweight Windows utility for Path of Exile 2. It uses the in-game stash search capabilities to provide a visual and audio notification when the item in the Currency Tab's center slot matches your search criteria.

When CLA detects a match, it updates the visual indicator and plays a randomly selected audio notification. You remain in control of every crafting action.

HOW IT WORKS
------------
1. CALIBRATE
Use the guided calibration process to:
  - Draw a box around the center item slot in your Currency Tab.
  - Confirm the detected slot boundaries.
  - Capture a negative sample (an item that does not match your search).
  - Capture a positive sample (an item that matches your search).

Calibration is saved between sessions. However, recalibration is required if your resolution, display mode, or monitored slot position changes.

Calibration works in Windowed and Borderless Windowed modes. If you play in Fullscreen, use Borderless Windowed for calibration.

2. MONITOR
Press F7 to toggle the visual indicator.
  - Yellow = Not Monitoring
  - Green = No match, safe to continue spamming.
  - Red = Match detected, stop Chaos spamming.

Press F8 to start or stop monitoring. CLA watches a small calibrated area of the screen rather than scanning the entire display.

3. RESPOND TO A MATCH
On a positive match, CLA:
  - Updates the visual indicator, if visible.
  - Plays a randomly selected audio notification, if available.

CLA keeps the red MATCH notification visible until you left-click inside the monitored item slot. This prevents the notification from disappearing if you hover over another item and its tooltip temporarily obscures the monitored slot. Without this behavior, the notification could repeatedly appear and disappear, which gets annoying very quickly.

CONTROLS AND FEATURES
---------------------
  - F7: Show or hide the stoplight overlay (rebindable).
  - F8: Toggle monitoring (rebindable).
  - F9: Capture a calibration sample (rebindable).
  - Guided calibration and saved settings.
  - Adjustable notification volume and randomized audio clips.
  - Compact stoplight indicator for at-a-glance feedback with adjustable thickness and opacity.
  - Links to crafting resources, including PoE2DB, Waystone and Tablet regex tools, and Renly's Tools.

IMPORTANT LIMITATIONS
---------------------
  - CLA supports the center item slot of the Currency Tab.
  - Accurate detection depends on calibration and consistent screen conditions.
  - CLA uses visual screen capture. It does not read game memory, modify game files, or communicate with game servers.
  - CLA does not click, move items, use currency, or send keyboard inputs to Path of Exile 2.
  - Notifications are not guaranteed to prevent an over roll. All crafting decisions and actions remain yours.

ABOUT TIER TWOLONGS
-------------------
Chaos Loss Aversion is an independent, Kyle-developed utility created for the Tier Twolongs Path of Exile 2 community.

Website: https://www.tiertwolongs.com
Source: https://github.com/tiertwolongs/chaos-loss-aversion

CLA is not affiliated with or endorsed by Grinding Gear Games.

Built by Tier Twolongs for Tier Twolongs.
We put the mid in pyramid.
