"""
Five channels, one subplot each (three subplots per row).

Run with:  uv run python examples/multi_plot.py
"""

import time

import numpy as np

from liveplotter import LivePlotAgent

N_CHANNELS = 5


def read_channels():
    """Stand-in read-out: shape (N_CHANNELS, 200), random walks."""
    return np.cumsum(np.random.randn(N_CHANNELS, 200), axis=1)


if __name__ == "__main__":
    with LivePlotAgent(clock=0.01) as agent:
        agent.new_liveplot_multi(
            data_func=read_channels,
            title="Channels",
            xlabel="sample",
            ylabel="value",
            refresh_interval=0.2,
            no_plots=N_CHANNELS,
            plot_labels=[f"ch{i}" for i in range(N_CHANNELS)],
        )
        # Plots stay up only while the with-block is running.
        time.sleep(30)
