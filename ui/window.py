from __future__ import annotations

import sys
from tkinter import Tk

GCLP_HBRBACKGROUND = -10


def paint_window_background(root: Tk, color: str) -> None:
    # windows fills newly exposed window area with the window class brush before the app repaints.
    # tk registers no brush, so maximizing showed black boxes until every ctk widget had redrawn
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    try:
        red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        gdi32.CreateSolidBrush.restype = ctypes.c_void_p
        brush = gdi32.CreateSolidBrush(red | (green << 8) | (blue << 16))

        # 32 bit windows only exports the non Ptr variant
        set_class_long = getattr(user32, "SetClassLongPtrW", None) or user32.SetClassLongW
        set_class_long.restype = ctypes.c_void_p
        set_class_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

        root.update_idletasks()
        for hwnd in {int(root.wm_frame(), 16), root.winfo_id()}:
            set_class_long(hwnd, GCLP_HBRBACKGROUND, brush)
    except (AttributeError, OSError, ValueError):
        pass
