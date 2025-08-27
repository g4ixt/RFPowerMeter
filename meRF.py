#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Created on Tue Jun 8 at 18:10:10 2021
@author: Ian Jefferson G4IXT
RF power meter programme for the AD8318/AD7887 power detector sold by Matkis SV1AFN https://www.sv1afn.com/

This code makes use of a subset of the code from touchstone.py from scikit-rf, an open-source
Python package for RF and Microwave applications.
"""

import logging
import numpy as np
import queue
import time

from multiprocessing import Process, freeze_support, Event
from multiprocessing import Queue as mpq

try:
    from PyQt6 import QtWidgets, QtCore, uic
    from PyQt6.QtCore import pyqtSlot, pyqtSignal, QRunnable, QObject, QThreadPool
    from PyQt6.QtWidgets import QMessageBox, QFileDialog
    from PyQt6.QtSql import QSqlDatabase, QSqlTableModel
except ModuleNotFoundError:
    from PyQt5 import QtWidgets, QtCore, uic
    from PyQt5.QtCore import pyqtSlot, pyqtSignal, QRunnable, QObject, QThreadPool
    from PyQt5.QtWidgets import QMessageBox, QFileDialog
    from PyQt5.QtSql import QSqlDatabase, QSqlTableModel
import spidev
import pyqtgraph
from touchstone_subset import Touchstone  # for importing S2P files

spi = spidev.SpiDev()
threadpool = QThreadPool()

# AD7887 ADC control register setting for external reference, single channel, mode 3
dOut = 0b00100000  # power down when CS high

# Meter scale values
Units = ['Auto Range', ' pW', ' nW', ' uW', ' mW', ' W']
dB = [-90, -60, -30, 0, 30, 60]

# calibration slope datasheet limits
fSpec = [900, 1900, 2200]
maxSlope = [-26*1.6384, -27*1.6384, -28*1.6384]  # Max spec mV converted to ADC Code
minSlope = [-23*1.6384, -22*1.6384, -21.5*1.6384]  # Min spec mV converted to ADC Code

logging.basicConfig(format="%(message)s", level=logging.INFO)

###############################################################################
# classes


class Database():
    '''calibration and attenuator/coupler data are stored in a SQLite database'''

    def __init__(self):
        self.db = None

    def connect(self):
        self.db = QSqlDatabase.addDatabase('QSQLITE')
        if QtCore.QFile.exists('powerMeter.db'):
            logging.info('Open database')
            self.db.setDatabaseName('powerMeter.db')
            self.db.open()
            logging.info(f'open: {self.db.isOpen()}  Connection = "{self.db.connectionName()}"')
        else:
            logging.info('Database file missing')
            popUp('Database file missing', 'Ok', 'Critical')

    def disconnect(self):
        attenuators.tm.submitAll()
        parameters.tm.submitAll()
        calibration.tm.submitAll()
        del attenuators.tm
        del parameters.tm
        del calibration.tm
        self.db.close()
        QSqlDatabase.removeDatabase(self.db.databaseName())


class WorkerSignals(QObject):
    error = pyqtSignal(str)
    result = pyqtSignal(list)


class Worker(QRunnable):  # not currently used
    '''Worker threads so that measurements can run outside GUI event loop'''

    def __init__(self, fn):
        super(Worker, self).__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        '''Initialise the runner'''

        logging.info(f'{self.fn.__name__} thread running')
        self.fn()
        logging.info(f'{self.fn.__name__} thread ended')


class Measurement():
    '''Read AD8318 RF Power value via AD7887 ADC using the Serial Peripheral Interface (SPI)'''

    def __init__(self):
        self.mp_running = Event()
        self.sampleTimer = QtCore.QElapsedTimer()
        self.runTimer = QtCore.QElapsedTimer()
        self.sample_rates = np.full(50, 50000)
        self.signals = WorkerSignals()
        self.signals.error.connect(spiError)
        self.buffer_size = 500
        self.fifo = queue.SimpleQueue()
        self.gui_update_timer = QtCore.QTimer()
        self.gui_update_timer.timeout.connect(self.calcPowers)
        self.mp_fifo = mpq()

    def startMeasurement(self):
        try:
            openSPI()
        except FileNotFoundError:
            popUp('No SPI device found', 'Ok', 'Critical')
        else:
            activeButtons(False)
            selectCal()
            sumLosses()
            self.mp_running.set()
            self.setTimebase()
            self.sampleCounter = 0
            self.sampleTimer.start()
            self.gui_update_timer.start(50)
            if __name__ == '__main__':  # prevents the subprocess from launching another subprocess
                freeze_support()
                self.spiTransaction = Process(target=self.readSPI,
                                              args=(dOut, calibration.slope, calibration.intercept))
                self.spiTransaction.start()

    def readSPI(self, dOut, slope, intercept):  # runs as a separate process
        logging.debug(f'dOut = {dOut} slope = {slope} intercept = {intercept}')
        i = 0
        enabled = self.mp_running.is_set()  # if tested every while loop, it slows measurement by ~20%
        buffer = np.zeros(self.buffer_size, dtype=float)
        while enabled:
            if i < self.buffer_size:
                dIn = spi.xfer([dOut, dOut])  # dOut = Pi to AD7887, MOSI. dIn = measurement result, MISO.
                if dIn[0] > 13:
                    self.signals.error.emit('SPI error')  # anything > 13 is due to noise or spi errors
                    return
                dIn = (dIn[0] << 8) + dIn[1]  # shift first byte to be MSB of a 12-bit word and add second byte
                buffer[i] = dIn
                i += 1
            else:
                i = 0
                powers = np.add(np.divide(buffer, slope), intercept)
                self.mp_fifo.put(powers)
                enabled = self.mp_running.is_set()

    def calcPowers(self):
        queue_size = self.mp_fifo.qsize()  # mp queue size is not totally reliable
        for i in range(queue_size):
            buffer = self.mp_fifo.get(block=True, timeout=None)  # pop measurement from FIFO queue
            self.yAxis = np.roll(self.yAxis, -self.buffer_size)  # roll the array left
            self.yAxis[-self.buffer_size:] = buffer  # over-write rolled data with current data

        run_time = self.sampleTimer.nsecsElapsed() / 1e9  # convert nS to S
        self.sample_rates = np.roll(self.sample_rates, 1)
        self.sample_rates[0] = int((self.buffer_size * queue_size) / run_time)
        sample_rate = np.mean(self.sample_rates)
        self.sampleTimer.restart()
        average = int(sample_rate * ui.averaging.value() / 1000)

        avgP = np.average(self.yAxis[:average])
        PdBm = np.subtract(avgP, attenuators.loss)  # correct for couplers and attenuators

        logging.debug(f'calcPowers: sample_rate = {sample_rate} rates = {self.sample_rates}')

        Axis = self.yAxis

        self.updateGUI(Axis, avgP, PdBm, sample_rate)

    def running_mean(self, x, N):
        cumsum = np.cumsum(np.insert(x, 0, 0))
        return (cumsum[N:] - cumsum[:-N]) / float(N)

    def setTimebase(self):
        self.samples = ui.memorySize.value()  # memory size in kSamples
        self.xAxis = np.arange(0, self.samples, 1, dtype=int)  # fill the np array with consecutive integers
        self.yAxis = np.full(self.samples, -75, dtype=float)  # fill the np array with each element = 75

    def updateGUI(self, Axis, avgP, PdBm, sample_rate):
        # update power meter range and label
        if ui.rangeBox.currentText() == 'Auto Range':
            try:
                # determine if the power units are nW, uW, mW, or W
                self.scale = next(index for index, listValue in enumerate(dB) if listValue > PdBm)
                ui.powerUnit.setText(str(Units[self.scale]))
                ui.powerWatts.setSuffix(str(Units[self.scale]))
            except StopIteration:
                logging.info(f'range error = {self.scale}')
                spiError('Range error')
                stopMeter()
                return
        else:
            self.userRange()  # set the units from the combo box

        # convert to display according to meter range selected
        power = 10 ** ((PdBm - dB[self.scale - 1]) / 10)
        ui.meter_widget.set_MaxValue(10.0)  # a max of 1 on the widget doesn't work
        if power >= 1:
            ui.meter_widget.set_MaxValue(10.0)
        if power >= 10:
            ui.meter_widget.set_MaxValue(100.0)
        if power >= 100:
            ui.meter_widget.set_MaxValue(1000.0)

        # update boxes on Display tab (uses the average powers)
        ui.measurementRate.setValue(sample_rate)
        ui.sensorPower.setValue(avgP)
        ui.inputPower.setValue(PdBm)

        # update the analogue gauge widget (uses the average powers)
        ui.meter_widget.update_value(power, mouse_controlled=False)
        ui.powerWatts.setValue(power)

        # update the moving pyqtgraph (uses sampled powers with no averaging)
        powerCurve.setData(self.xAxis, Axis)

    def userRange(self):
        # set the units from the combo box
        self.scale = ui.rangeBox.currentIndex() - 1
        ui.powerUnit.setText(ui.rangeBox.currentText())
        ui.powerWatts.setSuffix(Units[self.scale])


class ModelView():
    '''set up and process data models bound to the GUI widgets'''

    def __init__(self, tableName, graphName):
        self.table = tableName
        self.graphName = graphName
        self.tm = QSqlTableModel()
        self.loss = 0
        self.marker = self.graphName.addLine(0, 90, movable=True, pen='g', label=self.table)
        self.marker.label.setPosition(0.1)
        self.curve = self.graphName.plot([], [], name='', pen='r')
        self.row = None

    def createTableModel(self):
        # add exception handling?
        self.tm.setTable(self.table)

    def insertData(self, **data):  # used by ImportS2P, addFreq, addDevice, addCal
        record = self.tm.record()
        for key, value in data.items():
            logging.debug(f'insertData: key = {key} value={value}')
            record.setValue(str(key), value)
        self.tm.insertRecord(-1, record)
        self.updateModel()

    def deleteRow(self):
        if self.row is None:
            popUp('No row selected', 'Ok', 'Warn')
            return
        self.tm.removeRow(self.row)
        self.tm.submit()

    def update_row(self, **data):
        if self.row is None:
            popUp('No row selected', 'Ok', 'Warn')
            return
        record = self.tm.record(self.row)
        for key, value in data.items():
            logging.debug(f'update_row: key = {key} value={value}')
            record.setValue(str(key), value)
        self.tm.setRecord(self.row, record)
        self.updateModel()

    def updateModel(self):  # model must be re-populated when python code changes data
        self.tm.select()
        self.tm.layoutChanged.emit()

    def showCurve(self, curve):
        # plot calibration slope or device loss in GUI
        self.unlimited()
        freqs = []
        y = []
        self.tm.sort(self.tm.fieldIndex('FreqMHz'), QtCore.Qt.SortOrder.AscendingOrder)

        #  iterate through selected values and display on graph
        for i in range(0, self.tm.rowCount()):
            freqs.append(self.tm.record(i).value('FreqMHz'))
            y.append(self.tm.record(i).value(curve))
        self.curve.setData(freqs, y)

    def update_level(self, curve):
        # update marker label with level
        try:
            for i in range(self.tm.rowCount()):
                if self.tm.record(i).value('FreqMHz') >= self.marker.value():
                    self.marker.label.setText(f'{self.tm.record(i).value(curve):.2f} dB')
                    break
        except TypeError:
            logging.info('update_level: TypeError')
            return

    def table_clicked(self, ui_table):
        self.row = ui_table.currentIndex().row()  # the row index from the QModelIndexObject
        record = self.tm.record(self.row)
        logging.debug(f'table_clicked: {self.table} row {self.row} clicked')
        return record

    def table_header(self):
        header = []
        for i in range(1, self.tm.columnCount()):
            header.append(self.tm.record().fieldName(i))
        return header

    def update_code(self, code):  # change meter.dIn
        if self.row is None:
            popUp('No row selected', 'Ok', 'Warn')
            return
        try:
            openSPI()
        except FileNotFoundError:
            popUp('No SPI device found', 'Ok', 'Critical')
        else:
            dIn = spi.xfer([dOut, dOut])  # dOut = Pi to AD7887, MOSI. dIn = measurement result, MISO.
            if dIn[0] > 13:
                spiError(f'SPI error. dIn={dIn}')  # anything > 13 is due to noise or spi errors
                return
            dIn = (dIn[0] << 8) + dIn[1]  # shift first byte to be MSB of a 12-bit word and add second byte
            self.update_row(code=dIn)
            ui.cal_table.selectRow(self.row)
            spi.close()

    def calibrate(self):
        # Formula from AD8318 data sheet.  AD8318 transfer function slope is negative, higher RF power = lower ADC code
        if self.row is None:
            popUp('No row selected', 'Ok', 'Warn')
            return
        record = self.tm.record(self.row)
        high = record.value('HighCode')
        low = record.value('LowCode')
        cal_high = record.value('CalHighdBm')
        cal_low = record.value('CalLowdBm')
        if 0 not in (high, low, cal_high, cal_low):
            slope = (high - low)/(cal_high - cal_low)
            intercept = cal_high - (high / slope)
            self.update_row(Intercept=intercept, Slope=slope)
            ui.cal_table.selectRow(self.row)
        else:
            popUp('One or all of the ADC Codes/calibration values are zero', 'Ok', 'Warn')

    def unlimited(self):
        while self.tm.canFetchMore():  # remove 256 row limit for QSql Query
            self.tm.fetchMore()


###############################################################################
# other methods


def spiError(message):
    logging.info(message)
    ui.spi_error.setText(message)


def exit_handler():
    stopMeter()
    while meter.fifo.qsize() > 0:
        meter.fifo.get()
    config.disconnect()
    spi.close()
    logging.info('Closed')


def importS2P():
    # Import the (Touchstone) file of attenuator/coupler/cable calibration data
    if attenuators.row is not None:
        index = attenuators.tm.record(attenuators.row).value('AssetID')

        # pop up a dialogue box for user to select the file
        s2pFile = QFileDialog.getOpenFileName(None, 'Import s-parameter file for selected device', '', '*.s2p')
        sParam = Touchstone(s2pFile[0])  # use skrf.io method to read file - error trapping needed.  Very slow.

        # extract the device parameters (insertion loss or coupling factors)
        sParamData = sParam.get_sparameter_data('db')
        Freq = sParamData['frequency'].tolist()
        Loss = sParamData['S21DB'].tolist()

        # read the frequency and S21 data from the lists and insert into model
        deleteAllFreq()
        activeButtons(False)
        logging.info(f'Inserting {len(Freq)} records')
        ui.device_message.setText(f'Inserting {len(Freq)} records')
        for i in range(len(Freq)):
            parameters.insertData(AssetID=index, FreqMHz=Freq[i]/1e6, ValuedB=round(Loss[i], 3))
            parameters.marker.setValue(Freq[i]/1e6)
            ui.device_progress.setValue(int((i + 1) * 100 / len(Freq)))
        parameters.showCurve('ValuedB')
        activeButtons(True)

        # insert the nominal value to the Device data table
        attenuators.update_row(ValuedB=Loss[int(len(Freq) / 2)])

        ui.device_message.setText('')
    else:
        popUp('No device selected', 'Ok', 'Warn')


def sumLosses():  # this might be better done with a relational query? (to avoid changing the model filter)
    attenuators.unlimited()
    attenuators.tm.setFilter('inUse =' + str(1))  # set model to devices in use
    attenuators.updateModel()
    attenuators.loss = 0

    # future - check for devices being used out of their operating freq band

    for i in range(attenuators.tm.rowCount()):
        freqList = []
        lossList = []
        deviceRecord = attenuators.tm.record(i)
        asid = deviceRecord.value('AssetID')
        parameters.tm.setFilter('AssetID =' + str(asid))  # filter to only parameters of device i
        # sort by frequency, ascending: required for numpy interpolate
        parameters.tm.sort(1, QtCore.Qt.SortOrder.AscendingOrder)

        # copy the parameters into lists.  There must be a better way...
        for j in range(parameters.tm.rowCount()):
            parameterRecord = parameters.tm.record(j)
            freqList.append(parameterRecord.value('FreqMHz'))
            lossList.append(parameterRecord.value('ValuedB'))
        # interpolate device loss at set freq from the known parameters and sum them
        attenuators.loss += np.interp(ui.freqBox.value(), freqList, lossList)
    ui.totalLoss.setValue(-attenuators.loss)
    attenuators.tm.setFilter('')
    parameters.tm.setFilter('')


def selectCal():
    # select nearest calibration frequency to measurement frequency
    difference = 6000
    for i in range(calibration.tm.rowCount()-1):
        calRecord = calibration.tm.record(i)
        if difference > abs(ui.freqBox.value()-calRecord.value('FreqMHz')):
            difference = abs(ui.freqBox.value()-calRecord.value('FreqMHz'))
            calibration.slope = calRecord.value('Slope')
            calibration.intercept = calRecord.value('Intercept')
            ui.calQualLabel.setText(calRecord.value('CalQuality') + " " + str(int(calRecord.value('FreqMHz'))) + "MHz")


def popUp(message, button, icon):
    icons = {'Warn': QMessageBox.Icon.Warning, 'Info': QMessageBox.Icon.Information,
             'Critical': QMessageBox.Icon.Critical, 'Question': QMessageBox.Icon.Question}
    buttons = {'Ok': QMessageBox.StandardButton.Ok, 'Cancel': QMessageBox.StandardButton.Cancel}
    msg = QMessageBox(parent=(ui))
    msg.setIcon(icons.get(icon))
    msg.setText(message)
    msg.setStandardButtons(buttons.get(button))
    msg.exec()

##############################################################################
# respond to GUI signals


def deleteFreq():  # delete parameter for the frequency shown in the GUI
    parameters.deleteRow()
    parameters.showCurve('ValuedB')


def deleteAllFreq():
    if attenuators.row is None:
        popUp('No device selected', 'Ok', 'Warn')
        return
    activeButtons(False)
    parameters.unlimited()
    parameters.tm.sort(parameters.tm.fieldIndex('FreqMHz'), QtCore.Qt.SortOrder.AscendingOrder)
    rows = parameters.tm.rowCount()
    logging.info(f'Deleting {rows} records')
    ui.device_message.setText(f'Deleting {rows} records')
    for i in range(rows):
        try:
            parameters.marker.setValue((parameters.tm.record(i).value('FreqMHz')))
            ui.device_progress.setValue(int(i * 100 / rows))
        except TypeError:
            parameters.marker.setValue((parameters.tm.record(0).value('FreqMHz')))
        parameters.tm.removeRow(i)
        parameters.tm.submit()
    parameters.tm.select()
    parameters.showCurve('ValuedB')
    activeButtons(True)
    ui.device_message.setText('')


def addFreq():
    if attenuators.row is None:
        popUp('No device selected', 'Ok', 'Warn')
        return
    parameters.insertData(attenuators.tm.record(attenuators.row).value('AssetID'), 0, 0)


def deleteDevice():  # delete all the device parameters first, then delete the device
    if attenuators.row is None:
        popUp('No device selected', 'Ok', 'Warn')
        return
    deleteAllFreq()
    if parameters.tm.rowCount() == 0:
        attenuators.deleteRow()
        attenuators.row = None
    else:
        popUp('failed to delete some device parameters', 'Ok', 'Warn')
    sumLosses()


def addDevice():
    attenuators.insertData(Description='New Device', inUse=0)


def deleteCal():
    if calibration.row is None:
        popUp('No row selected', 'Ok', 'Warn')
        return
    calibration.deleteRow()
    calibration.showCurve('Slope')
    calibration.row = None


def addCal():
    calibration.insertData(CalHighdBm=-10, FreqMHz=6000, CalLowdBm=-50, HighCode=0, LowCode=0, Slope=0, Intercept=0)
    calibration.tm.submit()


def openSPI():
    # set up spi bus
    spi.open(0, 0)  # bus 0, device 0.  MISO = GPIO9, MOSI = GPIO10, SCLK = GPIO11
    spi.no_cs = False
    spi.mode = 3  # set clock polarity and phase to 0b11

    # spi max_speed_hz = integer accepted by driver : Pi max=31.2e6 but AD7887 max=125ks/s or 2MHz fSCLK
    # valid values (250MHz clock/power of 2). E.g.  7.629e3, 15.2e3, 30.5e3, 61e3, 122e3, 244e3, 488e3, 976e3, 1.953e6
    # 1.953e6 causes regular errors (spikes). Probably depends on GPIO connection capacitance etc
    spi.max_speed_hz = 1736111


def stopMeter():
    meter.mp_running.clear()
    try:
        while meter.spiTransaction.is_alive():
            logging.info('waiting for spiTransaction process to stop')
            time.sleep(0.1)
        logging.info('spiTransaction process stopped')
    except AttributeError:
        pass
    meter.gui_update_timer.stop()  # stop timer
    ui.powerWatts.setValue(0)
    ui.measurementRate.setValue(0)
    ui.sensorPower.setValue(-70)
    ui.inputPower.setValue(-70)
    ui.spi_error.setText('')
    activeButtons(True)
    spi.close()


def freqChanged():
    sumLosses()
    selectCal()


def deviceWidget():
    ui.meter.setCurrentWidget(ui.devices)


def activeButtons(tF):
    # prevent User button presses that may affect readings when meter is running
    ui.loadS2P.setEnabled(tF)
    ui.measHigh.setEnabled(tF)
    ui.measLow.setEnabled(tF)
    ui.addDevice.setEnabled(tF)
    ui.deleteDevice.setEnabled(tF)
    ui.addFreq.setEnabled(tF)
    ui.delFreq.setEnabled(tF)
    ui.delAllFreq.setEnabled(tF)
    ui.calibrate.setEnabled(tF)
    ui.addCal.setEnabled(tF)
    ui.deleteCal.setEnabled(tF)


def device_clicked():
    record = attenuators.table_clicked(ui.device_table)
    parameters.tm.setFilter('AssetID= "' + str(record.value('AssetID')) + '"')
    parameters.marker.setValue(parameters.tm.record(0).value('FreqMHz'))
    parameters.marker.label.setText(f'{record.value("Part")} {record.value("Description")}')
    parameters.showCurve('ValuedB')


def cal_clicked():
    record = calibration.table_clicked(ui.cal_table)
    calibration.marker.setValue(record.value('FreqMHz'))
    calibration.marker.label.setText(f'{record.value("Slope"):.2f}')


###############################################################################
# Instantiate classes
app = QtWidgets.QApplication([])  # create QApplication for the GUI
app.setApplicationName('QtRFPower')
app.setApplicationVersion(' v1.0.1')
ui = uic.loadUi("powerMeter.ui")

config = Database()
config.connect()
meter = Measurement()

attenuators = ModelView('Device', ui.deviceCurve)
calibration = ModelView('Calibration', ui.slopeFreq)
parameters = ModelView('deviceParameters', ui.deviceCurve)
attenuators.marker.setPen('y')
attenuators.marker.setAngle(0)

###############################################################################
# GUI settings

# adjust analog gauge meter
ui.meter_widget.set_MaxValue(10)
ui.meter_widget.set_enable_CenterPoint(enable=False)
ui.meter_widget.set_enable_value_text(enable=False)
ui.meter_widget.set_enable_filled_Polygon(enable=True)
ui.meter_widget.set_start_scale_angle(135)
ui.meter_widget.set_enable_ScaleText(enable=True)

# pyqtgraph settings for power vs time display
red = pyqtgraph.mkPen(color='r', width=1.0)
blue = pyqtgraph.mkPen(color='c', width=0.5, style=QtCore.Qt.PenStyle.DashLine)
yellow = pyqtgraph.mkPen(color='y', width=1.0)
ui.graphWidget.setYRange(-60, 10)
ui.graphWidget.setBackground('k')  # black
ui.graphWidget.showGrid(x=True, y=True)
ui.graphWidget.addLine(y=0, movable=False, pen=red, label='max',
                       labelOpts={'position': 0.05, 'color': ('r')})
ui.graphWidget.addLine(y=-10, movable=False, pen=blue, label='',
                       labelOpts={'position': 0.025, 'color': ('c')})
ui.graphWidget.addLine(y=-50, movable=False, pen=blue, label='',
                       labelOpts={'position': 0.025, 'color': ('c')})
ui.graphWidget.setLabel('left', 'Sensor Power', 'dBm')
ui.graphWidget.setLabel('bottom', 'Power Measurement', 'Samples')
powerCurve = ui.graphWidget.plot([], [], name='Sensor', pen=yellow, width=1)

# pyqtgraph settings for device parameters display
ui.deviceCurve.showGrid(x=True, y=True)
ui.deviceCurve.setBackground('k')  # white
ui.deviceCurve.setLabel('left', 'Gain', 'dB')
ui.deviceCurve.setLabel('bottom', 'Frequency', '')

# pyqtgraph settings for calibration display
ui.slopeFreq.addLegend(offset=(20, 10))
ui.slopeFreq.setXRange(0, 3200, padding=0)
ui.slopeFreq.showGrid(x=True, y=True)
ui.slopeFreq.setBackground('k')  # white
ui.slopeFreq.setLabel('bottom', 'Frequency', '')
ui.slopeFreq.setLabel('left', 'Transfer Fn Slope (Codes/dB)', '')
maxLim = ui.slopeFreq.plot(fSpec, maxSlope, name='AD8318 spec limits', pen='y')
minLim = ui.slopeFreq.plot(fSpec, minSlope, pen='y')

###############################################################################
# Connect signals from buttons and sliders

# Meter widget
ui.actionGauge.triggered.connect(lambda: ui.meter.setCurrentWidget(ui.gauge))
ui.actionClose.triggered.connect(app.closeAllWindows)
ui.runButton.clicked.connect(meter.startMeasurement)
ui.stopButton.clicked.connect(stopMeter)
ui.freqBox.valueChanged.connect(freqChanged)
ui.rangeBox.currentIndexChanged.connect(meter.userRange)
parameters.marker.sigPositionChanged.connect(lambda: parameters.update_level('ValuedB'))
calibration.marker.sigPositionChanged.connect(lambda: calibration.update_level('Slope'))

# Devices widget
ui.actionDevices.triggered.connect(lambda: ui.meter.setCurrentWidget(ui.devices))
ui.addFreq.clicked.connect(addFreq)
ui.delFreq.clicked.connect(deleteFreq)
ui.delAllFreq.clicked.connect(deleteAllFreq)
ui.loadS2P.clicked.connect(importS2P)
ui.device_table.clicked.connect(device_clicked)
ui.deleteDevice.clicked.connect(deleteDevice)
ui.addDevice.clicked.connect(addDevice)

# Calibration widget
ui.actionCalibration.triggered.connect(lambda: ui.meter.setCurrentWidget(ui.calibration))
ui.addCal.clicked.connect(addCal)
ui.deleteCal.clicked.connect(deleteCal)
ui.cal_table.clicked.connect(cal_clicked)
ui.measHigh.clicked.connect(lambda: calibration.update_code('HighCode'))
ui.measLow.clicked.connect(lambda: calibration.update_code('LowCode'))
ui.calibrate.clicked.connect(calibration.calibrate)

###############################################################################
# set up the application

attenuators.createTableModel()  # attenuator/coupler etc devices
colHeader = ui.device_table.horizontalHeader()
colHeader.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
attenuators.tm.select()
ui.device_table.setModel(attenuators.tm)

parameters.createTableModel()  # loss vs frequency for each device
colHeader = ui.params_table.horizontalHeader()
colHeader.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
parameters.tm.select()
ui.params_table.setModel(parameters.tm)

calibration.createTableModel()
calibration.tm.select()
ui.cal_table.setModel(calibration.tm)

ui.rangeBox.addItems(Units)

sumLosses()
selectCal()
calibration.showCurve('Slope')

ui.show()

###############################################################################
# run the application until the user closes it

try:
    app.exec()
finally:
    exit_handler()  # close database
