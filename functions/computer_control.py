# functions/computer_control.py
"""
Computer Control — gives ASHI mouse, keyboard, screen reading, and UI interaction.

Platform: Ubuntu 22.04+ / GNOME / Wayland (X11 fallback supported)
Dependencies:
  System: ydotool, tesseract-ocr, tesseract-ocr-eng
  Python: Pillow, pytesseract, python-dbus (system package)

Architecture:
  - Screenshots via xdg-desktop-portal D-Bus (Wayland-native, no dialog with interactive=False)
  - Input via ydotool (works on both Wayland and X11 through /dev/uinput)
  - OCR via pytesseract (tesseract-ocr engine)
  - Vision via moondream2 on Ollama (screen understanding)
  - Window management via gio/wmctrl/xdotool depending on session type
"""
import base64
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Lazy imports — fail gracefully with clear error messages
# ---------------------------------------------------------------------------

_PIL_AVAILABLE = False
_TESSERACT_AVAILABLE = False
_DBUS_AVAILABLE = False

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    pass

try:
    import pytesseract
    _TESSERACT_AVAILABLE = True
except ImportError:
    pass

try:
    import dbus
    _DBUS_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCREENSHOT_DIR = os.path.expanduser("~/.cache/ashi/screenshots")
YDOTOOL_BINARY = shutil.which("ydotool") or "/usr/bin/ydotool"
VISION_MODEL = os.environ.get("ASHI_VISION_MODEL", "moondream")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
SESSION_TYPE = os.environ.get("XDG_SESSION_TYPE", "wayland")

# Ensure screenshot cache dir exists
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_dependency(name: str, check_fn) -> Optional[str]:
    """Return error string if dependency missing, None if OK."""
    try:
        if check_fn():
            return None
    except Exception:
        pass
    return f"Missing dependency: {name}. Run the setup script."


def _run_cmd(cmd: list[str], timeout: int = 10) -> dict:
    """Run a subprocess command, return {stdout, stderr, exit_code}."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Timed out after {timeout}s", "exit_code": -1}
    except FileNotFoundError:
        return {"stdout": "", "stderr": f"Binary not found: {cmd[0]}", "exit_code": 127}


def _screenshot_path(prefix: str = "ashi_screenshot") -> str:
    """Generate a unique screenshot file path."""
    ts = int(time.time() * 1000)
    return os.path.join(SCREENSHOT_DIR, f"{prefix}_{ts}.png")


def _image_to_base64(filepath: str) -> str:
    """Read a PNG file and return base64-encoded string."""
    with open(filepath, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _take_screenshot_portal(filepath: str) -> dict:
    """
    Take screenshot via xdg-desktop-portal D-Bus API.
    Works on GNOME Wayland without user interaction when interactive=False.
    """
    if not _DBUS_AVAILABLE:
        return {"error": "python3-dbus not installed. Run: sudo apt install python3-dbus"}

    try:
        bus = dbus.SessionBus()
        portal = bus.get_object(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
        )
        iface = dbus.Interface(portal, "org.freedesktop.portal.Screenshot")
        options = dbus.Dictionary(
            {"interactive": dbus.Boolean(False)},
            signature="sv",
        )
        handle = iface.Screenshot("", options)

        # Portal saves to ~/Pictures/Screenshot*.png
        # Wait briefly for the file to appear
        time.sleep(0.5)

        # Find the most recent screenshot in ~/Pictures
        pictures_dir = os.path.expanduser("~/Pictures")
        candidates = sorted(
            Path(pictures_dir).glob("Screenshot*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not candidates:
            return {"error": "Portal screenshot call succeeded but no file found in ~/Pictures"}

        source = str(candidates[0])
        # Move to our cache directory
        shutil.move(source, filepath)
        return {"success": True, "path": filepath}

    except dbus.exceptions.DBusException as e:
        return {"error": f"D-Bus screenshot failed: {e}"}
    except Exception as e:
        return {"error": f"Screenshot failed: {e}"}


def _take_screenshot_gnome_screenshot(filepath: str) -> dict:
    """Fallback: use gnome-screenshot CLI if installed."""
    gs = shutil.which("gnome-screenshot")
    if not gs:
        return {"error": "gnome-screenshot not installed"}
    result = _run_cmd([gs, "-f", filepath], timeout=5)
    if result["exit_code"] == 0 and os.path.exists(filepath):
        return {"success": True, "path": filepath}
    return {"error": f"gnome-screenshot failed: {result['stderr']}"}


def _take_screenshot_grim(filepath: str, region: Optional[str] = None) -> dict:
    """Fallback for wlroots compositors (not GNOME). Use grim."""
    grim = shutil.which("grim")
    if not grim:
        return {"error": "grim not installed"}
    cmd = [grim]
    if region:
        cmd.extend(["-g", region])
    cmd.append(filepath)
    result = _run_cmd(cmd, timeout=5)
    if result["exit_code"] == 0 and os.path.exists(filepath):
        return {"success": True, "path": filepath}
    return {"error": f"grim failed: {result['stderr']}"}


# ---------------------------------------------------------------------------
# Tool: screen_capture
# ---------------------------------------------------------------------------

def screen_capture(
    region: Optional[str] = None,
    output_format: str = "path",
) -> dict:
    """
    Capture screenshot of the entire screen or a region.

    Args:
        region:        Optional "x,y,width,height" string for area capture.
                       If None, captures full screen.
        output_format: "path" returns file path, "base64" returns base64 PNG string.

    Returns:
        {path: str} or {base64: str, path: str} on success
        {error: str} on failure
    """
    filepath = _screenshot_path()

    if region:
        # For region capture, take full screenshot then crop with PIL
        result = _take_screenshot_portal(filepath)
        if "error" in result:
            result = _take_screenshot_gnome_screenshot(filepath)
        if "error" in result:
            result = _take_screenshot_grim(filepath)
        if "error" in result:
            return result

        # Crop to region
        if not _PIL_AVAILABLE:
            return {"error": "Pillow not installed for region crop. Run: pip install Pillow"}
        try:
            parts = [int(x.strip()) for x in region.split(",")]
            if len(parts) != 4:
                return {"error": "region must be 'x,y,width,height'"}
            x, y, w, h = parts
            img = Image.open(filepath)
            cropped = img.crop((x, y, x + w, y + h))
            cropped.save(filepath)
        except Exception as e:
            return {"error": f"Region crop failed: {e}"}
    else:
        result = _take_screenshot_portal(filepath)
        if "error" in result:
            result = _take_screenshot_gnome_screenshot(filepath)
        if "error" in result:
            result = _take_screenshot_grim(filepath)
        if "error" in result:
            return result

    response = {"path": filepath}
    if output_format == "base64":
        response["base64"] = _image_to_base64(filepath)
    return response


# ---------------------------------------------------------------------------
# Tool: screen_read (OCR)
# ---------------------------------------------------------------------------

def screen_read(
    region: Optional[str] = None,
    image_path: Optional[str] = None,
    lang: str = "eng",
) -> dict:
    """
    OCR the screen or a region, returning recognized text.

    Args:
        region:     Optional "x,y,width,height" to OCR only that area.
        image_path: Optional path to an existing screenshot. If None, takes a new one.
        lang:       Tesseract language code (default: eng).

    Returns:
        {text: str, path: str} on success
        {error: str} on failure
    """
    if not _PIL_AVAILABLE:
        return {"error": "Pillow not installed. Run: pip install Pillow"}
    if not _TESSERACT_AVAILABLE:
        return {"error": "pytesseract not installed. Run: pip install pytesseract"}

    # Get or take screenshot
    if image_path and os.path.exists(image_path):
        filepath = image_path
    else:
        cap = screen_capture(region=region)
        if "error" in cap:
            return cap
        filepath = cap["path"]

    try:
        img = Image.open(filepath)

        # If region specified and we didn't already crop via screen_capture
        if region and image_path:
            parts = [int(x.strip()) for x in region.split(",")]
            if len(parts) == 4:
                x, y, w, h = parts
                img = img.crop((x, y, x + w, y + h))

        text = pytesseract.image_to_string(img, lang=lang)
        return {"text": text.strip(), "path": filepath}
    except Exception as e:
        return {"error": f"OCR failed: {e}"}


# ---------------------------------------------------------------------------
# Tools: mouse_move, mouse_click, mouse_scroll
# ---------------------------------------------------------------------------

def _ydotool_available() -> bool:
    """Check if ydotool binary exists."""
    return os.path.isfile(YDOTOOL_BINARY) or shutil.which("ydotool") is not None


def mouse_move(x: int, y: int, absolute: bool = True) -> dict:
    """
    Move mouse cursor to position.

    Args:
        x:        X coordinate (pixels from left)
        y:        Y coordinate (pixels from top)
        absolute: If True, move to absolute position. If False, relative move.

    Returns:
        {success: True, x: int, y: int} or {error: str}
    """
    if not _ydotool_available():
        return {"error": "ydotool not installed. Run: sudo apt install ydotool"}

    flags = ["--absolute"] if absolute else []
    # ydotool 0.1.x syntax: ydotool mousemove [--absolute] -- x y
    # ydotool 1.x syntax: ydotool mousemove -a -x X -y Y
    # Detect version
    ver_result = _run_cmd(["ydotool", "--help"])
    help_text = ver_result.get("stdout", "") + ver_result.get("stderr", "")

    if "-x" in help_text and "-y" in help_text:
        # ydotool 1.x
        cmd = ["ydotool", "mousemove"]
        if absolute:
            cmd.append("-a")
        cmd.extend(["-x", str(x), "-y", str(y)])
    else:
        # ydotool 0.1.x
        cmd = ["ydotool", "mousemove"]
        if absolute:
            cmd.append("--absolute")
        cmd.extend(["--", str(x), str(y)])

    result = _run_cmd(cmd)
    if result["exit_code"] == 0:
        return {"success": True, "x": x, "y": y}
    return {"error": f"mouse_move failed: {result['stderr']}"}


def mouse_click(
    button: str = "left",
    x: Optional[int] = None,
    y: Optional[int] = None,
    clicks: int = 1,
) -> dict:
    """
    Click mouse button, optionally at a specific position.

    Args:
        button:  "left", "right", or "middle"
        x:       Optional X coordinate (move first if provided)
        y:       Optional Y coordinate (move first if provided)
        clicks:  Number of clicks (1=single, 2=double)

    Returns:
        {success: True, button: str} or {error: str}
    """
    if not _ydotool_available():
        return {"error": "ydotool not installed. Run: sudo apt install ydotool"}

    # Move to position first if coordinates given
    if x is not None and y is not None:
        move_result = mouse_move(x, y, absolute=True)
        if "error" in move_result:
            return move_result
        time.sleep(0.05)  # Brief pause for cursor to settle

    button_map = {"left": "0", "right": "1", "middle": "2"}
    btn_code = button_map.get(button.lower(), "0")

    # ydotool click uses hex button codes: 0xC0=left, 0xC1=right, 0xC2=middle
    # For 0.1.x: ydotool click <button_id>
    # button_id: 1=left, 2=right, 3=middle for 0.1.x
    btn_code_01x = {"left": "1", "right": "2", "middle": "3"}.get(button.lower(), "1")

    for _ in range(clicks):
        result = _run_cmd(["ydotool", "click", btn_code_01x])
        if result["exit_code"] != 0:
            # Try 1.x syntax
            hex_code = {"left": "0xC0", "right": "0xC1", "middle": "0xC2"}.get(button.lower(), "0xC0")
            result = _run_cmd(["ydotool", "click", hex_code])
            if result["exit_code"] != 0:
                return {"error": f"mouse_click failed: {result['stderr']}"}
        if clicks > 1:
            time.sleep(0.05)

    return {"success": True, "button": button, "clicks": clicks}


def mouse_scroll(direction: str = "down", amount: int = 3) -> dict:
    """
    Scroll the mouse wheel.

    Args:
        direction: "up" or "down"
        amount:    Number of scroll steps (default 3)

    Returns:
        {success: True, direction: str, amount: int} or {error: str}
    """
    if not _ydotool_available():
        return {"error": "ydotool not installed. Run: sudo apt install ydotool"}

    # ydotool 0.1.x: ydotool mousemove -- 0 <delta>  (positive = down, negative = up)
    # delta in scroll units
    delta = amount if direction.lower() == "down" else -amount

    # Try ydotool 0.1.x scroll syntax
    result = _run_cmd(["ydotool", "mousemove", "--wheel", "--", "0", str(delta)])
    if result["exit_code"] != 0:
        # Try alternative syntax for different versions
        # Some versions use: ydotool mousemove -w -- 0 <delta>
        result = _run_cmd(["ydotool", "mousemove", "-w", "--", "0", str(delta)])
    if result["exit_code"] != 0:
        return {"error": f"mouse_scroll failed: {result['stderr']}"}

    return {"success": True, "direction": direction, "amount": amount}


# ---------------------------------------------------------------------------
# Tools: keyboard_type, keyboard_key
# ---------------------------------------------------------------------------

def keyboard_type(text: str, delay_ms: int = 12) -> dict:
    """
    Type a string of text as if from a keyboard.

    Args:
        text:     The text to type.
        delay_ms: Delay between keystrokes in milliseconds (default 12).

    Returns:
        {success: True, typed: str} or {error: str}
    """
    if not _ydotool_available():
        return {"error": "ydotool not installed. Run: sudo apt install ydotool"}

    if not text:
        return {"error": "Empty text provided"}

    # ydotool type -- "text"
    # --delay for keystroke delay
    cmd = ["ydotool", "type", "--delay", str(delay_ms), "--", text]
    result = _run_cmd(cmd, timeout=30)

    if result["exit_code"] == 0:
        return {"success": True, "typed": text[:100]}
    return {"error": f"keyboard_type failed: {result['stderr']}"}


def keyboard_key(keys: str) -> dict:
    """
    Press a key combination (hotkey).

    Args:
        keys: Key combo string, e.g. "ctrl+c", "alt+tab", "super", "Return",
              "ctrl+shift+t". Uses ydotool key names.

    Returns:
        {success: True, keys: str} or {error: str}
    """
    if not _ydotool_available():
        return {"error": "ydotool not installed. Run: sudo apt install ydotool"}

    # Translate human-readable key names to ydotool keycodes
    # ydotool 0.1.x uses: ydotool key <key_name>
    # Common mappings: ctrl=29, shift=42, alt=56, super=125, tab=15, Return=28
    KEY_MAP = {
        "ctrl": "29",
        "control": "29",
        "shift": "42",
        "alt": "56",
        "super": "125",
        "meta": "125",
        "tab": "15",
        "return": "28",
        "enter": "28",
        "escape": "1",
        "esc": "1",
        "backspace": "14",
        "delete": "111",
        "space": "57",
        "up": "103",
        "down": "108",
        "left": "105",
        "right": "106",
        "home": "102",
        "end": "107",
        "pageup": "104",
        "pagedown": "109",
        "f1": "59", "f2": "60", "f3": "61", "f4": "62",
        "f5": "63", "f6": "64", "f7": "65", "f8": "66",
        "f9": "67", "f10": "68", "f11": "87", "f12": "88",
        "a": "30", "b": "48", "c": "46", "d": "32", "e": "18",
        "f": "33", "g": "34", "h": "35", "i": "23", "j": "36",
        "k": "37", "l": "38", "m": "50", "n": "49", "o": "24",
        "p": "25", "q": "16", "r": "19", "s": "31", "t": "20",
        "u": "22", "v": "47", "w": "17", "x": "45", "y": "21",
        "z": "44",
        "1": "2", "2": "3", "3": "4", "4": "5", "5": "6",
        "6": "7", "7": "8", "8": "9", "9": "10", "0": "11",
    }

    # Parse "ctrl+shift+t" into individual keys
    parts = [k.strip().lower() for k in keys.split("+")]

    # Build ydotool key command
    # ydotool 0.1.x: ydotool key <keycode>:<pressed> ...
    # pressed=1 for down, 0 for up
    key_sequence = []
    for part in parts:
        code = KEY_MAP.get(part)
        if not code:
            return {"error": f"Unknown key: '{part}'. Available: {', '.join(sorted(KEY_MAP.keys()))}"}
        key_sequence.append(f"{code}:1")  # key down

    # Release in reverse order
    for part in reversed(parts):
        code = KEY_MAP.get(part)
        key_sequence.append(f"{code}:0")  # key up

    cmd = ["ydotool", "key"] + key_sequence
    result = _run_cmd(cmd)

    if result["exit_code"] == 0:
        return {"success": True, "keys": keys}
    return {"error": f"keyboard_key failed: {result['stderr']}"}


# ---------------------------------------------------------------------------
# Tool: find_on_screen
# ---------------------------------------------------------------------------

def find_on_screen(
    text: str,
    region: Optional[str] = None,
    confidence: float = 0.6,
) -> dict:
    """
    Find text on screen using OCR and return its bounding box coordinates.

    Args:
        text:       Text string to find on screen.
        region:     Optional "x,y,width,height" to limit search area.
        confidence: Minimum OCR confidence (0.0-1.0). Default 0.6.

    Returns:
        {found: True, matches: [{text, x, y, width, height, center_x, center_y, confidence}]}
        {found: False, error: str} if not found
    """
    if not _PIL_AVAILABLE:
        return {"error": "Pillow not installed. Run: pip install Pillow"}
    if not _TESSERACT_AVAILABLE:
        return {"error": "pytesseract not installed. Run: pip install pytesseract"}

    # Take screenshot
    cap = screen_capture(region=region)
    if "error" in cap:
        return cap

    try:
        img = Image.open(cap["path"])
        # Use pytesseract to get word-level bounding boxes
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        matches = []
        search_lower = text.lower()
        n_boxes = len(data["text"])

        # Offset for region-relative coordinates
        offset_x, offset_y = 0, 0
        if region:
            parts = [int(x.strip()) for x in region.split(",")]
            if len(parts) == 4:
                offset_x, offset_y = parts[0], parts[1]

        # Search for single-word matches
        for i in range(n_boxes):
            word = data["text"][i].strip()
            conf = float(data["conf"][i]) / 100.0 if data["conf"][i] != "-1" else 0.0

            if word and search_lower in word.lower() and conf >= confidence:
                x = data["left"][i] + offset_x
                y = data["top"][i] + offset_y
                w = data["width"][i]
                h = data["height"][i]
                matches.append({
                    "text": word,
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h,
                    "center_x": x + w // 2,
                    "center_y": y + h // 2,
                    "confidence": round(conf, 3),
                })

        # Also search multi-word matches by concatenating adjacent words
        if not matches and " " in text:
            words = []
            for i in range(n_boxes):
                word = data["text"][i].strip()
                if word:
                    words.append({
                        "text": word,
                        "index": i,
                        "left": data["left"][i],
                        "top": data["top"][i],
                        "width": data["width"][i],
                        "height": data["height"][i],
                        "conf": float(data["conf"][i]) / 100.0 if data["conf"][i] != "-1" else 0.0,
                    })

            joined = " ".join(w["text"] for w in words).lower()
            start_idx = joined.find(search_lower)
            if start_idx != -1:
                # Find which words this spans
                char_count = 0
                first_word = last_word = None
                for wi, w in enumerate(words):
                    word_start = char_count
                    word_end = char_count + len(w["text"])
                    if word_start <= start_idx < word_end and first_word is None:
                        first_word = wi
                    if word_start < start_idx + len(search_lower) <= word_end + 1:
                        last_word = wi
                    char_count = word_end + 1  # +1 for space

                if first_word is not None and last_word is not None:
                    fw = words[first_word]
                    lw = words[last_word]
                    x = fw["left"] + offset_x
                    y = min(fw["top"], lw["top"]) + offset_y
                    w = (lw["left"] + lw["width"]) - fw["left"]
                    h = max(fw["top"] + fw["height"], lw["top"] + lw["height"]) - min(fw["top"], lw["top"])
                    avg_conf = sum(words[j]["conf"] for j in range(first_word, last_word + 1)) / (last_word - first_word + 1)

                    if avg_conf >= confidence:
                        matches.append({
                            "text": text,
                            "x": x,
                            "y": y,
                            "width": w,
                            "height": h,
                            "center_x": x + w // 2,
                            "center_y": y + h // 2,
                            "confidence": round(avg_conf, 3),
                        })

        if matches:
            return {"found": True, "matches": matches, "screenshot": cap["path"]}
        return {"found": False, "error": f"Text '{text}' not found on screen", "screenshot": cap["path"]}

    except Exception as e:
        return {"error": f"find_on_screen failed: {e}"}


# ---------------------------------------------------------------------------
# Tools: open_app, focus_window
# ---------------------------------------------------------------------------

def open_app(app_name: str, args: Optional[str] = None) -> dict:
    """
    Launch an application by name.

    Args:
        app_name: Application name (e.g. "firefox", "nautilus", "gnome-terminal").
                  Can also be a .desktop file basename (e.g. "org.gnome.Calculator").
        args:     Optional arguments to pass to the application.

    Returns:
        {success: True, app: str, pid: int} or {error: str}
    """
    # Try to find the binary
    binary = shutil.which(app_name)

    if binary:
        cmd = [binary]
        if args:
            cmd.extend(args.split())
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            time.sleep(0.3)  # Brief wait for process to start
            return {"success": True, "app": app_name, "pid": proc.pid}
        except Exception as e:
            return {"error": f"Failed to launch {app_name}: {e}"}

    # Try gio launch (for .desktop files)
    # Search for .desktop file
    desktop_dirs = [
        "/usr/share/applications",
        os.path.expanduser("~/.local/share/applications"),
        "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    ]

    app_lower = app_name.lower()
    for d in desktop_dirs:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if f.endswith(".desktop") and app_lower in f.lower():
                desktop_path = os.path.join(d, f)
                result = _run_cmd(["gio", "launch", desktop_path])
                if result["exit_code"] == 0:
                    return {"success": True, "app": app_name, "desktop_file": f}

    return {"error": f"Application '{app_name}' not found as binary or .desktop file"}


def focus_window(window_name: str) -> dict:
    """
    Bring a window to the foreground by title or app name.

    Args:
        window_name: Window title substring or application WM_CLASS name.

    Returns:
        {success: True, window: str} or {error: str}
    """
    # Strategy 1: Use gdbus to activate via GNOME Shell (Wayland-native)
    if _DBUS_AVAILABLE:
        try:
            bus = dbus.SessionBus()
            shell = bus.get_object("org.gnome.Shell", "/org/gnome/Shell")
            eval_iface = dbus.Interface(shell, "org.gnome.Shell")

            # Use GNOME Shell JS to find and activate window
            js_code = f"""
            (function() {{
                let start = global.get_window_actors();
                for (let actor of start) {{
                    let win = actor.get_meta_window();
                    let title = win.get_title() || '';
                    let wm_class = win.get_wm_class() || '';
                    if (title.toLowerCase().includes('{window_name.lower()}') ||
                        wm_class.toLowerCase().includes('{window_name.lower()}')) {{
                        win.activate(global.get_current_time());
                        return title;
                    }}
                }}
                return '';
            }})()
            """

            success, result = eval_iface.Eval(js_code)
            if success and result and result != "''":
                return {"success": True, "window": result.strip("'")}
        except Exception:
            pass  # Fall through to alternatives

    # Strategy 2: Use wmctrl (works on X11 / XWayland)
    wmctrl = shutil.which("wmctrl")
    if wmctrl:
        # List windows
        list_result = _run_cmd(["wmctrl", "-l"])
        if list_result["exit_code"] == 0:
            for line in list_result["stdout"].splitlines():
                if window_name.lower() in line.lower():
                    # Extract window ID (first column)
                    win_id = line.split()[0]
                    activate_result = _run_cmd(["wmctrl", "-i", "-a", win_id])
                    if activate_result["exit_code"] == 0:
                        return {"success": True, "window": line.split(None, 4)[-1] if len(line.split()) > 4 else window_name}

    # Strategy 3: Use xdotool (X11/XWayland only)
    xdotool = shutil.which("xdotool")
    if xdotool:
        search_result = _run_cmd(["xdotool", "search", "--name", window_name])
        if search_result["exit_code"] == 0 and search_result["stdout"].strip():
            win_id = search_result["stdout"].strip().splitlines()[0]
            _run_cmd(["xdotool", "windowactivate", win_id])
            return {"success": True, "window": window_name}

    return {"error": f"Could not find or focus window '{window_name}'. Available methods: gdbus(GNOME), wmctrl, xdotool"}


# ---------------------------------------------------------------------------
# Tool: screen_understand (Vision model)
# ---------------------------------------------------------------------------

def screen_understand(
    question: str = "Describe what is on the screen.",
    image_path: Optional[str] = None,
    region: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """
    Send a screenshot to a vision model to understand UI state.

    Args:
        question:   What to ask about the screen (default: describe the screen).
        image_path: Optional path to existing screenshot. Takes new one if None.
        region:     Optional "x,y,width,height" to analyze only that area.
        model:      Vision model name (default: moondream via Ollama).

    Returns:
        {description: str, model: str, path: str} on success
        {error: str} on failure
    """
    model = model or VISION_MODEL

    # Get screenshot
    if image_path and os.path.exists(image_path):
        filepath = image_path
    else:
        cap = screen_capture(region=region)
        if "error" in cap:
            return cap
        filepath = cap["path"]

    # Read image as base64
    img_b64 = _image_to_base64(filepath)

    # Call Ollama vision API
    try:
        import httpx
    except ImportError:
        return {"error": "httpx not installed. Run: pip install httpx"}

    try:
        payload = {
            "model": model,
            "prompt": question,
            "images": [img_b64],
            "stream": False,
        }

        response = httpx.post(
            f"{OLLAMA_HOST}/api/generate",
            json=payload,
            timeout=60.0,
        )

        if response.status_code != 200:
            return {"error": f"Ollama returned {response.status_code}: {response.text[:200]}"}

        result = response.json()
        description = result.get("response", "").strip()

        if not description:
            return {"error": "Vision model returned empty response"}

        return {
            "description": description,
            "model": model,
            "path": filepath,
            "tokens": result.get("eval_count", 0),
        }
    except httpx.ConnectError:
        return {"error": f"Cannot connect to Ollama at {OLLAMA_HOST}. Is it running?"}
    except Exception as e:
        return {"error": f"screen_understand failed: {e}"}


# ---------------------------------------------------------------------------
# Health check — verify all dependencies
# ---------------------------------------------------------------------------

def check_computer_control_health() -> dict:
    """
    Check all dependencies for computer control tools.

    Returns dict with status of each dependency:
        {dependency_name: {"available": bool, "detail": str}}
    """
    health = {}

    # ydotool
    ydotool_path = shutil.which("ydotool")
    health["ydotool"] = {
        "available": ydotool_path is not None,
        "detail": ydotool_path or "Not found. Run: sudo apt install ydotool",
    }

    # Tesseract
    tess_path = shutil.which("tesseract")
    health["tesseract"] = {
        "available": tess_path is not None,
        "detail": tess_path or "Not found. Run: sudo apt install tesseract-ocr tesseract-ocr-eng",
    }

    # Python packages
    health["pillow"] = {
        "available": _PIL_AVAILABLE,
        "detail": "OK" if _PIL_AVAILABLE else "Run: pip install Pillow",
    }
    health["pytesseract"] = {
        "available": _TESSERACT_AVAILABLE,
        "detail": "OK" if _TESSERACT_AVAILABLE else "Run: pip install pytesseract",
    }
    health["dbus"] = {
        "available": _DBUS_AVAILABLE,
        "detail": "OK" if _DBUS_AVAILABLE else "Run: sudo apt install python3-dbus",
    }

    # Session type
    health["session_type"] = {
        "available": True,
        "detail": SESSION_TYPE,
    }

    # Ollama vision model
    try:
        import httpx
        resp = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
        models = [m["name"] for m in resp.json().get("models", [])]
        has_vision = any(VISION_MODEL in m for m in models)
        health["vision_model"] = {
            "available": has_vision,
            "detail": f"{VISION_MODEL} {'found' if has_vision else 'not found'} in Ollama. Models: {', '.join(models[:5])}",
        }
    except Exception as e:
        health["vision_model"] = {
            "available": False,
            "detail": f"Ollama not reachable: {e}",
        }

    return health
