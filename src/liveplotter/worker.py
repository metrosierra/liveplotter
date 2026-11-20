#!/usr/bin/env python3
"""
Background polling thread used by every live-plot window.

This module runs **inside the plotting subprocess** (see ``liveplot.py``).
Each window owns exactly one :class:`__WorkerBee__`. The bee polls a data
function at a fixed interval and hands the result to the GUI thread through a
Qt signal.

Why a QThread plus a signal instead of updating the plot directly?
    Qt widgets may only be touched from the thread that owns the
    ``QApplication`` (the GUI thread). The data function here pulls from a
    ``multiprocess.Queue``. Doing that pull in a worker thread keeps the GUI
    thread free. A signal emitted from a ``QThread`` to a slot on a
    GUI-thread object is delivered as a *queued* connection, i.e. the slot
    runs later in the GUI thread, which makes the hand-over thread-safe.

Note on delivery timing
    Queued signals are only dispatched when the GUI thread processes its
    event queue. In this package that happens in
    ``__LivePlotProcess__.main_loop`` via ``app.processEvents()`` once per
    ``clock`` interval. So screen updates happen at most once per ``clock``,
    even if ``refresh_interval`` is shorter.
"""

from pyqtgraph.Qt import QtCore
import numpy as np
import time


class __WorkerBee__(QtCore.QThread):
    """
    QThread that repeatedly fetches data and emits it to its window.

    The thread runs until its window is closed (hidden), then emits a
    one-shot "self destruct" signal so the window can clean itself up.

    Parameters
    ----------
    data_func : callable
        Zero-argument callable returning a ``numpy.ndarray`` to plot. Inside
        this package it is ``partial(__LivePlotProcess__.__internal_data_func__, key)``,
        which pops one data snapshot from the inter-process data queue and
        returns this window's entry, or an empty array if none is available.
    isHidden_toggle : callable
        Zero-argument callable returning ``True`` once the window has been
        closed by the user. Polled once per loop iteration.
    refresh_interval : float
        Seconds to sleep between two consecutive ``data_func`` calls.

    Signals
    -------
    signal1 : Signal(numpy.ndarray)
        Emitted with each newly fetched data array. Connected to the
        window's ``update`` slot.
    signal2 : Signal(bool)
        Emitted once with ``True`` when the loop ends. Connected to the
        window's ``self_destruct`` slot.
    """

    # Class-level Signal objects are required by Qt: signals must be declared
    # on the class, not created in __init__. ``QtCore.Signal`` is pyqtgraph's
    # binding-agnostic alias (pyqtSignal on PyQt5/6, Signal on PySide6).
    signal1 = QtCore.Signal(np.ndarray)
    signal2 = QtCore.Signal(bool)
    # signal is a pyqtSignal object that emits a numpy array

    def __init__(self, data_func, isHidden_toggle, refresh_interval):
        super().__init__()

        # Store callables rather than the window itself: the bee only needs
        # to know "is my window still open?" and "give me new data".
        self.isHidden = isHidden_toggle
        self.data_func = data_func
        self.refresh_interval = refresh_interval

    def run(self):
        """
        Thread body: poll ``data_func`` and emit until the window is hidden.

        Called by Qt in the new thread when ``start()`` is invoked; do not
        call directly.
        """

        # Closing a top-level Qt window hides it rather than deleting it, so
        # ``isHidden()`` turning True is used as the "user closed the window"
        # event.
        while not self.isHidden():
            data = self.data_func()
            # Crosses to the GUI thread as a queued connection (see module
            # docstring); this thread never touches widgets directly.
            self.signal1.emit(data)
            time.sleep(self.refresh_interval)
        # run() is overridden, so no QThread event loop is running here and
        # quit() is effectively a no-op; returning from run() is what ends
        # the thread.
        self.quit()
        print("WorkerBee vi saluta")
        # Ask the owning window to close/clean up from the GUI thread.
        self.signal2.emit(True)
