#!/usr/bin/env python3
"""
Process and thread plumbing for liveplotter, plus the user-facing ``LivePlotAgent``.

General threadsafe subprocessed live plotter using pyqtgraph,
brought over by Mingsong WU circa 2023.
This version is more performant but might take up more CPU.

Architecture
------------
Two processes communicate through three ``multiprocess.Queue`` objects::

    MAIN (user) PROCESS                          PLOTTING SUBPROCESS
    -------------------                          -------------------
    LivePlotAgent                                __Qapp_liveplot__
     |                                            -> QApplication
     |  one "FetchData" thread per plot:          -> __LivePlotProcess__.main_loop
     |    self.data[key] = data_func()                 (polls task_q, publishes
     |                                                  window states, pumps Qt)
     |  "Data broadcast" thread:                  one window per plot
     |    data_q.put(self.data) ----- data_q ---->   (windows.py), each with a
     |                                               __WorkerBee__ thread that
     |  new_liveplot(...) -------- task_q ------>    pulls from data_q
     |
     |  "isalive state check" thread:
     |    self.states <------------ state_q -----  {key: window_is_open}

* ``task_q``: commands ``[command, key, plot_kwargs]``, e.g.
  ``["new_live_plot", "0", {...}]`` or ``["break", None, None]``.
* ``data_q``: snapshots of the agent's whole ``{key: ndarray}`` dict. Bounded
  to 50 entries so the producer blocks instead of growing memory without
  limit.
* ``state_q``: ``{key: bool}`` dicts telling the main process which windows
  are still open.

Why a subprocess?
    Qt wants its ``QApplication`` in the main thread of a process. Running it
    in a separate process keeps the GUI responsive regardless of what the
    user's script, IDE (Spyder, Jupyter, plain terminal) or acquisition code
    is doing, and keeps the user's process free of Qt event-loop
    requirements.

Why ``multiprocess`` rather than ``multiprocessing``?
    ``multiprocess`` serialises with ``dill`` instead of ``pickle``, which can
    handle more object types (lambdas, closures, interactively defined
    functions) when objects must be sent between processes.

Why do data functions stay in the main process?
    The user's ``data_func`` often wraps instrument drivers (DLL handles,
    open device sessions) that cannot be pickled. Only the returned numpy
    arrays cross the process boundary; the subprocess sees a stand-in data
    function (``__internal_data_func__``) that reads from ``data_q``.
"""

import numpy as np
from pyqtgraph.Qt import QtWidgets
import time
import threading

from functools import partial
import multiprocess as mp, queue
from queue import Empty
import operator

# Relative import: required now that the module lives inside the
# ``liveplotter`` package.
from .windows import __LivePlotterWindow__, __LiveMultiWindow__, __LiveHeatMap__


###################################################################################
def __Qapp_liveplot__(task_q, state_q, data_q, clock, verbose):
    """
    Entry point of the plotting subprocess.

    Creates the process's single ``QApplication`` and then builds a
    :class:`__LivePlotProcess__`, whose constructor runs the main loop and
    blocks until a ``"break"`` command arrives on ``task_q``.

    Parameters
    ----------
    task_q, state_q, data_q : multiprocess.Queue
        The three queues described in the module docstring.
    clock : float
        Main-loop period in seconds.
    verbose : bool
        Print diagnostic messages.
    """
    app = QtWidgets.QApplication([])
    try:
        liveplot_instance = __LivePlotProcess__(
            task_q, state_q, data_q, clock, app, verbose
        )
    except Exception as e:
        raise e
    # return liveplot_instance
###################################################################################


class __LivePlotProcess__:
    """
    Window manager and event pump running inside the plotting subprocess.

    Constructing the object starts :meth:`main_loop` immediately and does not
    return until the loop ends.

    Parameters
    ----------
    task_q, state_q, data_q : multiprocess.Queue
        The three queues described in the module docstring.
    clock : float
        Main-loop period in seconds. Also sets the default window refresh
        interval (``5 * clock``) when a plot is created with a falsy
        ``refresh_interval``.
    app : QtWidgets.QApplication
        The application object of this process.
    verbose : bool
        Print diagnostic messages.

    Attributes
    ----------
    windows : dict[str, __LiveWindowLike__]
        Open (and closed) windows by key. Closed windows stay in the dict.
    window_states : dict[str, bool]
        ``{key: window_is_open}``, sent to the main process via ``state_q``.
    """

    def __init__(self, task_q, state_q, data_q, clock, app, verbose):
        self.app = app
        self.verbose = verbose
        self.windows = {}
        self.window_no = 0
        self.clock_interval = clock
        self.task_q = task_q
        self.state_q = state_q
        self.data_q = data_q
        self.isalive = True
        self.window_states = {}
        self.main_loop()

    def main_loop(self):
        """
        Run the subprocess event loop until a ``"break"`` command is received.

        Each iteration (period ``clock``):

        1. If at least one window exists and the previous state message has
           been consumed (``state_q`` empty), publish ``{key: is_open}`` for
           all windows. Checking for emptiness first keeps at most about one
           state message in flight, so stale states do not pile up.
        2. Handle at most one command from ``task_q``.
        3. Sleep ``clock`` seconds, then let Qt process pending events
           (repaints, mouse interaction, and the queued data signals from the
           worker threads).

        Notes
        -----
        A manual ``processEvents()`` loop is used instead of ``app.exec()``
        so that queue polling and Qt event handling share one thread with no
        extra synchronisation. The consequence is that the GUI reacts to
        input and redraws at most once per ``clock``.
        """

        while self.isalive:
            if len(self.windows) > 0 and self.state_q.empty():
                for key in self.windows:
                    self.window_states[str(key)] = not self.windows[str(key)].isHidden()
                self.state_q.put(self.window_states)

            if self.task_q.empty():
                pass
            else:
                new_task = self.task_q.get()
                if new_task[0] == "new_live_plot":
                    ### task[1] should be window identifier key (any str)
                    ### task[2] should be plotter kwargs
                    if self.verbose:
                        print("command received!!")
                        print(new_task)
                    self.new_window(new_task[1], **new_task[2])

                elif new_task[0] == "new_multi_plot":
                    if self.verbose:
                        print("command received!!")
                        print(new_task)
                    self.new_multiwindow(new_task[1], **new_task[2])

                elif new_task[0] == "new_heatmap":
                    if self.verbose:
                        print("command received!!")
                        print(new_task)
                    self.new_liveplot_heatmap(new_task[1], **new_task[2])

                elif new_task[0] == "break":
                    self.isalive = False
                    if self.verbose:
                        print("stopping process loop")

            time.sleep(self.clock_interval)

            self.app.processEvents()

        if self.verbose:
            print("Exiting LivePlotProcess")
        self.__exit__(None, None, None)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.verbose:
            print("LivePlotProcess exiting ciao bella ciao")
        return

    def __internal_data_func__(self, key):
        """
        Stand-in data function given to each window's worker thread.

        Pops **one** snapshot from ``data_q`` and returns the entry for
        ``key``. All windows share ``data_q``, and each snapshot holds every
        window's data, so whichever worker pops a snapshot uses its own entry
        and ignores the rest.

        Parameters
        ----------
        key : str
            Window identifier.

        Returns
        -------
        numpy.ndarray
            The window's data, or ``np.array([])`` (shape ``(0,)``, skipped by
            the window) if the queue was empty, the key was missing, or any
            other error occurred (the error is printed).
        """
        try:
            dict = self.data_q.get_nowait()
            return dict[str(key)]
        except Empty:
            return np.array([])
        except KeyError:
            if self.verbose:
                print("Keyerror, buffering")
            return np.array([])
        except Exception as e:
            print(e)
            return np.array([])

    def new_window(self, key, **plot_kwargs):
        """
        Create a single-axes, multi-trace window (``__LivePlotterWindow__``).

        Parameters
        ----------
        key : str
            Window identifier chosen by the agent.
        **plot_kwargs
            Keyword arguments of ``__LiveWindowLike__`` except ``data_func``
            and ``verbose``. ``refresh_interval`` must be present; if it is
            falsy (``None``/``0``) it is replaced by ``5 * clock``.
        """
        ### we can pass a self function because it has no direct
        ### link to the customer package which houses whatever
        ### incompatible dll that cannot be pickled via Process
        refresh_interval = plot_kwargs['refresh_interval']
        if not refresh_interval:
            plot_kwargs['refresh_interval'] = self.clock_interval * 5

        if self.verbose:
            print(f"Refreshing plot at {refresh_interval}s")

        self.windows[str(key)] = __LivePlotterWindow__(
            data_func = partial(self.__internal_data_func__, str(key)),
            **plot_kwargs,
            verbose = self.verbose,
        )
        self.window_no += 1
        return self

    def new_multiwindow(self, key, **plot_kwargs):
        """
        Create a grid-of-subplots window (``__LiveMultiWindow__``).

        Same parameters and ``refresh_interval`` handling as :meth:`new_window`.
        """
        ### we can pass a self function because it has no direct
        ### link to the customer package which houses whatever
        ### incompatible dll that cannot be pickled via Process
        refresh_interval = plot_kwargs['refresh_interval']
        if not refresh_interval:
            plot_kwargs['refresh_interval'] = self.clock_interval * 5

        if self.verbose:
            print(f"Refreshing plot at {refresh_interval}s")

        self.windows[str(key)] = __LiveMultiWindow__(
            data_func = partial(self.__internal_data_func__, str(key)),
            **plot_kwargs,
            verbose = self.verbose,
        )
        self.window_no += 1
        return self

    def new_liveplot_heatmap(self, key, **plot_kwargs):
        """
        Create a 2D image window (``__LiveHeatMap__``).

        Same parameters and ``refresh_interval`` handling as :meth:`new_window`.
        """
        refresh_interval = plot_kwargs['refresh_interval']
        if not refresh_interval:
            plot_kwargs['refresh_interval'] = self.clock_interval * 5

        if self.verbose:
            print(f"Refreshing plot at {refresh_interval}s")

        self.windows[str(key)] = __LiveHeatMap__(
            data_func = partial(self.__internal_data_func__, str(key)),
            **plot_kwargs,
            verbose = self.verbose,
        )
        self.window_no += 1
        return self


class LivePlotAgent:
    """
    Non-blocking live plotting for any Python script, console or IDE.

    Creating a ``LivePlotAgent`` starts a separate plotting process. Each call
    to :meth:`new_liveplot`, :meth:`new_liveplot_multi` or
    :meth:`new_liveplot_heatmap` opens a window in that process and starts
    a background thread in *your* process that calls your ``data_func``
    every ``clock`` seconds. The latest result is streamed to the window.
    Your script carries on running while the windows update.

    Parameters
    ----------
    clock : float, default 0.1
        Base period in seconds. It sets how often each ``data_func`` is called,
        the plotting process's event-loop period (so the maximum screen
        update rate is ``1 / clock``), and the default ``refresh_interval``
        (``5 * clock``).
    verbose : bool, default False
        Print diagnostic messages from both processes.

    Notes
    -----
    Pyqt does not like to be sub-threaded, but is fine with sub-processing,
    so the Qt application runs in a ``multiprocess.Process`` rather than a
    ``threading.Thread``. (A sub-threaded version worked in Spyder but not
    elsewhere.) This makes the plotter console-agnostic. The agent owns the
    queues used to send commands and data to the plotting subprocess.

    All helper threads and the plotting process are daemons: they stop when
    your main program exits. Keep your script alive (e.g. run your
    acquisition loop, ``input()``, ``time.sleep``) for as long as you want
    the plots to stay up.

    On Windows, where processes are started with ``spawn``, create the agent
    under ``if __name__ == "__main__":``.

    Examples
    --------
    >>> import numpy as np
    >>> from liveplotter import LivePlotAgent
    >>> def read_two_channels():
    ...     return np.random.normal(size=(2, 500))
    >>> agent = LivePlotAgent(clock=0.1)
    >>> agent.new_liveplot(
    ...     data_func=read_two_channels,
    ...     title="Detector", xlabel="sample", ylabel="counts",
    ...     refresh_interval=0.2, no_plots=2, plot_labels=["A", "B"],
    ... )  # doctest: +SKIP
    >>> agent.close()  # doctest: +SKIP
    """

    def __init__(self, clock=0.1, verbose=False):
        self.clock_interval = clock
        self.verbose = verbose
        self.task_q = mp.Queue()
        self.state_q = mp.Queue()
        # Bounded so that the broadcast thread blocks when the plotting side
        # falls behind, instead of buffering snapshots without limit.
        self.data_q = mp.Queue(maxsize=50)  ##need to play with buffer size
        self.process = mp.Process(
            target=__Qapp_liveplot__,
            args=(
                self.task_q,
                self.state_q,
                self.data_q,
                self.clock_interval,
                self.verbose,
            ),
        )
        # Daemon: the plotting process is terminated automatically when the
        # user's main process exits, so no stray windows are left behind.
        self.process.daemon = True
        self.process.start()
        self.window_no = 0
        self.available_window_keys = []
        # {key: latest ndarray}, written by the FetchData threads and read
        # by the broadcast thread.
        self.data = {}
        # {key: window_is_open}, written by __new_plot_prep__ and replaced
        # wholesale by the state-check thread.
        self.states = {}
        self.active = True
        threading.Thread(
            target=self.__transmit_data__, daemon=True, name="Data broadcast thread"
        ).start()
        threading.Thread(
            target=self.__check_states__,
            daemon=True,
            name="Window isalive state check thread",
        ).start()
        if self.verbose:
            print("LivePlotAgent initialised")

    def __enter__(self):
        """Support ``with LivePlotAgent() as agent:``; returns the agent."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Shut down: stop helper loops, ask the subprocess to exit, then terminate it.

        Sequence: stop the broadcast and state-check threads (``active =
        False``), send ``"break"``, wait 1 s for the subprocess to leave
        its loop, drain all queues, and finally ``terminate()`` the process
        in case it has not exited.

        Notes
        -----
        The per-plot FetchData threads are not signalled here; they are
        daemon threads and end when the main program exits.
        """
        self.active = False
        self.task_q.put(["break", None, None])
        if self.verbose:
            print("command sent!")
        time.sleep(1)
        self.__flush_queues__()
        self.process.terminate()
        return self

    def __flush_queues__(self):
        """
        Remove every pending item from the three queues.

        Probable purpose: a ``multiprocess.Queue`` that still holds unread
        data can make interpreter shutdown wait on its feeder thread.
        Draining before ``terminate()`` reduces the chance of that hang.
        """

        def __internal_flush__(self, queue):
            while not queue.empty():
                try:
                    queue.get_nowait()
                except Empty:
                    pass
            return
        if self.verbose:
            print("flushing memory queues")
        # self.task_q.close()
        # self.state_q.close()
        # self.data_q.close()
        while not self.task_q.empty():
            __internal_flush__(self, self.task_q)
        while not self.state_q.empty():
            __internal_flush__(self, self.state_q)
        while not self.data_q.empty():
            __internal_flush__(self, self.data_q)
        return self

    def __fetch_data__(self, data_func, key, kill_func):
        """
        Per-plot polling thread (main process): keep ``self.data[key]`` fresh.

        Phase 1 (first 5 s): call ``data_func`` every ``clock`` seconds
        unconditionally. This grace period covers the time before the
        subprocess has created the window and reported its state; without it
        the thread could see a stale "closed" state and exit immediately.

        Phase 2: while the window is reported open, keep calling
        ``data_func`` every ``clock``. When it is reported closed, call
        ``kill_func`` (if given) once and end the thread.

        Parameters
        ----------
        data_func : callable
            User data function, called with no arguments.
        key : str
            Window identifier.
        kill_func : callable or None
            Called with no arguments when the user closes the window.
        """
        alive = True
        start = time.time()

        while time.time() - start < 5:
            self.data[str(key)] = data_func()
            time.sleep(self.clock_interval)

        while alive:
            try:
                window_isopen = self.states[str(key)]
                if window_isopen:
                    self.data[str(key)] = data_func()
                    time.sleep(self.clock_interval)
                else:
                    if kill_func:
                        kill_func()
                    alive = False
            except KeyError as e:
                # Key not (yet) reported by the subprocess; retry.
                pass

        if self.verbose:
            print("thread exiting!!!!!!!!!!!")
        return

    def __transmit_data__(self):
        """
        Broadcast thread (main process): push data snapshots into ``data_q``.

        While at least one window is open, put a reference to ``self.data``
        on the queue as fast as the queue accepts it. ``data_q`` is bounded
        (50), so ``put`` blocks once the plotting side stops consuming. That
        blocking is what throttles this loop. The dict is pickled later by
        the queue's feeder thread, so a snapshot holds the values at
        pickling time, not at ``put`` time.
        """
        if self.verbose:
            print("starting transmission data thread")
        while self.active:
            if True in self.states.values():
                self.data_q.put(self.data)
            time.sleep(1e-20)

    def __check_states__(self):
        """
        State thread (main process): every 2 s, adopt the latest window states.

        Replaces ``self.states`` with the ``{key: is_open}`` dict from the
        subprocess, clears data of closed windows, and recomputes
        ``available_window_keys`` (keys of closed windows that may be reused).

        Notes
        -----
        ``available_window_keys`` is built by position: entry ``n`` of
        ``self.states`` is labelled ``str(n)``. This relies on keys being
        ``"0", "1", ...`` in insertion order, which is how the agent assigns
        them.
        """
        while self.active:
            if not self.state_q.empty():
                try:
                    states = self.state_q.get()
                    self.states = states
                    self._garbage_collection_()
                    # Boolean-mask the positions 0..n-1 by "window closed"
                    # and turn the surviving positions back into string keys.
                    self.available_window_keys = list(
                        map(
                            str,
                            np.arange(0, len(self.states), 1)[
                                list(map(operator.not_, self.states.values()))
                            ],
                        )
                    )
                except (Empty, KeyError) as e:
                    pass
            time.sleep(2)

    def _garbage_collection_(self):
        """
        Replace the data of newly closed windows with an empty array.

        Frees the memory of the last frame of closed windows and stops them
        being pickled into every snapshot at full size.
        """
        for key in self.states:
            if not self.states[key] and key not in self.available_window_keys:
                if self.verbose:
                    print(f"Cleaning data for key:{key}")
                self.data[key] = np.array([])

    def __new_plot_prep__(self, data_func=None, kill_func=None):
        """
        Choose a window key and start the FetchData thread for a new plot.
        By default we just generate the next integer key.
        Parameters
        ----------
        data_func : callable, optional
            User data function. If ``None``, a dummy function returning
            random data is used.
        kill_func : callable, optional
            Called once when the user closes the window.

        Returns
        -------
        str
            The window key.
        """
        key = str(self.window_no)
        self.window_no += 1

        if self.verbose:
            print(f"Key: {key}")
        ### some dummy data if data func is None
        if not data_func:
            data_func = lambda: np.array(
                [[np.linspace(0, 1, 1000), np.random.rand(1000)]]
            )

        # Seed data and state before the thread starts, so the broadcast
        # thread sees an open window with data right away.
        self.data[key] = data_func()
        self.states[key] = True

        threading.Thread(
            target=self.__fetch_data__,
            args=(
                data_func,
                key,
                kill_func,
            ),
            daemon=True,
            name="FetchData thread for key {}".format(key),
        ).start()
        return key

    def new_liveplot_heatmap(self, data_func=None, kill_func=None, **plot_settings):
        """
        Open a live 2D image (heatmap) window.

        Parameters
        ----------
        data_func : callable
            Zero-argument function returning a 2D ``numpy.ndarray``. With
            pyqtgraph's default axis order, element ``[i, j]`` is drawn at
            x = i, y = j.
        kill_func : callable, optional
            Called once, from a background thread, when the user closes the
            window.
        **plot_settings
            Must include ``title``, ``xlabel``, ``ylabel``,
            ``refresh_interval``, ``no_plots`` and ``plot_labels`` (the last
            two are unused for heatmaps but required; e.g. ``no_plots=1,
            plot_labels=None``). See :meth:`new_liveplot`.

        Returns
        -------
        LivePlotAgent
            ``self``, so calls can be chained.

        Notes
        -----
        The colour scale starts at the fixed range 0-100 and is not
        auto-scaled; drag the colour bar in the window to adjust it.
        """
        key = self.__new_plot_prep__(data_func, kill_func)
        self.task_q.put(["new_heatmap", key, plot_settings])
        if self.verbose:
            print("command sent!")
        return self

    def new_liveplot_multi(self, data_func=None, kill_func=None, **plot_settings):
        """
        Open a window with one subplot per channel (grid, three per row).

        Parameters
        ----------
        data_func : callable
            Zero-argument function returning an array indexable as
            ``data[i]`` for ``i < no_plots``, each a 1D trace, typically
            shape ``(no_plots, n_samples)``.
        kill_func : callable, optional
            Called once, from a background thread, when the user closes the
            window.
        **plot_settings
            Same required keys as :meth:`new_liveplot`.

        Returns
        -------
        LivePlotAgent
            ``self``, so calls can be chained.
        """
        key = self.__new_plot_prep__(data_func, kill_func)
        self.task_q.put(["new_multi_plot", key, plot_settings])
        if self.verbose:
            print("command sent!")
        return self

    def new_liveplot(self, data_func=None, kill_func=None, **plot_settings):
        """
        Open a window with all channels overlaid on one set of axes.

        Parameters
        ----------
        data_func : callable
            Zero-argument function returning an array indexable as
            ``data[i]`` for ``i < no_plots``, each a 1D trace, typically
            shape ``(no_plots, n_samples)``. Trace ``i`` is drawn against
            its sample index. It is called every ``clock`` seconds in a
            background thread of your process, and must return a
            ``numpy.ndarray`` (it is pickled to the plotting process).
        kill_func : callable, optional
            Called once, from a background thread, when the user closes the
            window, e.g. to stop an acquisition.
        **plot_settings
            All of the following keys are required. A missing key raises
            an error inside the plotting process, not here.

            title : str
                Initial plot title. It is replaced by the latest values
                of each trace once data arrives.
            xlabel, ylabel : str
                Axis labels.
            refresh_interval : float or None
                Seconds between screen updates. ``None``/``0`` means
                ``5 * clock``. Values below ``clock`` give no faster updates.
            no_plots : int
                Number of traces.
            plot_labels : list of str or None
                Legend labels, one per trace; ``None`` gives ``1..no_plots``.

        Returns
        -------
        LivePlotAgent
            ``self``, so calls can be chained.
        """
        key = self.__new_plot_prep__(data_func, kill_func)
        self.task_q.put(["new_live_plot", key, plot_settings])
        # self.task_q.put(['dummy', key, plot_settings])
        if self.verbose:
            print("command sent!")
        return self

    def close(self):
        """Shut down the plotting process; equivalent to leaving a ``with`` block."""
        self.__exit__(None, None, None)
        return
