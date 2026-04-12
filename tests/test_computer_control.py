# tests/test_computer_control.py
"""
Tests for computer_control.py — ASHI Phase 2: Computer Control.

Strategy:
- Unit tests mock subprocess calls and D-Bus to avoid requiring a live desktop
- Integration tests (marked with @pytest.mark.integration) require a running GNOME session
- All file I/O uses tmp_path to avoid polluting the system
"""
import sys
import os
import base64
from pathlib import Path
from unittest.mock import patch, MagicMock


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions"))

from action_classifier import classify_action, ActionRisk


# ---------------------------------------------------------------------------
# Action classifier tests for new tools
# ---------------------------------------------------------------------------

class TestActionClassifierComputerControl:
    """Verify all computer control tools are classified correctly."""

    def test_screen_capture_is_reversible(self):
        assert classify_action("screen_capture", {}) == ActionRisk.REVERSIBLE

    def test_screen_read_is_reversible(self):
        assert classify_action("screen_read", {"region": "0,0,100,100"}) == ActionRisk.REVERSIBLE

    def test_find_on_screen_is_reversible(self):
        assert classify_action("find_on_screen", {"text": "OK"}) == ActionRisk.REVERSIBLE

    def test_screen_understand_is_reversible(self):
        assert classify_action("screen_understand", {"question": "What app is open?"}) == ActionRisk.REVERSIBLE

    def test_cc_health_is_reversible(self):
        assert classify_action("cc_health", {}) == ActionRisk.REVERSIBLE

    def test_mouse_move_is_irreversible(self):
        assert classify_action("mouse_move", {"x": 100, "y": 200}) == ActionRisk.IRREVERSIBLE

    def test_mouse_click_is_irreversible(self):
        assert classify_action("mouse_click", {"button": "left"}) == ActionRisk.IRREVERSIBLE

    def test_mouse_scroll_is_irreversible(self):
        assert classify_action("mouse_scroll", {"direction": "down"}) == ActionRisk.IRREVERSIBLE

    def test_keyboard_type_is_irreversible(self):
        assert classify_action("keyboard_type", {"text": "hello"}) == ActionRisk.IRREVERSIBLE

    def test_keyboard_key_is_irreversible(self):
        assert classify_action("keyboard_key", {"keys": "ctrl+c"}) == ActionRisk.IRREVERSIBLE

    def test_open_app_is_irreversible(self):
        assert classify_action("open_app", {"app_name": "firefox"}) == ActionRisk.IRREVERSIBLE

    def test_focus_window_is_irreversible(self):
        assert classify_action("focus_window", {"window_name": "Firefox"}) == ActionRisk.IRREVERSIBLE


# ---------------------------------------------------------------------------
# computer_control module tests (mocked)
# ---------------------------------------------------------------------------

# We import inside each test to allow patching module-level state
def _import_cc():
    """Import computer_control with path setup."""
    import computer_control
    return computer_control


class TestScreenCapture:
    """Tests for screen_capture tool."""

    def test_returns_path_on_success(self, tmp_path):
        cc = _import_cc()
        fake_screenshot = tmp_path / "Screenshot.png"
        _write_minimal_png(fake_screenshot)

        with patch.object(cc, "_take_screenshot_portal") as mock_portal:
            mock_portal.return_value = {"success": True, "path": str(fake_screenshot)}
            with patch.object(cc, "_screenshot_path", return_value=str(fake_screenshot)):
                result = cc.screen_capture()

        assert "path" in result
        assert "error" not in result

    def test_returns_base64_when_requested(self, tmp_path):
        cc = _import_cc()
        fake_screenshot = tmp_path / "Screenshot.png"
        _write_minimal_png(fake_screenshot)

        with patch.object(cc, "_take_screenshot_portal") as mock_portal:
            mock_portal.return_value = {"success": True, "path": str(fake_screenshot)}
            with patch.object(cc, "_screenshot_path", return_value=str(fake_screenshot)):
                result = cc.screen_capture(output_format="base64")

        assert "base64" in result
        assert "path" in result
        # Verify it's valid base64
        decoded = base64.b64decode(result["base64"])
        assert len(decoded) > 0

    def test_falls_through_to_gnome_screenshot(self, tmp_path):
        cc = _import_cc()
        fake_screenshot = tmp_path / "Screenshot.png"
        _write_minimal_png(fake_screenshot)

        with patch.object(cc, "_take_screenshot_portal", return_value={"error": "no dbus"}):
            with patch.object(cc, "_take_screenshot_gnome_screenshot") as mock_gs:
                mock_gs.return_value = {"success": True, "path": str(fake_screenshot)}
                with patch.object(cc, "_screenshot_path", return_value=str(fake_screenshot)):
                    result = cc.screen_capture()

        assert "path" in result
        mock_gs.assert_called_once()

    def test_falls_through_to_grim(self, tmp_path):
        cc = _import_cc()
        fake_screenshot = tmp_path / "Screenshot.png"
        _write_minimal_png(fake_screenshot)

        with patch.object(cc, "_take_screenshot_portal", return_value={"error": "no dbus"}):
            with patch.object(cc, "_take_screenshot_gnome_screenshot", return_value={"error": "not installed"}):
                with patch.object(cc, "_take_screenshot_grim") as mock_grim:
                    mock_grim.return_value = {"success": True, "path": str(fake_screenshot)}
                    with patch.object(cc, "_screenshot_path", return_value=str(fake_screenshot)):
                        result = cc.screen_capture()

        assert "path" in result
        mock_grim.assert_called_once()

    def test_returns_error_when_all_methods_fail(self):
        cc = _import_cc()
        with patch.object(cc, "_take_screenshot_portal", return_value={"error": "fail1"}):
            with patch.object(cc, "_take_screenshot_gnome_screenshot", return_value={"error": "fail2"}):
                with patch.object(cc, "_take_screenshot_grim", return_value={"error": "fail3"}):
                    result = cc.screen_capture()

        assert "error" in result

    def test_region_crop(self, tmp_path):
        cc = _import_cc()
        fake_screenshot = tmp_path / "Screenshot.png"
        _write_sized_png(fake_screenshot, 100, 100)

        with patch.object(cc, "_take_screenshot_portal") as mock_portal:
            mock_portal.return_value = {"success": True, "path": str(fake_screenshot)}
            with patch.object(cc, "_screenshot_path", return_value=str(fake_screenshot)):
                result = cc.screen_capture(region="10,10,50,50")

        assert "path" in result
        assert "error" not in result

    def test_invalid_region_format(self, tmp_path):
        cc = _import_cc()
        fake_screenshot = tmp_path / "Screenshot.png"
        _write_minimal_png(fake_screenshot)

        with patch.object(cc, "_take_screenshot_portal") as mock_portal:
            mock_portal.return_value = {"success": True, "path": str(fake_screenshot)}
            with patch.object(cc, "_screenshot_path", return_value=str(fake_screenshot)):
                result = cc.screen_capture(region="bad_format")

        assert "error" in result


class TestScreenRead:
    """Tests for screen_read tool."""

    def test_returns_text_from_image(self, tmp_path):
        cc = _import_cc()
        fake_img = tmp_path / "test.png"
        _write_minimal_png(fake_img)

        with patch("computer_control.pytesseract") as mock_tess:
            mock_tess.image_to_string.return_value = "Hello World"
            with patch.object(cc, "_PIL_AVAILABLE", True), \
                 patch.object(cc, "_TESSERACT_AVAILABLE", True):
                result = cc.screen_read(image_path=str(fake_img))

        assert result["text"] == "Hello World"

    def test_error_when_pillow_missing(self):
        cc = _import_cc()
        with patch.object(cc, "_PIL_AVAILABLE", False):
            result = cc.screen_read()
        assert "error" in result
        assert "Pillow" in result["error"]

    def test_error_when_tesseract_missing(self):
        cc = _import_cc()
        with patch.object(cc, "_PIL_AVAILABLE", True), \
             patch.object(cc, "_TESSERACT_AVAILABLE", False):
            result = cc.screen_read()
        assert "error" in result
        assert "pytesseract" in result["error"]


class TestMouseMove:
    """Tests for mouse_move tool."""

    def test_successful_move(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=True), \
             patch.object(cc, "_run_cmd") as mock_cmd:
            mock_cmd.side_effect = [
                {"stdout": "", "stderr": "Usage: ydotool", "exit_code": 0},
                {"stdout": "", "stderr": "", "exit_code": 0},
            ]
            result = cc.mouse_move(100, 200)

        assert result["success"] is True
        assert result["x"] == 100
        assert result["y"] == 200

    def test_error_when_ydotool_missing(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=False):
            result = cc.mouse_move(100, 200)
        assert "error" in result
        assert "ydotool" in result["error"]


class TestMouseClick:
    """Tests for mouse_click tool."""

    def test_click_without_position(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=True), \
             patch.object(cc, "_run_cmd") as mock_cmd:
            mock_cmd.return_value = {"stdout": "", "stderr": "", "exit_code": 0}
            result = cc.mouse_click(button="left")

        assert result["success"] is True
        assert result["button"] == "left"

    def test_click_with_position(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=True), \
             patch.object(cc, "_run_cmd") as mock_cmd:
            mock_cmd.side_effect = [
                {"stdout": "", "stderr": "Usage: ydotool", "exit_code": 0},
                {"stdout": "", "stderr": "", "exit_code": 0},
                {"stdout": "", "stderr": "", "exit_code": 0},
            ]
            result = cc.mouse_click(button="right", x=500, y=300)

        assert result["success"] is True
        assert result["button"] == "right"

    def test_double_click(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=True), \
             patch.object(cc, "_run_cmd") as mock_cmd:
            mock_cmd.return_value = {"stdout": "", "stderr": "", "exit_code": 0}
            result = cc.mouse_click(button="left", clicks=2)

        assert result["success"] is True
        assert result["clicks"] == 2


class TestMouseScroll:
    """Tests for mouse_scroll tool."""

    def test_scroll_down(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=True), \
             patch.object(cc, "_run_cmd") as mock_cmd:
            mock_cmd.return_value = {"stdout": "", "stderr": "", "exit_code": 0}
            result = cc.mouse_scroll(direction="down", amount=5)

        assert result["success"] is True
        assert result["direction"] == "down"

    def test_scroll_up(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=True), \
             patch.object(cc, "_run_cmd") as mock_cmd:
            mock_cmd.return_value = {"stdout": "", "stderr": "", "exit_code": 0}
            result = cc.mouse_scroll(direction="up", amount=3)

        assert result["success"] is True
        assert result["direction"] == "up"


class TestKeyboardType:
    """Tests for keyboard_type tool."""

    def test_type_text(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=True), \
             patch.object(cc, "_run_cmd") as mock_cmd:
            mock_cmd.return_value = {"stdout": "", "stderr": "", "exit_code": 0}
            result = cc.keyboard_type("Hello World")

        assert result["success"] is True
        assert "Hello" in result["typed"]

    def test_empty_text_error(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=True):
            result = cc.keyboard_type("")
        assert "error" in result

    def test_error_when_ydotool_missing(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=False):
            result = cc.keyboard_type("test")
        assert "error" in result


class TestKeyboardKey:
    """Tests for keyboard_key tool."""

    def test_single_key(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=True), \
             patch.object(cc, "_run_cmd") as mock_cmd:
            mock_cmd.return_value = {"stdout": "", "stderr": "", "exit_code": 0}
            result = cc.keyboard_key("return")

        assert result["success"] is True
        assert result["keys"] == "return"

    def test_combo_key(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=True), \
             patch.object(cc, "_run_cmd") as mock_cmd:
            mock_cmd.return_value = {"stdout": "", "stderr": "", "exit_code": 0}
            result = cc.keyboard_key("ctrl+shift+t")

        assert result["success"] is True
        call_args = mock_cmd.call_args[0][0]
        assert call_args[0] == "ydotool"
        assert call_args[1] == "key"
        # Should have 3 key-downs + 3 key-ups = 6 entries
        assert len(call_args[2:]) == 6

    def test_unknown_key_error(self):
        cc = _import_cc()
        with patch.object(cc, "_ydotool_available", return_value=True):
            result = cc.keyboard_key("nonexistent_key")
        assert "error" in result
        assert "Unknown key" in result["error"]


class TestFindOnScreen:
    """Tests for find_on_screen tool."""

    def test_finds_text(self, tmp_path):
        cc = _import_cc()
        fake_img = tmp_path / "screen.png"
        _write_minimal_png(fake_img)

        mock_data = {
            "text": ["", "Save", "Cancel", ""],
            "conf": ["0", "95", "90", "0"],
            "left": [0, 100, 200, 0],
            "top": [0, 50, 50, 0],
            "width": [0, 40, 60, 0],
            "height": [0, 20, 20, 0],
        }

        with patch.object(cc, "screen_capture", return_value={"path": str(fake_img)}), \
             patch("computer_control.pytesseract") as mock_tess:
            mock_tess.image_to_data.return_value = mock_data
            mock_tess.Output.DICT = "dict"
            result = cc.find_on_screen("Save")

        assert result["found"] is True
        assert len(result["matches"]) == 1
        match = result["matches"][0]
        assert match["text"] == "Save"
        assert match["center_x"] == 120  # 100 + 40//2
        assert match["center_y"] == 60   # 50 + 20//2

    def test_text_not_found(self, tmp_path):
        cc = _import_cc()
        fake_img = tmp_path / "screen.png"
        _write_minimal_png(fake_img)

        mock_data = {
            "text": ["", "Save", ""],
            "conf": ["0", "95", "0"],
            "left": [0, 100, 0],
            "top": [0, 50, 0],
            "width": [0, 40, 0],
            "height": [0, 20, 0],
        }

        with patch.object(cc, "screen_capture", return_value={"path": str(fake_img)}), \
             patch("computer_control.pytesseract") as mock_tess:
            mock_tess.image_to_data.return_value = mock_data
            mock_tess.Output.DICT = "dict"
            result = cc.find_on_screen("Delete")

        assert result["found"] is False


class TestOpenApp:
    """Tests for open_app tool."""

    def test_launches_binary(self):
        cc = _import_cc()
        with patch("shutil.which", return_value="/usr/bin/firefox"), \
             patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc
            result = cc.open_app("firefox")

        assert result["success"] is True
        assert result["pid"] == 12345

    def test_app_not_found(self):
        cc = _import_cc()
        with patch("shutil.which", return_value=None):
            with patch("os.listdir", return_value=[]):
                result = cc.open_app("nonexistent_app_xyz")

        assert "error" in result


class TestFocusWindow:
    """Tests for focus_window tool."""

    def test_focus_via_dbus(self):
        cc = _import_cc()
        mock_bus = MagicMock()
        mock_shell = MagicMock()
        mock_iface = MagicMock()
        mock_iface.Eval.return_value = (True, "'Firefox'")

        with patch.object(cc, "_DBUS_AVAILABLE", True), \
             patch("computer_control.dbus", create=True) as mock_dbus:
            mock_dbus.SessionBus.return_value = mock_bus
            mock_bus.get_object.return_value = mock_shell
            mock_dbus.Interface.return_value = mock_iface
            result = cc.focus_window("Firefox")

        assert result["success"] is True

    def test_error_when_window_not_found(self):
        cc = _import_cc()
        with patch.object(cc, "_DBUS_AVAILABLE", False), \
             patch("shutil.which", return_value=None):
            result = cc.focus_window("nonexistent_window")

        assert "error" in result


class TestScreenUnderstand:
    """Tests for screen_understand tool."""

    def test_calls_ollama_with_image(self, tmp_path):
        cc = _import_cc()
        fake_img = tmp_path / "screen.png"
        _write_minimal_png(fake_img)

        mock_httpx = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "A terminal window with code editor open.",
            "eval_count": 42,
        }
        mock_httpx.post.return_value = mock_response
        mock_httpx.ConnectError = Exception

        # httpx is imported at function scope inside screen_understand,
        # so we patch the builtins __import__ to intercept it
        import builtins
        _real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "httpx":
                return mock_httpx
            return _real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            result = cc.screen_understand(
                question="What is on the screen?",
                image_path=str(fake_img),
            )

        assert "description" in result
        assert "terminal" in result["description"].lower()
        assert result["tokens"] == 42

    def test_error_on_ollama_down(self, tmp_path):
        cc = _import_cc()
        fake_img = tmp_path / "screen.png"
        _write_minimal_png(fake_img)

        mock_httpx = MagicMock()
        mock_httpx.ConnectError = ConnectionError
        mock_httpx.post.side_effect = ConnectionError("refused")

        import builtins
        _real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "httpx":
                return mock_httpx
            return _real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            result = cc.screen_understand(image_path=str(fake_img))

        assert "error" in result


class TestHealthCheck:
    """Tests for check_computer_control_health."""

    def test_returns_all_dependencies(self):
        cc = _import_cc()
        mock_httpx = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": [{"name": "moondream:latest"}]}
        mock_httpx.get.return_value = mock_resp

        import builtins
        _real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "httpx":
                return mock_httpx
            return _real_import(name, *args, **kwargs)

        with patch("shutil.which", return_value="/usr/bin/fake"), \
             patch("builtins.__import__", side_effect=_mock_import):
            health = cc.check_computer_control_health()

        assert "ydotool" in health
        assert "tesseract" in health
        assert "pillow" in health
        assert "pytesseract" in health
        assert "dbus" in health
        assert "session_type" in health
        assert "vision_model" in health


# ---------------------------------------------------------------------------
# Tool dispatch integration tests
# ---------------------------------------------------------------------------

class TestToolDispatchRegistration:
    """Verify computer control tools are registered in tool_dispatch."""

    def test_computer_control_tools_in_registry(self):
        from tool_dispatch import TOOL_REGISTRY

        expected_tools = [
            "screen_capture", "screen_read", "screen_understand",
            "find_on_screen", "mouse_move", "mouse_click", "mouse_scroll",
            "keyboard_type", "keyboard_key", "open_app", "focus_window",
            "cc_health",
        ]

        for tool_name in expected_tools:
            assert tool_name in TOOL_REGISTRY, f"{tool_name} not registered in TOOL_REGISTRY"

    def test_dispatch_unknown_tool_still_works(self):
        from tool_dispatch import dispatch

        result = dispatch({"tool": "totally_fake_tool", "args": {}})
        assert "error" in result
        assert "unknown tool" in result["error"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_minimal_png(path: Path):
    """Write a minimal valid 1x1 white PNG file."""
    import struct
    import zlib

    def _chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)
    raw = b"\x00\xff\xff\xff"
    idat = _chunk(b"IDAT", zlib.compress(raw))
    iend = _chunk(b"IEND", b"")

    with open(path, "wb") as f:
        f.write(signature + ihdr + idat + iend)


def _write_sized_png(path: Path, width: int, height: int):
    """Write a valid PNG file of given dimensions (white pixels)."""
    import struct
    import zlib

    def _chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)
    raw = b""
    for _ in range(height):
        raw += b"\x00" + b"\xff\xff\xff" * width
    idat = _chunk(b"IDAT", zlib.compress(raw))
    iend = _chunk(b"IEND", b"")

    with open(path, "wb") as f:
        f.write(signature + ihdr + idat + iend)
