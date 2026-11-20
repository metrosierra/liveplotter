#!/usr/bin/env python3
"""
Window classes that draw the live plots.

This module runs **inside the plotting subprocess** (see ``liveplot.py``).
Each class wraps a ``pyqtgraph.GraphicsLayoutWidget`` and owns one
:class:`~liveplotter.worker.__WorkerBee__` that feeds it data.

Class overview
--------------
``__LiveWindowLike__``
    Common base: creates the pyqtgraph window and the worker thread and wires
    the worker's signals to ``update`` / ``self_destruct``. Subclasses provide
    ``setup_plots`` (build axes and curves) and ``set_data`` (draw a new
    frame).
``__LivePlotterWindow__``
    One set of axes with ``no_plots`` overlaid line traces. The title shows the
    last value of each trace.
``__LiveMultiWindow__``
    ``no_plots`` separate subplots (three per row), one trace each.
``__LiveHeatMap__``
    One 2D image with a colour bar.

Data contract
-------------
The ``data`` array delivered to ``set_data`` is whatever the user's
``data_func`` returned in the main process (after a pickle round trip):

* line plots (single and multi): indexable as ``data[i]`` for
  ``i in range(no_plots)``, each ``data[i]`` a 1D sequence of y values. The x
  axis is the sample index ``0..len(data[i])-1``. A 2D array of shape
  ``(no_plots, n_samples)`` is the natural choice.
* heatmap: a 2D array. With pyqtgraph's default (column-major) image axis
  order, ``data[i, j]`` is drawn at x = i, y = j.

An array of shape ``(0,)`` (the "no data this cycle" sentinel) is skipped by
``update`` and does not reach ``set_data``.

Naming
------
The double-underscore class names are kept from the original code to mark
these classes as internal; users interact only with ``LivePlotAgent``.
"""

from pyqtgraph.Qt import QtGui, QtCore, QtWidgets
import pyqtgraph as pg
import numpy as np

# Relative import: required now that the module lives inside the
# ``liveplotter`` package (the original flat layout used ``from worker import``).
from .worker import __WorkerBee__


class __LiveWindowLike__(QtWidgets.QWidget):
    """
    Base class shared by all live-plot windows.

    The visible window is ``self.window`` (a ``pg.GraphicsLayoutWidget``).
    The ``QWidget`` that this class inherits from is never shown itself. It
    serves as a ``QObject`` that can own Qt slots for the worker's signals.

    Parameters
    ----------
    data_func : callable
        Zero-argument callable returning the next ``numpy.ndarray`` to draw
        (see module docstring for the expected layout).
    title : str
        Plot title (initial title; the single-axes window overwrites it with
        the latest values on every frame).
    xlabel, ylabel : str
        Axis labels.
    refresh_interval : float
        Seconds between data fetches by the worker thread.
    no_plots : int
        Number of traces (single window) or subplots (multi window). Required
        but unused by the heatmap.
    plot_labels : sequence or None
        Legend labels, one per trace. Falsy (``None``, ``[]``) gives labels
        ``1..no_plots``. Required but unused by the heatmap.
    verbose : bool
        Print diagnostic messages.

    Notes
    -----
    The worker thread is created here but started by the subclass, *after*
    ``setup_plots`` has created the plot items that ``set_data`` writes into.
    """

    def __init__(
        self,
        data_func,
        title,
        xlabel,
        ylabel,
        refresh_interval,
        no_plots,
        plot_labels,
        verbose,
    ):
        super().__init__()
        # show=True makes the window appear immediately (once the GUI thread
        # next processes events).
        self.window = pg.GraphicsLayoutWidget(show=True, title="Live Plotting Window")
        self.window.resize(900, 500)
        # Global pyqtgraph option: applies to every plot item created after
        # this call in this process.
        pg.setConfigOptions(antialias=True)

        self.xlabel = xlabel
        self.ylabel = ylabel
        self.title = title
        self.refresh_interval = refresh_interval
        self.no_plots = no_plots
        self.plot_labels = plot_labels
        self.verbose = verbose

        # Pass the bound method ``self.isHidden`` (not its value) so the
        # worker re-evaluates window visibility on every loop iteration.
        self.worker = __WorkerBee__(data_func, self.isHidden, self.refresh_interval)
        self.make_connection(self.worker)

    def __exit__(self, exc_type, exc_value, traceback):
        """Close the visible pyqtgraph window."""
        self.window.close()
        if self.verbose:
            print("LivePlotterWindow exiting ciao bella ciao")

    def isHidden(self):
        """
        Return whether the visible pyqtgraph window is hidden (i.e. closed).

        Overrides ``QWidget.isHidden`` for Python callers so that the state
        of ``self.window`` (the window the user sees) is reported rather
        than that of the never-shown base ``QWidget``.
        """
        return self.window.isHidden()

    def make_connection(self, data_object):
        """
        Connect a worker's signals to this window's slots.

        Parameters
        ----------
        data_object : __WorkerBee__
            The worker whose ``signal1`` (data) and ``signal2`` (finished)
            should drive ``update`` and ``self_destruct``.
        """
        data_object.signal1.connect(self.update)
        data_object.signal2.connect(self.self_destruct)
        return self

    @QtCore.Slot(bool)
    def self_destruct(self, yes):
        """Slot: close the window when the worker reports it has finished."""
        if yes:
            self.__exit__(None, None, None)

    @QtCore.Slot(np.ndarray)
    def update(self, data):
        """
        Slot: receive a data array from the worker and draw it.

        Runs in the GUI thread. A shape ``(0,)`` array means the worker found
        no new data this cycle (empty queue or key not yet present), so the
        frame is skipped and the previous drawing stays on screen.
        """
        if data.shape == (0,):
            if self.verbose:
                print("data is empty, skipping this cycle, please correct this")
        else:
            self.set_data(data)
        return self


class __LivePlotterWindow__(__LiveWindowLike__):
    """
    Single set of axes with ``no_plots`` overlaid line traces.

    LivePlotterWindow is a QWidget object that contains a pyqtgraph window.
    The pyqtgraph window is updated by the WorkerBee object.

    On each frame, trace ``i`` is drawn as ``data[i]`` against the sample
    index, and the plot title is replaced by the last value of every trace,
    formatted as ``| v0 | v1 | ... |``.

    Parameters are those of :class:`__LiveWindowLike__`.
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)
        self.setup_plots()
        # Start polling only after the curves exist, so the first set_data
        # call has something to write into.
        self.worker.start()

    def setup_plots(self):
        """
        Setup the plots, axes, legend, and styling.

        Creates one ``PlotItem`` and ``no_plots`` ``PlotDataItem`` curves in
        ``self.plots``.
        """
        self.graph = self.window.addPlot(title=self.title)
        self.graph.setTitle(self.title, color="grey", size="20pt")

        # Must be created before the curves: ``PlotItem.plot(name=...)`` only
        # registers a curve with a legend that already exists.
        legend = self.graph.addLegend()

        ##################### style points #####################
        self.graph.showGrid(x=True, y=True)
        self.styling = {"font-size": "20px", "color": "grey"}
        # self.graph.setTitle(self.title)
        self.tickfont = QtGui.QFont()
        self.tickfont.setPixelSize(20)
        self.graph.getAxis("bottom").setTickFont(self.tickfont)
        self.graph.getAxis("left").setTickFont(self.tickfont)
        self.graph.getAxis("right").setTickFont(self.tickfont)
        self.set_xlabel(self.xlabel)
        self.set_ylabel(self.ylabel)

        ########################################################
        # Kept from the original code; not used elsewhere.
        self.initial_xydata = [[[0.0], [0.0]]]
        self.plots = []

        for i in range(self.no_plots):
            # An integer pen makes pyqtgraph pick colour pg.intColor(i),
            # cycling through 9 distinct hues.
            self.plots.append(
                self.graph.plot(pen=i, name = f"Channel {self.plot_labels[i]}!!!")
                if self.plot_labels
                else self.graph.plot(pen=i, name = f"Channel {i+1}!!!")
                )

    def set_xlabel(self, label):
        """Set the bottom-axis label with the window's font styling."""
        self.graph.setLabel("bottom", label, **self.styling)

    def set_ylabel(self, label):
        """Set the left-axis label with the window's font styling."""
        self.graph.setLabel("left", label, **self.styling)

    def set_data(self, data):
        """
        Draw one frame.

        Parameters
        ----------
        data : numpy.ndarray
            ``data[i]`` is the y data of trace ``i``; at least ``no_plots``
            rows are needed. Extra rows are ignored.

        Notes
        -----
        If ``data`` has fewer than ``no_plots`` rows, the traces before the
        missing row are updated, then an ``IndexError`` is caught and a
        message printed; the title is not updated for that frame.
        """
        try:
            last_numbers = "|"
            for i, plot in enumerate(self.plots):
                # x is the sample index; a new arange is built every frame
                # because the trace length may change between frames.
                plot.setData(np.arange(len(data[i])), data[i])
                last_numbers += f" {data[i][-1]} |"

            # The title doubles as a numeric read-out of the newest samples.
            self.graph.setTitle(last_numbers, color="white", size="20pt")

        except IndexError:
            print("IndexError: data is not in the correct format")


class __LiveMultiWindow__(__LiveWindowLike__):
    """
    ``no_plots`` separate subplots in a grid, three per row, one trace each.

    Subplot ``i`` draws ``data[i]`` against the sample index. All subplots
    share the same title and axis labels.

    Parameters are those of :class:`__LiveWindowLike__`.
    """

    ### this is link to the parent class decorated functions

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # NOTE: the base class already created and showed a
        # GraphicsLayoutWidget; it is replaced here by a second one. The
        # worker reads ``self.window`` lazily through ``self.isHidden``, so it
        # tracks this new window. The first window is left without a Python
        # reference and is destroyed when garbage-collected.
        self.window = pg.GraphicsLayoutWidget(show = True, title = "Live Plotting Window")
        self.window.resize(900,500)
        # just antialiasing
        pg.setConfigOptions(antialias = True)
        # Creates graph object

        self.graphs = []
        self.plot = []
        self.initial_ydata = np.array([[0.]])
        self.setup_plots()
        self.worker.start()

    def setup_plots(self):
        """
        Build the subplot grid and one curve per subplot.

        Fills ``self.graphs`` (``PlotItem`` per subplot) and ``self.plot``
        (``PlotDataItem`` per subplot).
        """
        self.tickfont = QtGui.QFont()
        self.tickfont.setPixelSize(20)
        for i in range(self.no_plots):
            # Start a new row every three plots. At i == 0 this moves to row 1
            # and leaves row 0 empty, which takes no space on screen.
            if i % 3 ==0:
                self.window.nextRow()
            self.graphs.append(self.window.addPlot(title = self.title))
            self.graphs[i].addLegend()
            self.graphs[i].showGrid(x = True, y = True)
            self.graphs[i].getAxis("bottom").setTickFont(self.tickfont)
            self.graphs[i].getAxis("left").setTickFont(self.tickfont)

        self.styling = {"font-size": "20px", "color": "grey"}

        self.set_xlabel(self.xlabel)
        self.set_ylabel(self.ylabel)

        # creating maybe multiple line plot subclass objects for the self.graph object, store in list
        # data_store keeps a reference to the last frame of each subplot.
        self.data_store = [[]]
        ### storing lineplot instances into list, with indexed data store list
        for i in range(self.no_plots):
            ### setting pen as integer makes line colour cycle through 9 hues by default
            ### check pyqtgraph documentation on styling...it's quite messy
            self.plot.append(self.graphs[i].plot(pen=i, name = f"Channel {self.plot_labels[i]}!!!")
                if self.plot_labels
                else self.graphs[i].plot(pen=i, name = f"Channel {i+1}!!!"))

            # Returns the legend already created above (addLegend reuses an
            # existing legend), so this is a no-op kept from the original.
            legend = self.graphs[i].addLegend()
            self.data_store.append(self.initial_ydata)

    def set_xlabel(self, label):
        """Set the bottom-axis label on every subplot."""
        for i in range(self.no_plots):
            self.graphs[i].setLabel('bottom', label, **self.styling)
        return self

    def set_ylabel(self, label):
        """Set the left-axis label on every subplot."""
        for i in range(self.no_plots):
            self.graphs[i].setLabel('left', label, **self.styling)
        return self

    def set_data(self, data):
        """
        Draw one frame: subplot ``i`` shows ``data[i]`` vs sample index.

        Unlike the single-axes window, an ``IndexError`` (fewer than
        ``no_plots`` rows) is not caught here; it propagates out of the
        ``update`` slot.
        """
        for i in range(self.no_plots):
            self.data_store[i] = data[i]
            self.plot[i].setData(np.arange(len(data[i])), data[i])
        return self


class __LiveHeatMap__(__LiveWindowLike__):
    """
    Live 2D image with an interactive colour bar.

    The colour scale is initialised to the fixed range 0–100 and is *not*
    auto-scaled on update. Values outside the range saturate. The user can drag
    the colour bar in the window to change the range.

    ``no_plots`` and ``plot_labels`` must be passed (base-class signature)
    but are not used.

    Parameters are those of :class:`__LiveWindowLike__`.
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)
        self.setup_plots()
        self.worker.start()

    def setup_plots(self):
        """Create the image item, demo image, colour map and colour bar."""
        # Placeholder image shown until the first real frame arrives.
        self.initial_data = np.fromfunction(lambda i, j: (1+0.3*np.sin(i)) * (i)**2 + (j)**2, (100, 100))

        self.graph = self.window.addPlot(title=self.title)
        self.graph.setTitle(self.title, color="grey", size="20pt")

        legend = self.graph.addLegend()

        ##################### style points #####################
        self.graph.showGrid(x=True, y=True)
        self.styling = {"font-size": "20px", "color": "grey"}
        self.tickfont = QtGui.QFont()
        self.tickfont.setPixelSize(20)
        self.graph.getAxis("bottom").setTickFont(self.tickfont)
        self.graph.getAxis("left").setTickFont(self.tickfont)
        self.graph.getAxis("right").setTickFont(self.tickfont)
        self.set_xlabel(self.xlabel)
        self.set_ylabel(self.ylabel)

        self.img = pg.ImageItem(image=self.initial_data) # create monochrome image from demonstration data
        self.graph.addItem(self.img)            # add to PlotItem 'plot'
        self.cm = pg.colormap.get('CET-L17') # prepare a linear color map
        # CHANGED from ``cmap=`` to ``colorMap=``: ``cmap`` was a deprecated
        # alias removed in pyqtgraph 0.13.4 (TypeError there and in 0.14).
        # ``colorMap`` exists since at least 0.12.4 and is what ``cmap`` was
        # forwarded to, so behaviour is the same on older versions.
        self.bar = pg.ColorBarItem( values= (0, 100), colorMap=self.cm ) # prepare interactive color bar
        # Have ColorBarItem control colors of img and appear in 'plot':
        self.bar.setImageItem(self.img, insert_in = self.graph )
        return self

    def set_xlabel(self, label):
        """Set the bottom-axis label."""
        self.graph.setLabel("bottom", label, **self.styling)
        return

    def set_ylabel(self, label):
        """Set the left-axis label."""
        self.graph.setLabel("left", label, **self.styling)
        return

    def set_data(self, data):
        """
        Replace the image with a new 2D array.

        ``ImageItem.updateImage`` defaults to ``autoLevels=False``, so the
        colour-bar range is kept between frames.
        """
        self.img.updateImage(data)
        return
