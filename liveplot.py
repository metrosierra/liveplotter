#!/usr/bin/env python3

import numpy as np
from PyQt5.QtWidgets import QApplication
import time
import threading

from functools import partial
import multiprocess as mp, queue
from queue import Empty
import operator

from windows import __LivePlotterWindow__, __LiveMultiWindow__, __LiveHeatMap__

'''
General threadsafe subprocessed live plotter using pyqtgraph 
brought over by Mingsong WU circa 2023

This version is more performant but might take up more cpu

workerbee, LivePlotterWindow, LiveMultWindow, LiveHeatMap, LiveWindowLike set up 
the plot styling and update system

LivePlotProcess, LivePlotAgent, __Qapp_liveplot__ set up the data transfer
ecosystem based on multiprocessing task/data queues

'''
###################################################################################
def __Qapp_liveplot__(task_q, state_q, data_q, clock, verbose):
    app = QApplication([])
    try:
        liveplot_instance = __LivePlotProcess__(
            task_q, state_q, data_q, clock, app, verbose
        )
    except Exception as e:
        raise e
    # return liveplot_instance
###################################################################################
class __LivePlotProcess__:
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
    We want to try to phase towards using multiprocess.Process method instead
    of threading.Thread to initialise the async live plot QT app. This is because
    pyqt does not like to be sub-threaded, but is ok with sub-processing.

    Sub-threading method (plot_live_plot) works with spyder, not with anything else.
    To be console-agnostic, we try sub-processing, mediated by ProcessManager class.

    LivePlotAgent class hosts the Queue method which lets us pipe commands and data into
    the live plotting subprocess.
    """

    def __init__(self, clock=0.1, verbose=False):
        """
        self.queue = something.Queue()

        """
        self.clock_interval = clock
        self.verbose = verbose
        self.task_q = mp.Queue()
        self.state_q = mp.Queue()
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
        self.process.daemon = True
        self.process.start()
        self.window_no = 0
        self.available_window_keys = []
        self.data = {}
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
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.active = False
        self.task_q.put(["break", None, None])
        if self.verbose:
            print("command sent!")
        time.sleep(1)
        self.__flush_queues__()
        self.process.terminate()
        return self

    def __flush_queues__(self):

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
                pass

        if self.verbose:
            print("thread exiting!!!!!!!!!!!")
        return

    def __transmit_data__(self):
        if self.verbose:
            print("starting transmission data thread")
        while self.active:
            if True in self.states.values():
                self.data_q.put(self.data)
            time.sleep(1e-20)

    def __check_states__(self):
        while self.active:
            if not self.state_q.empty():
                try:
                    states = self.state_q.get()
                    self.states = states
                    self._garbage_collection_()
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
        for key in self.states:
            if not self.states[key] and key not in self.available_window_keys:
                if self.verbose:
                    print(f"Cleaning data for key:{key}")
                self.data[key] = np.array([])

    def __new_plot_prep__(self, data_func=None, kill_func=None):
        avail_win = None
        if len(self.available_window_keys) > 0:
            avail_win = min(self.available_window_keys)

        if avail_win and self.window_no - int(avail_win) > 1:
            key = avail_win
        else:
            key = str(self.window_no)
            self.window_no += 1

        if self.verbose:
            print(f"Key: {key}")
        ### some dummy data if data func is None
        if not data_func:
            data_func = lambda: np.array(
                [[np.linspace(0, 1, 1000), np.random.rand(1000)]]
            )

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
        key = self.__new_plot_prep__(data_func, kill_func)
        self.task_q.put(["new_heatmap", key, plot_settings])
        if self.verbose:
            print("command sent!")
        return self

    def new_liveplot_multi(self, data_func=None, kill_func=None, **plot_settings):
        key = self.__new_plot_prep__(data_func, kill_func)
        self.task_q.put(["new_multi_plot", key, plot_settings])
        if self.verbose:
            print("command sent!")
        return self

    def new_liveplot(self, data_func=None, kill_func=None, **plot_settings):
        key = self.__new_plot_prep__(data_func, kill_func)
        self.task_q.put(["new_live_plot", key, plot_settings])
        # self.task_q.put(['dummy', key, plot_settings])
        if self.verbose:
            print("command sent!")
        return self

    def close(self):
        self.__exit__(None, None, None)
        return