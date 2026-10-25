"""
How GTK draws the window, for the Activity log and Settings → About.

Stuttering animations almost always mean drawing without the graphics card:
GTK falls back to its software renderer, or Mesa to its software rasteriser,
when the graphics driver cannot be loaded. Neither is the app's to fix, but
both are worth saying out loud, because the cause is otherwise invisible.
"""

from __future__ import annotations

import ctypes

GL_VENDOR = 0x1F00
GL_RENDERER = 0x1F01

#: Mesa's and others' software rasterisers, as they name themselves.
SOFTWARE_DRIVERS = ("llvmpipe", "softpipe", "swrast", "lavapipe", "software rasterizer")


def gl_driver(display) -> str | None:
    """
    The OpenGL driver GTK gets on this display, e.g. "AMD Radeon RX 6600 (radeonsi)"
    or "llvmpipe (LLVM 19.1.7, 256 bits)". None when there is no OpenGL at all.
    Read through libepoxy, which GTK has already loaded.
    """
    try:
        context = display.create_gl_context()
        context.realize()
        context.make_current()
    except Exception:  # noqa: BLE001 - no GL is an answer, not an error
        return None
    try:
        lib = ctypes.CDLL("libepoxy.so.0")
        pointer = ctypes.c_void_p.in_dll(lib, "epoxy_glGetString")
        get_string = ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_uint)(pointer.value)
        renderer = get_string(GL_RENDERER)
        return renderer.decode("utf-8", "replace") if renderer else None
    except (OSError, ValueError, AttributeError):
        return None
    finally:
        try:
            from gi.repository import Gdk
            Gdk.GLContext.clear_current()
        except Exception:  # noqa: BLE001
            pass


def is_software(renderer: str | None, driver: str | None) -> bool:
    if renderer == "GskCairoRenderer":
        return True
    return bool(driver) and any(name in driver.lower() for name in SOFTWARE_DRIVERS)
