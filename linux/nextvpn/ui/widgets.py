"""
The two hand-drawn pieces of the interface: the connect control and the
throughput graph. Everything else is stock libadwaita.
"""

from __future__ import annotations

import math

import cairo
from gi.repository import Adw, Gtk

from ..core.i18n import _
from ..core.status import TunnelState

# Brand colours, per theme. Identical to the Windows build's.
BRAND = {
    False: {"primary": (0x0F, 0xA9, 0x7B), "secondary": (0x0B, 0x8A, 0x63), "up": (0x2F, 0x7F, 0xD1)},
    True: {"primary": (0x2E, 0xE6, 0xA8), "secondary": (0x12, 0xB8, 0x86), "up": (0x5A, 0xB9, 0xFF)},
}


def brand(name: str) -> tuple[float, float, float]:
    r, g, b = BRAND[Adw.StyleManager.get_default().get_dark()][name]
    return r / 255, g / 255, b / 255


def foreground(widget: Gtk.Widget) -> tuple[float, float, float]:
    if hasattr(widget, "get_color"):           # GTK 4.10+
        c = widget.get_color()
    else:                                      # pragma: no cover - older GTK
        c = widget.get_style_context().get_color()
    return c.red, c.green, c.blue


def animations_enabled() -> bool:
    settings = Gtk.Settings.get_default()
    return settings is None or settings.props.gtk_enable_animations


class ConnectDial(Gtk.Overlay):
    """
    Concentric circles on one centre: a static track, the rotating arc and the
    two ripples that run while a tunnel is being established, the glow, and the
    button itself on top.

    The button is a real Gtk.Button, so focus, keyboard activation, tooltips and
    screen readers behave like any other button. Motion runs off the frame
    clock only while the engine is busy; once connected the control is static,
    because a permanently animating window costs CPU and battery for no
    information.
    """

    SIZE = 176
    TRACK_RADIUS = 74
    GLOW_RADIUS = 70

    #: Glow strength per state. Idle is a hint, connected is a statement.
    GLOW = {"idle": 0.30, "busy": 0.55, "connected": 1.0}

    def __init__(self):
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)

        self.area = Gtk.DrawingArea(content_width=self.SIZE, content_height=self.SIZE)
        self.area.set_draw_func(self._draw)
        self.set_child(self.area)

        self.button = Gtk.Button(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.button.add_css_class("connect-button")
        icon = Gtk.Image(icon_name="system-shutdown-symbolic", pixel_size=34)
        self.button.set_child(icon)
        self.add_overlay(self.button)

        self._state = TunnelState.DISCONNECTED
        self._glow = self.GLOW["idle"]
        self._busy_since: int | None = None
        self._frame_time = 0
        self._tick_id = 0

        target = Adw.CallbackAnimationTarget.new(self._on_glow)
        self._glow_anim = Adw.TimedAnimation.new(self, self._glow, self._glow, 320, target)
        self._glow_anim.set_easing(Adw.Easing.EASE_OUT_CUBIC)

        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self.area.queue_draw())
        self.connect("unrealize", lambda *_: self._stop_busy())

    # -------------------------------------------------------------- state

    def set_state(self, state: TunnelState, label: str, sensitive: bool) -> None:
        self.button.set_tooltip_text(label)
        self.button.update_property([Gtk.AccessibleProperty.LABEL], [label])
        self.button.set_sensitive(sensitive)

        if state == self._state:
            return
        self._state = state

        for name in ("connected", "busy", "idle", "faulted"):
            self.button.remove_css_class(name)

        if state in (TunnelState.CONNECTING, TunnelState.DISCONNECTING):
            self.button.add_css_class("busy")
            self._start_busy()
            self._fade_glow(self.GLOW["busy"])
        elif state == TunnelState.CONNECTED:
            self.button.add_css_class("connected")
            self._stop_busy()
            self._fade_glow(self.GLOW["connected"])
        else:
            self.button.add_css_class("faulted" if state == TunnelState.FAULTED else "idle")
            self._stop_busy()
            self._fade_glow(self.GLOW["idle"])

    def _fade_glow(self, target: float) -> None:
        self._glow_anim.pause()
        self._glow_anim.set_value_from(self._glow)
        self._glow_anim.set_value_to(target)
        self._glow_anim.play()

    def _on_glow(self, value: float) -> None:
        self._glow = value
        self.area.queue_draw()

    def _start_busy(self) -> None:
        self._busy_since = None
        if not self._tick_id:
            self._tick_id = self.area.add_tick_callback(self._on_tick)

    def _stop_busy(self) -> None:
        if self._tick_id:
            self.area.remove_tick_callback(self._tick_id)
            self._tick_id = 0
        self._busy_since = None
        self.area.queue_draw()

    def _on_tick(self, widget, clock) -> bool:
        now = clock.get_frame_time()
        if self._busy_since is None:
            self._busy_since = now
        self._frame_time = now
        widget.queue_draw()
        return True

    # ------------------------------------------------------------ drawing

    def _draw(self, area, cr, width, height) -> None:
        cx, cy = width / 2, height / 2
        primary, secondary = brand("primary"), brand("secondary")
        fg = foreground(area)

        # Glow, under everything.
        if self._glow > 0.01:
            glow = cairo.RadialGradient(cx, cy, 0, cx, cy, self.GLOW_RADIUS)
            glow.add_color_stop_rgba(0.0, *primary, 0.50 * self._glow)
            glow.add_color_stop_rgba(0.55, *primary, 0.25 * self._glow)
            glow.add_color_stop_rgba(1.0, *primary, 0.0)
            cr.set_source(glow)
            cr.arc(cx, cy, self.GLOW_RADIUS, 0, 2 * math.pi)
            cr.fill()

        # Static track.
        cr.set_line_width(1)
        cr.set_source_rgba(*fg, 0.14)
        cr.arc(cx, cy, self.TRACK_RADIUS, 0, 2 * math.pi)
        cr.stroke()

        if self._busy_since is None:
            return

        elapsed = (self._frame_time - self._busy_since) / 1_000_000
        moving = animations_enabled()

        # Two ripples, half a cycle apart, so the pulse reads as continuous.
        if moving:
            for offset in (0.0, 1.2):
                t = ((elapsed - offset) % 2.4) / 2.4 if elapsed >= offset else None
                if t is None:
                    continue
                eased = 1 - (1 - t) ** 3
                scale = 0.62 + (1.10 - 0.62) * eased
                alpha = (t / 0.18) * 0.62 if t < 0.18 else 0.62 * (1 - (t - 0.18) / 0.82)
                cr.set_line_width(2)
                cr.set_source_rgba(*primary, max(0.0, alpha))
                cr.arc(cx, cy, self.TRACK_RADIUS * scale, 0, 2 * math.pi)
                cr.stroke()

        # A single arc, 28% of the circumference, one turn every 1.9 s.
        angle = (elapsed / 1.9) * 2 * math.pi if moving else 0.0
        start = angle - math.pi / 2
        cr.set_line_width(3)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        gradient = cairo.LinearGradient(cx - self.TRACK_RADIUS, cy - self.TRACK_RADIUS,
                                        cx + self.TRACK_RADIUS, cy + self.TRACK_RADIUS)
        gradient.add_color_stop_rgb(0, *primary)
        gradient.add_color_stop_rgb(1, *secondary)
        cr.set_source(gradient)
        cr.arc(cx, cy, self.TRACK_RADIUS, start, start + 0.28 * 2 * math.pi)
        cr.stroke()


class ThroughputGraph(Gtk.Overlay):
    """
    Recent throughput as a filled download area with an upload line over it.
    Both series share one scale, so their relative size stays honest; the scale
    is the peak of the visible window.
    """

    def __init__(self):
        super().__init__(vexpand=True, hexpand=True)
        self.area = Gtk.DrawingArea(vexpand=True, hexpand=True)
        self.area.set_size_request(-1, 110)
        self.area.set_draw_func(self._draw)
        self.set_child(self.area)

        self.empty = Gtk.Label(label=_("No traffic yet"), halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.empty.add_css_class("dim-label")
        self.empty.add_css_class("caption")
        self.add_overlay(self.empty)

        self._samples: list[tuple[float, float]] = []
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self.area.queue_draw())

    def set_samples(self, samples) -> None:
        self._samples = list(samples)
        self.empty.set_visible(len(self._samples) < 2)
        self.area.queue_draw()

    def _draw(self, area, cr, w, h) -> None:
        samples = self._samples
        if w < 8 or h < 8 or len(samples) < 2:
            return

        down, up = brand("primary"), brand("up")
        peak = max(max(d, u) for d, u in samples)
        # Headroom so the peak never touches the top edge.
        peak = 1.0 if peak <= 0 else peak * 1.15
        step = w / (len(samples) - 1)

        def y(value: float) -> float:
            return h - (value / peak) * (h - 2) - 1

        # Download area.
        cr.move_to(0, h)
        for i, (d, _u) in enumerate(samples):
            cr.line_to(i * step, y(d))
        cr.line_to(w, h)
        cr.close_path()
        fill = cairo.LinearGradient(0, 0, 0, h)
        fill.add_color_stop_rgba(0, *down, 96 / 255)
        fill.add_color_stop_rgba(1, *down, 8 / 255)
        cr.set_source(fill)
        cr.fill()

        cr.set_line_width(1.5)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)

        # Upload line under the download line, so the main series stays on top.
        for i, (_d, u) in enumerate(samples):
            (cr.move_to if i == 0 else cr.line_to)(i * step, y(u))
        cr.set_source_rgba(*up, 0.9)
        cr.stroke()

        for i, (d, _u) in enumerate(samples):
            (cr.move_to if i == 0 else cr.line_to)(i * step, y(d))
        cr.set_source_rgb(*down)
        cr.stroke()


def code_badge(size: str = "large") -> tuple[Gtk.Widget, Gtk.Label, Gtk.Image]:
    """A round badge showing a country code, or a pin for "best performance"."""
    badge = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    badge.add_css_class("code-badge")
    if size == "small":
        badge.add_css_class("small")
    # The contents expand to centre themselves inside the circle; set explicitly
    # here, so that expansion stops at the badge instead of stretching whatever
    # row or card the badge is placed in.
    badge.set_hexpand(False)
    badge.set_vexpand(False)
    stack_label = Gtk.Label(hexpand=True, halign=Gtk.Align.CENTER)
    stack_label.add_css_class("code-badge-label")
    image = Gtk.Image(icon_name="find-location-symbolic", hexpand=True, halign=Gtk.Align.CENTER,
                      pixel_size=19 if size != "small" else 15)
    badge.append(stack_label)
    badge.append(image)
    return badge, stack_label, image


def set_badge(label: Gtk.Label, image: Gtk.Image, code: str) -> None:
    label.set_label(code)
    label.set_visible(bool(code))
    image.set_visible(not code)

