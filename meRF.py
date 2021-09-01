#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Created on Tue Jun  8 18:10:10 2021
@author: Ian Jefferson G4IXT
RF power meter programme for the AD8318/AD7887 power detector sold by Matkis SV1AFN https://www.sv1afn.com/
"""
# import sys
# import numpy
from numpy import interp, average
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QMessageBox, QFileDialog
from PyQt5.QtSql import QSqlDatabase, QSqlTableModel
from skrf.io.touchstone import Touchstone
import spidev
import pyqtgraph
from collections import deque

from random import randint  # remove after testing

# import SQLlite
import QtPowerMeter

spi = spidev.SpiDev()

# the spi max_speed_hz must be chosen from a value accepted by the driver : Pi does not work above 31.2e6
speedVal = [7.629e3, 15.2e3, 30.5e3, 61e3, 122e3, 244e3, 488e3,
            976e3, 1.953e6, 3.9e6, 7.8e6, 15.6e6, 31.2e6, 62.5e6, 125e6]

# AD7887 ADC control register setting for external reference, single channel, always powered up
dOut = 0b00100001


##############################################################################
# classes

class database():

    def connect(self):

        self.db = QSqlDatabase.addDatabase('QSQLITE')

        if QtCore.QFile.exists('powerMeter.db'):
            self.db.setDatabaseName('powerMeter.db')
            self.db.open()
        else:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setText('Database file missing')
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()


class Measurement():
    '''Read AD8318 RF Power value via AD7887 ADC using the Serial Peripheral Interface (SPI)'''

    def __init__(self, indx):
        # initialise the SPI speed at one of the valid values for the rPi
        self.spiRate = speedVal[indx]
        self.dIn = 0
        self.sensorPower = -90
        self.powerdBm = -90
        self.powerW = 1
        self.timer = QtCore.QTimer()

    def readSPI(self):
        # dOut is data sent from the Pi to the AD7887, i.e. MOSI.
        # dIn is the RF power measurement result, i.e. MISO.
        try:
            spi.open(1, 0)  # bus 0, device 0
            # spi.no_cs()
            spi.mode = 0  # sets clock polarity and phase
            spi.max_speed_hz = int(self.spiRate)
            self.dIn = spi.xfer3([dOut, dOut], 2)
            spi.close()
            print(dOut)
            print(self.spiRate)
            print(self.dIn)
            # self.dIn = int(self.dIn,base=2)
        except FileNotFoundError:
            self.dIn = 1250 + randint(-30, 30)  # test, remove and un-comment popUp
            # popUp('No SPI device found', 'OK')

    def calcPower(self):
        # use the calibration settings nearest to the measurement frequency
        calRecord = calibration.tm.record(calibration.id)
        self.sensorPower = (self.dIn/calRecord.value('Slope')) + calRecord.value('Intercept')
        self.powerList.append(self.sensorPower)  # used to plot power graph

        if self.sensorPower >= 12:
            popUp("The sensor is no more. It has ceased to be. It is an ex-sensor. \
                  Its maximum input level is exceeded", "No, no, it's stunned")

        self.powerdBm = self.sensorPower - attenuators.loss  # subtract total loss of couplers and attenuators

    def updateGUI(self):
        # update the GUI values in dBm.  Probably should separate into smaller blocks
        ui.sensorPower.setValue(int(self.sensorPower))
        ui.inputPower.setValue(self.powerdBm)

        # update power meter range and label
        Watts = ['pW', 'nW', 'uW', 'mW', 'W', 'kW']
        dBm = [-90, -60, -30, 0, 30, 60]
        meterRange = next(x for x, val in enumerate(dBm) if val > self.powerdBm)
        if meterRange > 0:
            meterRange += -1
        ui.powerUnit.setText(str(Watts[meterRange]))
        ui.powerWatts.setSuffix(str(Watts[meterRange]))

        # convert dBm to Watts and update analogue meter
        meter_dB = self.powerdBm - dBm[meterRange]  # ref to the max value for each range, i.e. 1000 units
        self.powerW = 10 ** (meter_dB / 10)  # dB to Watts
        if ui.Scale.currentText() == 'Auto':  # future manual setting method to add
            ui.meterWidget.set_MaxValue(1000)
            if self.powerW <= 10:
                ui.meterWidget.set_MaxValue(10)
            if self.powerW >= 10 and self.powerW <= 100:
                ui.meterWidget.set_MaxValue(100)
        self.damping.append(self.powerW)
        damping = average(self.damping)
        ui.meterWidget.update_value(damping, mouse_controlled=False)
        ui.powerWatts.setValue(self.powerW)

        # update moving pyqtgraph
        powerCurve.setData(self.timebase, self.powerList)

    def powerScope(self):
        length = ui.dequeLength.value()
        damping = ui.dampingBox.value()
        self.timebase = deque(maxlen=length)
        self.powerList = deque(maxlen=length)
        self.damping = deque(maxlen=damping)
        self.elapsed = 0


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


##############################################################################
# other methods

def exit_handler():
    print('Closing Database')
    attenuators.tm.submitAll()
    parameters.tm.submitAll()
    calibration.tm.submitAll()
    del attenuators.tm
    del parameters.tm
    del calibration.tm
    config.db.close()
    print('Closed')


def importS2P():
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
    attenuators.tm.setFilter('inUse =' + str(1))  # set model to show only devices in use
    attenuators.updateModel()
    attenuators.loss = 0
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
        attenuators.loss += interp(ui.freqBox.value(), freqList, lossList)
    ui.totalLoss.setValue(-attenuators.loss)


def selectCal():
    # select nearest calibration frequency to measurement frequency
    difference = 6000
    for i in range(calibration.tm.rowCount()-1):
        calRecord = calibration.tm.record(i)
        if difference > abs(ui.freqBox.value()-calRecord.value('Freq MHz')):
            difference = abs(ui.freqBox.value()-calRecord.value('Freq MHz'))
            calibration.id = i
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


def deleteCal():
    calibration.row = ui.calTable.currentIndex().row()  # set the row index for the currently selected calibration
    calibration.deleteRow(calibration.row, 1)


def updateCal():
    calibration.row = ui.calTable.currentIndex().row()  # set the row index for the currently selected calibration
    record = calibration.tm.record(calibration.row)
    record.setValue('CalQuality', ui.calQual.currentText())
    if ui.vHigh.isChecked():
        high.readSPI()
        record.setValue('Sensor vHigh', high.dIn)
    if ui.vLow.isChecked():
        low.readSPI()
        record.setValue('Sensor vLow', low.dIn)
    calibration.tm.setRecord(calibration.row, record)  # append the contents of 'record' to the table via the model
    calibration.updateModel()
    # if high and low are both now populated IN THE Model record, calculate slope and intercept.


def startMeter():
    ui.browseDevices.setEnabled(False)
    ui.deviceParameters.setEnabled(False)
    ui.calTable.setEnabled(False)
    sumLosses()
    selectCal()
    meter.powerScope()
    meter.timer.start(ui.timebase.value())  # timer calls readMeter method every time it re-start


def readMeter():
    meter.elapsed += ui.timebase.value()
    meter.timebase.append(meter.elapsed)
    meter.readSPI()
    meter.calcPower()
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


##############################################################################
# instantiate classes

config = database()
config.connect()

meter = Measurement(1)
high = Measurement(1)
low = Measurement(1)

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
# ui.meterWidget.update_value(1, mouse_controlled=False)  # this is how to set the value
ui.meterWidget.set_MaxValue(10)
ui.meterWidget.set_enable_CenterPoint(enable=False)
ui.meterWidget.set_enable_barGraph(enable=False)
ui.meterWidget.set_enable_value_text(enable=False)
ui.meterWidget.set_enable_filled_Polygon(enable=False)
ui.meterWidget.set_start_scale_angle(90)
ui.meterWidget.set_total_scale_angle_size(270)

# adjust pyqtgraph settings
red = pyqtgraph.mkPen(color='r', width=1.0)
blue = pyqtgraph.mkPen(color='b', width=0.5)
ui.graphWidget.setYRange(-80, 10)
ui.graphWidget.setBackground('w')
ui.graphWidget.showGrid(x=False, y=True)
ui.graphWidget.addLine(y=10, movable=False, pen=red)
ui.graphWidget.addLine(y=-5, movable=False, pen=blue)
ui.graphWidget.addLine(y=-50, movable=False, pen=blue)
ui.graphWidget.setLabel('left', 'Sensor Power dBm')
powerCurve = ui.graphWidget.plot([], [], name='Sensor', pen=red, width=5)

# populate combo boxes
ui.calQual.addItems(['Datasheet', 'Uncalibrated Meter', 'Calibrated Meter', 'Lab standard'])
ui.calQual.itemText(0)
ui.Scale.addItems(['Auto'])  # future addition of manual settings
ui.Scale.itemText(0)

# Connect the signals from buttons

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

meter.timer.timeout.connect(readMeter)

window.show()
window.setWindowTitle('Qt Power Meter')

# run the application until the user closes it

try:
    app.exec()
finally:
    exit_handler()  # close database