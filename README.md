# liveplotter

Non-blocking live plotting of experimental data, built on
[pyqtgraph](https://www.pyqtgraph.org/).

(Remember to install a Qt binding of choice first, see below)

You give `liveplotter` a function that returns your latest data as a NumPy
array. It opens a plot window that keeps redrawing that data while your script
carries on. The plots run in a **separate process**, so it works the same from
a terminal, Spyder, Jupyter or any other IDE, and a busy acquisition loop does
not freeze the GUI.

```python
from liveplotter import LivePlotAgent

agent = LivePlotAgent()
agent.new_liveplot(data_func=read_my_detector, title="Detector",
                   xlabel="sample", ylabel="counts", refresh_interval=0.2,
                   no_plots=2, plot_labels=["A", "B"])
```

Three window types are available:

| Method | Window |
|---|---|
| `new_liveplot` | All channels overlaid on one set of axes; the title shows the latest value of each channel |
| `new_liveplot_multi` | One subplot per channel, three per row |
| `new_liveplot_heatmap` | A 2D image with a colour bar |

---

## Installation

`liveplotter` needs **one** Qt binding. Choose it with an extra: `pyqt5`,
`pyqt6` or `pyside6`. If you already have a Qt binding installed, you can
leave the extra out.

With **uv**, to add it to a project:

```bash
uv add "liveplotter[pyqt5] @ git+https://github.com/metrosierra/liveplotter"
```

With **pip**:

```bash
pip install "liveplotter[pyqt5] @ git+https://github.com/metrosierra/liveplotter"
```

To pin a specific release, append a tag, e.g. `...liveplotter@v0.1.0`.

Python ≥ 3.9. The dependencies are `numpy`, `pyqtgraph` and `multiprocess`.
The `multiprocess` package is a fork of `multiprocessing` that uses `dill`
for serialisation.

### For development

```bash
git clone https://github.com/metrosierra/liveplotter
cd liveplotter
uv sync --extra pyqt5        # creates .venv from the exact versions in uv.lock
uv run python examples/single_plot.py
```

`uv.lock` records the exact dependency versions used for development, for
reproducibility. It does not restrict the versions that end users get with
`pip install` or `uv add`. Those follow the ranges in `pyproject.toml`.

---

## Quick start

```python
import time
import numpy as np
from liveplotter import LivePlotAgent


def read_two_channels():
    """Stand-in for your instrument read-out: 2 channels x 500 samples."""
    return np.random.normal(size=(2, 500))


def stop_acquisition():
    print("Window closed, stopping acquisition")


if __name__ == "__main__":          # required on Windows, recommended everywhere
    agent = LivePlotAgent(clock=0.01)

    agent.new_liveplot(
        data_func=read_two_channels,
        kill_func=stop_acquisition,  # optional
        title="Detector",
        xlabel="sample",
        ylabel="counts",
        refresh_interval=0.2,
        no_plots=2,
        plot_labels=["A", "B"],
    )

    # Keep the main program alive while plotting. Normally this is your
    # acquisition loop.
    time.sleep(30)
    agent.close()
```

More complete scripts are in [`examples/`](examples/).

---

## Usage

### `LivePlotAgent(clock=0.01, verbose=False)`

Creating the agent starts the plotting process, which has no windows yet.
One agent can manage several windows.

| Argument | Meaning |
|---|---|
| `clock` | Base period in seconds. Each `data_func` is called every `clock`, the plotting process redraws at most every `clock`, and the default `refresh_interval` is `5 * clock`. |
| `verbose` | Print diagnostic messages from both processes. |

The agent is also a context manager. Leaving the `with` block calls
`close()`:

```python
with LivePlotAgent() as agent:
    agent.new_liveplot(...)
    run_my_experiment()   # plotting stays up while this runs
```

### Opening windows

```python
agent.new_liveplot(data_func, kill_func=None, **plot_settings)
agent.new_liveplot_multi(data_func, kill_func=None, **plot_settings)
agent.new_liveplot_heatmap(data_func, kill_func=None, **plot_settings)
```

Each call returns the agent, so calls can be chained.

* **`data_func`**: a function with no arguments that returns a
  `numpy.ndarray`. It runs in a background thread of **your** process, so it
  can use instrument drivers, DLL handles and so on. Only the returned array
  is sent to the plotting process.
* **`kill_func`** (optional): a function with no arguments. It is called once,
  from a background thread, when the user closes the window. You can use it,
  for example, to stop an acquisition.

All of the following `plot_settings` keys are **required**, for every
window type:

| Key | Type | Meaning |
|---|---|---|
| `title` | `str` | Plot title. The single-axes window replaces it with the latest values once data arrives. |
| `xlabel` | `str` | Bottom-axis label |
| `ylabel` | `str` | Left-axis label |
| `refresh_interval` | `float` or `None` | Seconds between screen updates. `None` or `0` means `5 * clock`. |
| `no_plots` | `int` | Number of channels (traces or subplots). Unused by heatmaps, but must be given. |
| `plot_labels` | `list[str]` or `None` | Legend label per channel. `None` labels them `1, 2, …`. Unused by heatmaps, but must be given. |

A missing key is not reported at the call site. It raises an error inside the
plotting process, which then exits and closes all windows. If windows never
appear, look for a traceback in the console. In Jupyter, that is the terminal
running the Jupyter server.

### What `data_func` must return

**`new_liveplot` and `new_liveplot_multi`**: an array where `data[i]` is the
1D trace of channel `i`, for `i` in `range(no_plots)`. The natural choice is
shape `(no_plots, n_samples)`. Each trace is plotted against its sample
index `0 … n_samples-1`. Traces can change length between calls.

* With `new_liveplot`, if fewer than `no_plots` rows are returned, an
  `IndexError` message is printed and that frame is only partly drawn.

**`new_liveplot_heatmap`**: a 2D array. Element `[i, j]` is drawn at
`x = i`, `y = j`. The colour scale starts at the fixed range **0 to 100** and
does not rescale automatically. Values outside it saturate. You can drag the
colour bar in the window to change the range.

```python
agent.new_liveplot_heatmap(
    data_func=lambda: 100 * np.random.rand(64, 64),
    title="Camera", xlabel="x (px)", ylabel="y (px)",
    refresh_interval=0.2, no_plots=1, plot_labels=None,
)
```

**An empty array** (`np.array([])`) is treated as "no data this time" and
the previous frame stays on screen.

### Timing

* Your `data_func` is called every `clock` seconds, independently of the
  screen refresh. The window always shows the most recent result available
  when it redraws.
* A window updates every `refresh_interval` seconds, but never faster than
  `clock`. Setting `refresh_interval < clock` does not speed it up.
* For the first 5 seconds after a window is opened, `data_func` is polled
  regardless of window state. This covers the start-up time of the window.

### Closing

* **Closing a window** with its close button stops that window. After the
  next state update (≤ about 2 s), polling of its `data_func` stops and
  `kill_func` is called.
* **`agent.close()`** stops the plotting process and closes all windows. It
  takes about 1 s. The `data_func` threads of windows that were still open
  are not stopped by `close()`. They are daemon threads and end when your
  program exits.
* When your main program exits, the plotting process and all helper threads
  stop automatically, because they are daemons. So keep your script running
  for as long as you want to see the plots.

---

## Platform notes

* **Windows** starts subprocesses with `spawn`, which re-imports your
  script. Create the agent inside an `if __name__ == "__main__":` block.
  Otherwise Python raises an error about starting a process before
  bootstrapping has finished.
* **Linux and macOS**: `multiprocess` starts the plotting process with
  `fork`, so the guard is not strictly needed, but it is still good
  practice.
* **Jupyter / Spyder / IPython**: work as-is. `data_func` can be defined
  interactively, because it never leaves your process.

---

## How it works

```
 YOUR PROCESS                                  PLOTTING PROCESS
 ------------                                  ----------------
 LivePlotAgent                                 QApplication + main loop
   per window: thread calling data_func()        (polls commands, reports
     -> self.data[key]                            window states, pumps Qt)
   broadcast thread:                           per window: pyqtgraph window
     self.data ---------- data_q ------------>   + QThread pulling from data_q
   new_liveplot(...) ---- task_q ------------>   creates windows
   state thread <-------- state_q -----------    {key: window_is_open}
```

* `task_q` carries commands such as "open a line-plot window with these
  settings" and "stop".
* `data_q` carries snapshots of `{window_key: latest_array}`. It is bounded
  (50 snapshots), so the producer waits when the plotting side is busy.
* `state_q` reports which windows are still open, so the agent can stop
  polling closed ones and call their `kill_func`.

The source files are commented in detail:

| File | Contents |
|---|---|
| `src/liveplotter/liveplot.py` | `LivePlotAgent` and the plotting-process loop |
| `src/liveplotter/windows.py` | The three window classes |
| `src/liveplotter/worker.py` | The QThread that feeds each window |

---

## Known limitations

* `plot_settings` are not checked when you call `new_liveplot`. See the
  [Opening windows](#opening-windows) section above.
* Calling a `new_liveplot*` method without `data_func` plots built-in dummy
  data, which is meant only for testing the call itself. Its shape suits
  none of the window types well.
* The heatmap colour range is fixed at 0 to 100 at start-up.
* Every data snapshot contains the data of all open windows. With many
  windows of large arrays, transfer cost grows accordingly.

---

## Citing

If you use `liveplotter` in work that leads to a publication, please cite it
using the metadata in [`CITATION.cff`](CITATION.cff). On GitHub, use the
"Cite this repository" button.

## Licence

GNU General Public License v3.0. See [`LICENSE`](LICENSE).

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md).
