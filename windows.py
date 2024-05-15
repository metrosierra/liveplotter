#!/usr/bin/env python3

from pyqtgraph.Qt import QtGui, QtCore, QtWidgets
import pyqtgraph as pg
import numpy as np

from queue import Empty


from worker import __WorkerBee__


'''
General threadsafe subprocessed live plotter using pyqtgraph 
brought over by Mingsong WU circa 2023

This version is more performant but might take up more cpu

workerbee, liveplotterwindow, livemultwindow, LiveWindowLike set up 
the plot styling and update system

liveplotprocess, liveplotagent, __Qapp_liveplot__ set up the data transfer
ecosystem based on multiprocessing task/data queues

'''


class __LiveWindowLike__(QtWidgets.QWidget):

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
        self.window = pg.GraphicsLayoutWidget(show=True, title="Live Plotting Window")
        self.window.resize(900, 500)
        pg.setConfigOptions(antialias=True)
        
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.title = title
        self.refresh_interval = refresh_interval
        self.no_plots = no_plots
        self.plot_labels = plot_labels
        self.verbose = verbose

        self.worker = __WorkerBee__(data_func, self.isHidden, self.refresh_interval)
        self.make_connection(self.worker)

    def __exit__(self, exc_type, exc_value, traceback):
        self.window.close()
        if self.verbose:
            print("LivePlotterWindow exiting ciao bella ciao")

    def isHidden(self):
        return self.window.isHidden()

    def make_connection(self, data_object):
        data_object.signal1.connect(self.update)
        data_object.signal2.connect(self.self_destruct)
        return self

    @QtCore.pyqtSlot(bool)
    def self_destruct(self, yes):
        if yes:
            self.__exit__(None, None, None)

    @QtCore.pyqtSlot(np.ndarray)
    def update(self, data):
        if data.shape == (0,):
            if self.verbose:
                print("data is empty, skipping this cycle, please correct this")
        else:
            self.set_data(data)
        return self 

class __LivePlotterWindow__(__LiveWindowLike__):
    """
    LivePlotterWindow is a QWidget object that contains a pyqtgraph window.
    The pyqtgraph window is updated by the WorkerBee object.
    """

    def __init__(self, **kwargs):

        super().__init__(**kwargs)
        self.setup_plots()
        self.worker.start()


    def setup_plots(self):
        """
        Setup the plots, axes, legend, and styling.
        """
        self.graph = self.window.addPlot(title=self.title)
        self.graph.setTitle(self.title, color="grey", size="20pt")

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
        self.initial_xydata = [[[0.0], [0.0]]]
        self.plots = []

        for i in range(self.no_plots):
            self.plots.append(
                self.graph.plot(pen=i, name = f"Channel {self.plot_labels[i]}!!!")
                if self.plot_labels
                else self.graph.plot(pen=i, name = f"Channel {i+1}!!!")
                )

    def set_xlabel(self, label):
        self.graph.setLabel("bottom", label, **self.styling)

    def set_ylabel(self, label):
        self.graph.setLabel("left", label, **self.styling)

    def set_data(self, data):
        try:
            last_numbers = "|"
            for i, plot in enumerate(self.plots):
                plot.setData(np.arange(len(data[i])), data[i])
                last_numbers += f" {data[i][-1]} |"

            self.graph.setTitle(last_numbers, color="white", size="20pt")
            
        except IndexError:
            print("IndexError: data is not in the correct format")

class __LiveMultiWindow__(__LiveWindowLike__):

    ### this is link to the parent class decorated functions

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

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
        self.tickfont = QtGui.QFont()
        self.tickfont.setPixelSize(20)
        for i in range(self.no_plots): 
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
        self.data_store = [[]]
        ### storing lineplot instances into list, with indexed data store list
        for i in range(self.no_plots):
            ### setting pen as integer makes line colour cycle through 9 hues by default
            ### check pyqtgraph documentation on styling...it's quite messy
            self.plot.append(self.graphs[i].plot(pen=i, name = f"Channel {self.plot_labels[i]}!!!")
                if self.plot_labels
                else self.graphs[i].plot(pen=i, name = f"Channel {i+1}!!!"))
            
            legend = self.graphs[i].addLegend()
            self.data_store.append(self.initial_ydata)
        
    def set_xlabel(self, label):
        for i in range(self.no_plots):
            self.graphs[i].setLabel('bottom', label, **self.styling)
        return self
    def set_ylabel(self, label):
        for i in range(self.no_plots):
            self.graphs[i].setLabel('left', label, **self.styling)
        return self

    def set_data(self, data):
        for i in range(self.no_plots):
            self.data_store[i] = data[i]
            self.plot[i].setData(np.arange(len(data[i])), data[i])
        return self

class __LiveHeatMap__(__LiveWindowLike__):
    
    def __init__(self, **kwargs):

        super().__init__(**kwargs)
        self.setup_plots()
        self.worker.start()

    def setup_plots(self):
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
        self.bar = pg.ColorBarItem( values= (0, 100), cmap=self.cm ) # prepare interactive color bar
        # Have ColorBarItem control colors of img and appear in 'plot':
        self.bar.setImageItem(self.img, insert_in = self.graph ) 
        return self

    def set_xlabel(self, label):
        self.graph.setLabel("bottom", label, **self.styling)
        return 
    
    def set_ylabel(self, label):
        self.graph.setLabel("left", label, **self.styling)
        return
    
    def set_data(self, data):
        self.img.updateImage(data)
        return 
