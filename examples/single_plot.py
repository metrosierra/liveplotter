"""
Two noisy channels overlaid on one set of axes.

Run with:  uv run python examples/single_plot.py
Close the window, or wait 30 s, to finish.
"""

import time

import numpy as np

from liveplotter import LivePlotAgent

N_SAMPLES = 500


def read_two_channels():
    """Stand-in for an instrument read-out: shape (2, N_SAMPLES)."""
    phase = time.time()
    x = np.linspace(0, 4 * np.pi, N_SAMPLES)
    return np.vstack(
        [
            np.sin(x + phase) + 0.1 * np.random.randn(N_SAMPLES),
            np.cos(x + phase) + 0.1 * np.random.randn(N_SAMPLES),
        ]
    )


window_open = True


def on_close():
    # Called from a background thread when the window is closed.
    global window_open
    window_open = False
    print("window closed")


if __name__ == "__main__":
    agent = LivePlotAgent(clock=0.01)
    agent.new_liveplot(
        data_func=read_two_channels,
        kill_func=on_close,
        title="Two channels",
        xlabel="sample",
        ylabel="signal (a.u.)",
        refresh_interval=0.2,
        no_plots=2,
        plot_labels=["sin", "cos"],
    )

    # Stand-in for the experiment's main loop.
    start = time.time()
    while window_open and time.time() - start < 30:
        time.sleep(0.5)

    agent.close()
