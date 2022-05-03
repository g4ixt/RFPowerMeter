#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Created on Tue Jun  8 18:10:10 2021
@author: Ian Jefferson G4IXT
RF power meter programme for the AD8318/AD7887 power detector sold by Matkis SV1AFN https://www.sv1afn.com/

This code makes use of a subset of the code from touchstone.py from scikit-rf, an open-source
Python package for RF and Microwave applications.
"""

import numpy as np
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import pyqtSlot, QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt5.QtWidgets import QMessageBox, QFileDialog
from PyQt5.QtSql import QSqlDatabase, QSqlTableModel
import spidev
import pyqtgraph
# from collections import deque

import QtPowerMeter
from touchstone_subset import Touchstone

spi = spidev.SpiDev()

# AD7887 ADC control register setting for external reference, single channel, mode 3
# dOut = 0b00100001 # stay powered on all the time
dOut = 0b00100000  # power down when CS high

# Meter scale values
Units = ['pW', 'nW', 'uW', 'mW', 'W', 'kW']
dBm = [-90, -60, -30, 0, 30, 60]


##############################################################################
# classes

class database():
    '''calibration and attenuator/coupler data are stored in a SQLite database'''

    def connect(self):

        print("Open database")
        self.db = QSqlDatabase.addDatabase('QSQLITE')

        if QtCore.QFile.exists('powerMeter.db'):
            self.db.setDatabaseName('powerMeter.db')
            self.db.open()
        else:
            print("Database file missing")
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setText('Database file missing')
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()

    def disconnect(self):
        print('Close Database')
        attenuators.tm.submitAll()
        parameters.tm.submitAll()
        calibration.tm.submitAll()
        del attenuators.tm
        del parameters.tm
        del calibration.tm
        self.db.close()


class Measurement():
    '''Read AD8318 RF Power value via AD7887 ADC using the Serial Peripheral Interface (SPI)'''

    def __init__(self):
        self.timer = QtCore.QTimer()
        self.runTime = QtCore.QElapsedTimer()
        # self.rate = 0
        self.buffer = np.zeros(25, dtype=float)

        self.threadpool = QThreadPool()
        print("Multithreading with %d threads" % self.threadpool.maxThreadCount())
        self.signals = WorkerSignals()

    def readSPI(self):
        # dOut is data sent from the Pi to the AD7887, i.e. MOSI.
        # dIn is the RF power measurement result, i.e. MISO.
        # This method runs in a separate Thread for performance reasons
        for i in range(25):
            dIn = spi.xfer([dOut, dOut])  # AD7882 is 12 bit but Pi SPI only 8 bit so two bytes needed

            if dIn[0] > 13:  # anything > 13 is due to noise or spi errors
                ui.spiNoise.setText('SPI error detected')   # emit as a string signal

            self.dIn = (dIn[0] << 8) + dIn[1]  # shift first byte to be MSB of a 12-bit word and add second byte

            # use calibration nearest to the measurement frequency obtained from selectCal method
            self.sensorPower = (self.dIn/calibration.slope) + calibration.intercept

            self.buffer[i] = self.sensorPower

            if self.sensorPower >= 12 and self.dIn != 0:  # sensor absolute maximum input level exceeded
                ui.sensorOverload.setText('Sensor rating exceeded')  # emit this as string from worker thread for GUI

        self.yAxis = np.roll(self.yAxis, -25)  # shift all the y-values left 10
        self.yAxis[-25:] = self.sensorPower  # write the latest 10 values to the right side
        self.counter += 25

    def updateGUI(self):
        self.averagePower = np.average(self.yAxis[-self.averages:])
        self.powerdBm = self.averagePower - attenuators.loss  # subtract total loss of couplers and attenuators

        # uses the average powers apart from the moving graph, which uses the individual measurements
        ui.sensorPower.setValue(self.averagePower)
        ui.inputPower.setValue(self.powerdBm)

        # update power meter range and label
        try:
            meterRange = next(x for x, val in enumerate(dBm) if val > self.powerdBm)
            if meterRange > 0:
                meterRange += -1
            ui.powerUnit.setText(str(Units[meterRange]))
            ui.powerWatts.setSuffix(str(Units[meterRange]))
        except StopIteration:
            ui.spiNoise.setText('SPI error detected')

        # convert dBm to Watts and update analogue meter scale
        # meterRange = 1  # test
        meter_dB = self.powerdBm - dBm[meterRange]  # ref to the max value for each range, i.e. 1000 units
        self.powerW = 10 ** (meter_dB / 10)  # dB to 'unit' Watts
        if ui.Scale.currentText() == 'Auto':  # future manual setting method to add
            ui.meterWidget.set_MaxValue(1000)
            if self.powerW <= 10:
                ui.meterWidget.set_MaxValue(10)
            if self.powerW >= 10 and self.powerW <= 100:
                ui.meterWidget.set_MaxValue(100)

        # update the analog gauge widget
        ui.meterWidget.update_value(self.powerW, mouse_controlled=False)
        ui.powerWatts.setValue(self.powerW)
        ui.measurementRate.setValue(self.rate)

        # update the moving pyqtgraph
        powerCurve.setData(meter.xAxis, self.yAxis)

    def setTimebase(self):
        self.samples = ui.memorySize.value()
        self.xAxis = np.arange(self.samples, dtype=int)  # test
        self.yAxis = np.full(self.samples, -75, dtype=float)  # test


# class powerScope():
#     '''A moving power vs time display like an oscilloscope'''

#     def __init__(self):
#         # do nothing yet
#         x=0

#     def scan(self, sensorPower):
#         # write y-axis values into buffer
#         for i in range(10):
#             if self.count < self.samples:  # write x and y into the buffer until it's full
#                 self.xAxis[self.count] = self.count
#                 self.yAxis[self.count] = sensorPower[i]
#                 self.count += 1
#             else:
#                 self.yAxis = np.roll(self.yAxis, -1)  # shift all the y-values left one measurement step (x-increment)
#                 self.yAxis[self.count-1] = sensorPower[i]  # write the latest value to the highest x position


class modelView():
    '''set up and process data models bound to the GUI widgets'''

    def __init__(self, tableName):
        self.table = tableName
        self.id = 0
        self.row = 0
        self.loss = 0

    def createTableModel(self):
        # add exception handling?

        self.tm = QSqlTableModel()
        self.tm.setTable(self.table)
        self.tm.setEditStrategy(QSqlTableModel.OnRowChange)
        self.tm.select()

    def addRow(self):  # add a single blank row
        record = self.tm.record()
        self.tm.insertRecord(-1, record)
        self.updateModel()

    def insertData(self, AssetID, Freq, Loss):  # add a single row populated with data

        # needs error trapping for positive insertion losses ***

        record = self.tm.record()
        record.setValue('AssetID', AssetID)
        record.setValue('Freq MHz', Freq)  # database field is set to MHz
        record.setValue('Value dB', Loss)
        self.tm.insertRecord(-1, record)
        # self.tm.submit()
        self.updateModel()
        app.processEvents()

    def getID(self):
        self.id = self.tm.record(self.row).value('AssetID')  # set the Primary Key of the selected row

    def deleteRow(self, selectedRow, numRows):
        self.tm.setEditStrategy(QSqlTableModel.OnManualSubmit)
        self.tm.removeRows(selectedRow, numRows)
        self.tm.submitAll()
        self.tm.setEditStrategy(QSqlTableModel.OnRowChange)
        self.updateModel()

    def showParameters(self):
        # identify which attenuator the user has clicked ('self' is always 'attenuators' when called)
        attenuators.row = ui.browseDevices.currentIndex().row()  # set the row index for the currently selected device
        self.getID()
        # filter to show only matching data from the parameters table
        parameters.tm.setFilter('AssetID =' + str(attenuators.id))
        parameters.updateModel()

    def updateModel(self):
        # model must be re-populated when python code changes data
        self.tm.select()
        self.tm.layoutChanged.emit()

    # def saveData(self):  # not required
    #     self.tm.submit()


class Worker(QRunnable):
    '''    multithread some functions   '''

    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args

    @pyqtSlot()
    def run(self):
        print("%s thread running" % self.fn.__name__)  # print is not thread safe
        while meter.timer.isActive():
            self.fn(*self.args)
        print("%s thread finished" % self.fn.__name__)


class WorkerSignals(QObject):
    '''   signals from running threads   '''

    powerRF = pyqtSignal(np.ndarray)


##############################################################################
# other methods

def exit_handler():
    config.disconnect()
    spi.close()
    print('Closed')


def importS2P():    # could maybe modify this to run in a separate thread so the GUI updates in real time
    # Import the (Touchstone) file containing attenuator/coupler/cable calibration data and extract
    # insertion loss or coupling factors by frequency

    # pop up a dialogue box for user to select the file
    s2pFile = QFileDialog.getOpenFileName(None, 'Import s-parameter file for selected device', '', '*.s2p')
    sParam = Touchstone(s2pFile[0])  # use skrf.io method to read file - error trapping needed

    # extract the device parameters (insertion loss or coupling factors)
    sParamData = sParam.get_sparameter_data('db')
    Freq = sParamData['frequency'].tolist()
    Loss = sParamData['S21DB'].tolist()

    # set attenuator.id to currently selected row, filter on it and delete existing parameters
    attenuators.showParameters()
    parameters.deleteRow(0, parameters.tm.rowCount())

    # read the frequency and S21db data from the lists and insert into SQL database rows
    for i in range(len(Freq)):
        parameters.insertData(attenuators.id, Freq[i] / 1e6, Loss[i])
    parameters.updateModel()


def sumLosses():
    # sum all the losses for the devices set as 'in use'
    attenuators.tm.setFilter('inUse =' + str(1))  # set model to show only devices in use
    attenuators.updateModel()
    attenuators.loss = 0

    # future - check for devices being used out of their freq range

    for i in range(attenuators.tm.rowCount()):
        freqList = []
        lossList = []
        deviceRecord = attenuators.tm.record(i)
        attenuators.id = deviceRecord.value('AssetID')
        parameters.tm.setFilter('AssetID =' + str(attenuators.id))  # filter model to parameters of device i
        parameters.tm.sort(1, 0)  # sort by frequency, ascending required for numpy interpolate
        parameters.updateModel()

        # copy the parameters into lists.  There must be a better way...
        for j in range(parameters.tm.rowCount()):
            parameterRecord = parameters.tm.record(j)
            freqList.append(parameterRecord.value('Freq MHz'))
            lossList.append(parameterRecord.value('Value dB'))

        # interpolate device loss at set freq from the known parameters and sum them
        attenuators.loss += np.interp(ui.freqBox.value(), freqList, lossList)
    ui.totalLoss.setValue(-attenuators.loss)


def selectCal():
    # select nearest calibration frequency to measurement frequency
    difference = 6000
    for i in range(calibration.tm.rowCount()-1):
        calRecord = calibration.tm.record(i)
        if difference > abs(ui.freqBox.value()-calRecord.value('Freq MHz')):
            difference = abs(ui.freqBox.value()-calRecord.value('Freq MHz'))
            calibration.slope = calRecord.value('Slope')
            calibration.intercept = calRecord.value('Intercept')
            ui.calQualLabel.setText(calRecord.value('CalQuality'))


def popUp(message, button):
    msg = QMessageBox(parent=(window))
    msg.setIcon(QMessageBox.Warning)
    msg.setText(message)
    msg.addButton(button, QMessageBox.ActionRole)
    msg.exec_()

##############################################################################
# respond to GUI signals


def delDevices():
    attenuators.showParameters()  # set attenuator.id to currently selected row and set filter for parameters view
    parameters.deleteRow(0, parameters.tm.rowCount())  # delete all parameters where id = attenuator.id
    parameters.tm.submitAll()

    attenuators.deleteRow(attenuators.row, 1)  # now delete the attenuator
    attenuators.tm.submit()
    attenuators.updateModel()
    if attenuators.row > 0:
        ui.browseDevices.selectRow(attenuators.row-1)
    else:
        ui.browseDevices.selectRow(0)
    # parameters.tm.setFilter('')
    attenuators.showParameters()


def addParameter():
    attenuators.row = ui.browseDevices.currentIndex().row()  # set the row index for the currently selected device
    attenuators.getID()
    parameters.insertData(attenuators.id, 0, 0)


def deleteParameter():
    parameters.row = ui.deviceParameters.currentIndex().row()  # set the row index for the currently selected paranmeter
    parameters.deleteRow(parameters.row, 1)


def calibrate():
    calibration.row = ui.calTable.currentIndex().row()  # set the row index for the currently selected calibration
    record = calibration.tm.record(calibration.row)
    slope = (record.value('High Code')-record.value('Low Code'))/((record.value('Cal High dBm')-record.value('Cal Low dBm')))
    intercept = record.value('Cal High dBm')-(record.value('High Code')/slope)
    record.setValue('Slope', slope)
    record.setValue('Intercept', intercept)
    calibration.tm.setRecord(calibration.row, record)  # append the contents of 'record' to the table via the model
    calibration.updateModel()


def deleteCal():
    calibration.row = ui.calTable.currentIndex().row()  # set the row index for the currently selected calibration
    calibration.deleteRow(calibration.row, 1)


def updateCal():
    try:
        openSPI()
    except FileNotFoundError:
        popUp('No SPI device found', 'OK')
    else:
        calibration.row = ui.calTable.currentIndex().row()  # set the row index for the currently selected calibration
        record = calibration.tm.record(calibration.row)
        # record.setValue('CalQuality', ui.calQual.currentText())
        if ui.vHigh.isChecked():
            high.readSPI()
            record.setValue('High Code', high.dIn)
        if ui.vLow.isChecked():
            low.readSPI()
            record.setValue('Low Code', low.dIn)

        calibration.tm.setRecord(calibration.row, record)  # append the contents of 'record' to the table via the model
        calibration.updateModel()
        # if high and low are both now populated IN THE Model record, calculate slope and intercept.
        spi.close()


def openSPI():
    # set up spi bus
    spi.open(0, 0)  # bus 0, device 0.  MISO = GPIO9, MOSI = GPIO10, SCLK = GPIO11
    spi.no_cs = False
    spi.mode = 3  # set clock polarity and phase to 0b11

    # spi max_speed_hz must be integer val accepted by driver : Pi max=31.2e6 but AD7887 max=125ks/s or 2MHz fSCLK
    # valid values are 7.629e3, 15.2e3, 30.5e3, 61e3, 122e3, 244e3, 488e3, 976e3, 1.953e6, [3.9, 7.8, 15.6, 31.2e6]
    spi.max_speed_hz = 1953000


def startMeter():
    try:
        openSPI()
    except FileNotFoundError:
        popUp('No SPI device found', 'OK')
    else:
        # disable settings buttons and start measuring if spi device present
        ui.sensorOverload.setText('')
        ui.spiNoise.setText('')
        ui.browseDevices.setEnabled(False)
        ui.deviceParameters.setEnabled(False)
        ui.calTable.setEnabled(False)

        sumLosses()
        selectCal()
        meter.averages = ui.averaging.value()
        meter.counter = 0   # counts number of power readings
        meter.setTimebase()
        meter.runTime.start()  # A QElapsedTimer that measures how long meter has been running for
        meter.timer.start()  # this timer calls readMeter method every time it re-starts

        measurePower = Worker(meter.readSPI)
        meter.threadpool.start(measurePower)


def readMeter():

    meter.rate = meter.counter / (meter.runTime.elapsed()/1000)
    meter.updateGUI()


def stopMeter():
    meter.timer.stop()
    ui.browseDevices.setEnabled(True)
    ui.deviceParameters.setEnabled(True)
    ui.calTable.setEnabled(True)
    attenuators.tm.setFilter('')
    attenuators.updateModel()
    parameters.tm.setFilter('')
    parameters.updateModel()
    spi.close()


##############################################################################
# instantiate classes

config = database()
config.connect()

meter = Measurement()
# high = Measurement()
# low = Measurement()

attenuators = modelView("Device")
calibration = modelView("calibration")
parameters = modelView("deviceParameters")


##############################################################################
# interfaces to the GUI

app = QtWidgets.QApplication([])  # create QApplication for the GUI
window = QtWidgets.QMainWindow()
ui = QtPowerMeter.Ui_MainWindow()
ui.setupUi(window)

# adjust analog gauge meter
ui.meterWidget.set_MaxValue(10)
ui.meterWidget.set_enable_CenterPoint(enable=False)
ui.meterWidget.set_enable_barGraph(enable=False)
ui.meterWidget.set_enable_value_text(enable=False)
ui.meterWidget.set_enable_filled_Polygon(enable=False)
ui.meterWidget.set_start_scale_angle(90)
ui.meterWidget.set_total_scale_angle_size(270)

# adjust pyqtgraph settings for power vs time display
red = pyqtgraph.mkPen(color='r', width=1.0)
blue = pyqtgraph.mkPen(color='c', width=1.0)
yellow = pyqtgraph.mkPen(color='y', width=1.0)
ui.graphWidget.setYRange(-60, 10)
ui.graphWidget.setBackground('k')  # black
ui.graphWidget.showGrid(x=True, y=True)
ui.graphWidget.addLine(y=10, movable=False, pen=red, label='max', labelOpts={'position':0.05, 'color':('r')})
ui.graphWidget.addLine(y=-5, movable=False, pen=blue, label='<', labelOpts={'position':0.025, 'color':('c')})
ui.graphWidget.addLine(y=-50, movable=False, pen=blue, label='>', labelOpts={'position':0.025, 'color':('c')})
ui.graphWidget.setLabel('left', 'Sensor Power', 'dBm')
ui.graphWidget.setLabel('bottom', 'Power Measurement', 'Samples')
powerCurve = ui.graphWidget.plot([], [], name='Sensor', pen=yellow, width=1)

# populate combo boxes
ui.Scale.addItems(['Auto'])  # future - addition of manual settings
ui.Scale.itemText(0)

# Connect signals from buttons

# attenuators, couplers and cables
ui.addDevice.clicked.connect(attenuators.addRow)
ui.deleteDevice.clicked.connect(delDevices)

# calibration
ui.addRow.clicked.connect(addParameter)
ui.importS2P.clicked.connect(importS2P)
ui.showParameters.clicked.connect(attenuators.showParameters)
ui.deleteRow.clicked.connect(deleteParameter)
ui.addCalData.clicked.connect(calibration.addRow)
ui.deleteCal.clicked.connect(deleteCal)
ui.measure.clicked.connect(updateCal)
ui.calibrate.clicked.connect(calibrate)

# start and stop
ui.runButton.clicked.connect(startMeter)
ui.stopButton.clicked.connect(stopMeter)


##############################################################################
# set up the application

attenuators.createTableModel()

ui.browseDevices.setModel(attenuators.tm)
ui.browseDevices.setColumnHidden(0, True)  # hide Primary Key
ui.browseDevices.resizeColumnToContents(1)
ui.browseDevices.selectRow(0)
calibration.createTableModel()
ui.calTable.setModel(calibration.tm)

parameters.createTableModel()

ui.deviceParameters.setModel(parameters.tm)
ui.deviceParameters.setColumnHidden(0, True)  # hide ID field
attenuators.showParameters

meter.timer.timeout.connect(readMeter)  # A Qtimer defined in the Measurement Class init

window.show()
window.setWindowTitle('Qt Power Meter')

# run the application until the user closes it

try:
    app.exec()
finally:
    exit_handler()  # close database
