"""Optional bounded Windows mouse/keyboard batches bound to one exact application window."""

from __future__ import annotations

import importlib
import ntpath
import os
import time
from collections.abc import Callable
from typing import Any

from uaf.config import Settings
from uaf.errors import PolicyDenied, SideEffectError, UnavailableError, ValidationError
from uaf.models import RiskTier, ToolContext, ToolResult
from uaf.tools import ToolMetadata
from uaf.util import reject_secret_data

_PRESS_KEYS = frozenset(
    {
        "enter",
        "tab",
        "esc",
        "backspace",
        "delete",
        "up",
        "down",
        "left",
        "right",
        "home",
        "end",
        "pageup",
        "pagedown",
        "space",
        *(f"f{index}" for index in range(1, 13)),
    }
)
_MODIFIERS = frozenset({"ctrl", "alt", "shift"})
_DENIED_HOTKEYS = {
    ("alt", "f4"),
    ("alt", "tab"),
    ("ctrl", "alt", "delete"),
    ("ctrl", "alt", "esc"),
    ("ctrl", "shift", "esc"),
    ("ctrl", "c"),
    ("ctrl", "v"),
    ("ctrl", "x"),
}


def windows_process_path(window: Any) -> str:
    """Resolve a Win32 window's process without shell commands or third-party code."""
    import ctypes
    from ctypes import wintypes

    hwnd = int(getattr(window, "_hWnd", 0))
    if hwnd <= 0:
        raise PolicyDenied("Desktop window has no valid Win32 handle")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    process_id = wintypes.DWORD()
    if not kernel32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id)):
        raise PolicyDenied("Desktop window process could not be resolved")
    handle = kernel32.OpenProcess(0x1000, False, process_id.value)
    if not handle:
        raise PolicyDenied("Desktop window process access was denied")
    try:
        size = wintypes.DWORD(32_768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise PolicyDenied("Desktop executable path could not be resolved")
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


class DesktopService:
    def __init__(
        self,
        settings: Settings,
        *,
        driver: Any | None = None,
        platform_name: str | None = None,
        process_resolver: Callable[[Any], str] = windows_process_path,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self._injected_driver = driver
        self.platform_name = platform_name or os.name
        self.process_resolver = process_resolver
        self.sleep = sleep

    def _driver(self) -> Any:
        if not self.settings.desktop_enabled:
            raise PolicyDenied("Desktop control is disabled; enable it explicitly")
        if not self.settings.desktop_allowed_applications:
            raise PolicyDenied("Desktop application allowlist is empty")
        if self._injected_driver is None and self.platform_name != "nt":
            raise UnavailableError("Desktop mouse/keyboard control is currently Windows-only")
        try:
            driver = self._injected_driver or importlib.import_module("pyautogui")
        except ImportError as exc:
            raise UnavailableError("Install UAF's desktop extra to enable mouse/keyboard control") from exc
        # These cannot be disabled through configuration or a task payload.
        driver.FAILSAFE = True
        driver.PAUSE = 0.15
        return driver

    @staticmethod
    def _window_handle(window: Any) -> int:
        return int(getattr(window, "_hWnd", 0))

    def _process_name(self, window: Any) -> str:
        return ntpath.basename(self.process_resolver(window)).lower()

    def _bind_window(self, driver: Any, application: str, title: str) -> Any:
        if application not in self.settings.desktop_allowed_applications:
            raise PolicyDenied("Desktop executable is not allowlisted")
        if not isinstance(title, str) or not 1 <= len(title) <= 300:
            raise ValidationError("Desktop window title must be 1–300 characters")
        try:
            windows = list(driver.getAllWindows())[:64]
        except Exception as exc:
            raise UnavailableError("Desktop windows could not be enumerated") from exc
        matches = []
        for window in windows:
            if self._window_matches(window, application, title):
                matches.append(window)
        if len(matches) != 1:
            raise PolicyDenied("Desktop target must resolve to exactly one matching window")
        target = matches[0]
        try:
            target.activate()
            self.sleep(0.2)
            active = driver.getActiveWindow()
            if (
                active is None
                or self._window_handle(active) != self._window_handle(target)
                or self._process_name(active) != application
            ):
                raise PolicyDenied("Desktop target did not retain active focus")
        except PolicyDenied:
            raise
        except Exception as exc:
            raise UnavailableError("Desktop target window could not be activated") from exc
        return target

    def _window_matches(self, window: Any, application: str, title: str) -> bool:
        try:
            return getattr(window, "title", "") == title and self._process_name(window) == application
        except Exception:
            # Unreadable windows are simply not eligible targets.
            return False

    @staticmethod
    def _assert_focus(driver: Any, target: Any, application: str, resolver: Any) -> None:
        active = driver.getActiveWindow()
        if (
            active is None
            or int(getattr(active, "_hWnd", 0)) != int(getattr(target, "_hWnd", 0))
            or ntpath.basename(resolver(active)).lower() != application
        ):
            raise PolicyDenied("Desktop focus changed; batch stopped before the next action")

    @staticmethod
    def _point(action: dict[str, Any], width: int, height: int) -> tuple[int, int]:
        x, y = action.get("x"), action.get("y")
        if (
            not isinstance(x, int)
            or isinstance(x, bool)
            or not isinstance(y, int)
            or isinstance(y, bool)
            or not 0 <= x < width
            or not 0 <= y < height
        ):
            raise ValidationError("Desktop coordinates must be inside the current screen")
        return x, y

    def _validate_actions(self, driver: Any, actions: Any) -> list[dict[str, Any]]:
        if not isinstance(actions, list) or not 1 <= len(actions) <= min(
            self.settings.desktop_max_actions_per_batch, 20
        ):
            raise ValidationError("Desktop action batch exceeds its configured bound")
        size = driver.size()
        width, height = (int(size.width), int(size.height)) if hasattr(size, "width") else map(int, size)
        total_characters = 0
        total_wait = 0
        for action in actions:
            if not isinstance(action, dict):
                raise ValidationError("Every desktop action must be an object")
            kind = action.get("kind")
            if kind in {"move", "click"}:
                self._point(action, width, height)
            if kind == "click":
                if action.get("button", "left") not in {"left", "right", "middle"}:
                    raise ValidationError("Desktop mouse button is invalid")
                clicks = action.get("clicks", 1)
                if not isinstance(clicks, int) or isinstance(clicks, bool) or clicks not in {1, 2}:
                    raise ValidationError("Desktop click count must be 1 or 2")
            elif kind == "move":
                pass
            elif kind == "type":
                text = action.get("text")
                if (
                    not isinstance(text, str)
                    or not text
                    or len(text) > 1_000
                    or any(not 32 <= ord(character) <= 126 for character in text)
                ):
                    raise ValidationError("Desktop typing accepts non-empty printable ASCII only")
                reject_secret_data(text, label="desktop text")
                total_characters += len(text)
            elif kind == "press":
                if action.get("key") not in _PRESS_KEYS:
                    raise ValidationError("Desktop key is not allowlisted")
            elif kind == "hotkey":
                keys = action.get("keys")
                if (
                    not isinstance(keys, list)
                    or not 2 <= len(keys) <= 3
                    or any(not isinstance(key, str) for key in keys)
                    or any(
                        key not in _MODIFIERS
                        and key not in _PRESS_KEYS
                        and not (len(key) == 1 and key.isascii() and key.isalnum())
                        for key in keys
                    )
                    or not any(key in _MODIFIERS for key in keys)
                    or len(set(keys)) != len(keys)
                ):
                    raise ValidationError("Desktop hotkey is invalid")
                # Compare order-insensitively against denied combinations.
                if tuple(sorted(keys)) in {tuple(sorted(item)) for item in _DENIED_HOTKEYS}:
                    raise PolicyDenied("Desktop clipboard/system/focus hotkeys are forbidden")
            elif kind == "scroll":
                clicks = action.get("clicks")
                if (
                    not isinstance(clicks, int)
                    or isinstance(clicks, bool)
                    or not -10 <= clicks <= 10
                    or clicks == 0
                ):
                    raise ValidationError("Desktop scroll must be between -10 and 10, excluding zero")
            elif kind == "wait":
                milliseconds = action.get("milliseconds")
                if (
                    not isinstance(milliseconds, int)
                    or isinstance(milliseconds, bool)
                    or not 50 <= milliseconds <= 2_000
                ):
                    raise ValidationError("Desktop wait must be between 50 and 2,000 ms")
                total_wait += milliseconds
            else:
                raise ValidationError(f"Unsupported desktop action: {kind}")
        if total_characters > 1_000 or total_wait > 5_000:
            raise ValidationError("Desktop batch text/wait budget exceeded")
        return actions

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        driver = self._driver()
        application = payload.get("application")
        title = payload.get("window_title")
        actions = self._validate_actions(driver, payload.get("actions"))
        target = self._bind_window(driver, application, title)
        completed = 0
        attempted = 0
        try:
            for action in actions:
                self._assert_focus(driver, target, application, self.process_resolver)
                kind = action["kind"]
                attempted += 1
                if kind == "move":
                    driver.moveTo(action["x"], action["y"], duration=0.1)
                elif kind == "click":
                    driver.click(
                        x=action["x"],
                        y=action["y"],
                        clicks=action.get("clicks", 1),
                        button=action.get("button", "left"),
                    )
                elif kind == "type":
                    driver.write(action["text"], interval=0.02)
                elif kind == "press":
                    driver.press(action["key"])
                elif kind == "hotkey":
                    driver.hotkey(*action["keys"])
                elif kind == "scroll":
                    driver.scroll(action["clicks"])
                elif kind == "wait":
                    self.sleep(action["milliseconds"] / 1_000)
                completed += 1
        except Exception as exc:
            if attempted:
                raise SideEffectError(
                    f"Desktop batch stopped after {completed} completed and {attempted} attempted "
                    "actions; inspect the window and reconcile before retrying",
                    uncertain=True,
                ) from exc
            raise
        return {
            "application": application,
            "window_title": title,
            "executed_actions": completed,
            "postcondition": completed == len(actions),
        }


def desktop_tool(service: DesktopService) -> Any:
    class DesktopExecute:
        def metadata(self) -> ToolMetadata:
            action_schema = {
                "type": "object",
                "required": ["kind"],
                "additionalProperties": False,
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["move", "click", "type", "press", "hotkey", "scroll", "wait"],
                    },
                    "x": {"type": "integer", "minimum": 0, "maximum": 100_000},
                    "y": {"type": "integer", "minimum": 0, "maximum": 100_000},
                    "button": {"type": "string", "enum": ["left", "right", "middle"]},
                    "clicks": {"type": "integer", "minimum": -10, "maximum": 10},
                    "text": {"type": "string", "minLength": 1, "maxLength": 1_000},
                    "key": {"type": "string", "maxLength": 20},
                    "keys": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 3,
                        "items": {"type": "string", "maxLength": 20},
                    },
                    "milliseconds": {"type": "integer", "minimum": 50, "maximum": 2_000},
                },
            }
            return ToolMetadata(
                "desktop.execute",
                "1",
                "Execute an exact approved mouse/keyboard batch in one allowlisted Windows window",
                {
                    "type": "object",
                    "required": ["application", "window_title", "actions"],
                    "additionalProperties": False,
                    "properties": {
                        "application": {"type": "string", "minLength": 5, "maxLength": 260},
                        "window_title": {"type": "string", "minLength": 1, "maxLength": 300},
                        "actions": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 20,
                            "items": action_schema,
                        },
                    },
                },
                {"type": "object"},
                RiskTier.R3,
                frozenset({"worker"}),
                timeout_seconds=30,
                idempotent=False,
            )

        def execute(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
            return ToolResult(
                output=service.execute(payload),
                evidence={"fail_safe": True, "blind_retry": False},
            )

    return DesktopExecute()
