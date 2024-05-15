#!/usr/bin/env python3

from pyqtgraph.Qt import QtCore
import numpy as np
import time


class __WorkerBee__(QtCore.QThread): 
    """
    WorkerBee is a QThread object that emits a signal every
                                                    refresh_interval seconds.
    The signal is connected to a slot in the LivePlotterWindow object that
                                                            updates the plot.
    """

    signal1 = QtCore.pyqtSignal(np.ndarray)
    signal2 = QtCore.pyqtSignal(bool)
    # signal is a pyqtSignal object that emits a numpy array

    def __init__(self, data_func, isHidden_toggle, refresh_interval):
        super().__init__()

        self.isHidden = isHidden_toggle
        self.data_func = data_func
        self.refresh_interval = refresh_interval

    def run(self):

        while not self.isHidden():
            data = self.data_func()
            self.signal1.emit(data)
            time.sleep(self.refresh_interval)
        self.quit()
        print("WorkerBee vi saluta")
        self.signal2.emit(True)


