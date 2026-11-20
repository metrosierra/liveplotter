"""
Live 2D image. The colour bar starts at the range 0-100 (drag it to change).

Run with:  uv run python examples/heatmap.py
"""

import time

import numpy as np

from liveplotter import LivePlotAgent

SIZE = 64
x_grid, y_grid = np.meshgrid(np.arange(SIZE), np.arange(SIZE), indexing="ij")


def read_camera():
    """Stand-in for a camera frame: a moving Gaussian spot scaled to 0-100."""
    centre = SIZE / 2 + 15 * np.sin(time.time())
    spot = np.exp(-((x_grid - centre) ** 2 + (y_grid - SIZE / 2) ** 2) / 50.0)
    return 100 * spot + 5 * np.random.rand(SIZE, SIZE)


if __name__ == "__main__":
    agent = LivePlotAgent(clock=0.01)
    agent.new_liveplot_heatmap(
        data_func=read_camera,
        title="Camera",
        xlabel="x (px)",
        ylabel="y (px)",
        refresh_interval=0.2,
        no_plots=1,        # required, unused for heatmaps
        plot_labels=None,  # required, unused for heatmaps
    )
    time.sleep(30)
    agent.close()
