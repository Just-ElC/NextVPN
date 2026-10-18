"""
Everything that is not drawing.

Nothing in this package imports GTK, so the rules that decide what the
application believes and does can be tested without a display. The two
modules that touch the desktop (system_proxy and the GSettings half of it)
import GIO lazily and only when they are actually asked to change something.
"""
