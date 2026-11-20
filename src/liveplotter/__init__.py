"""
liveplotter: non-blocking live plotting of experimental data with pyqtgraph.

The plots run in a separate process, so your acquisition script, console or
IDE is never blocked by the GUI. The only public object is
:class:`LivePlotAgent`::

    from liveplotter import LivePlotAgent

    agent = LivePlotAgent(clock=0.1)
    agent.new_liveplot(data_func=my_reader, title="Signal", xlabel="sample",
                       ylabel="V", refresh_interval=0.2, no_plots=1,
                       plot_labels=None)

See the README for full usage, data-format rules and caveats.

Modules
-------
liveplot
    ``LivePlotAgent`` (user side) and the plotting-subprocess main loop.
windows
    The pyqtgraph window classes (line plot, multi-subplot, heatmap).
worker
    The QThread that feeds each window with data.
"""

from importlib.metadata import PackageNotFoundError, version

from .liveplot import LivePlotAgent

try:
    # Single source of truth for the version: pyproject.toml.
    __version__ = version("liveplotter")
except PackageNotFoundError:
    # Running from a source tree that has not been installed.
    __version__ = "unknown"

__all__ = ["LivePlotAgent", "__version__"]
