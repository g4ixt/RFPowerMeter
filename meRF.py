#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Created on Tue Jun  8 18:10:10 2021
@author: Ian Jefferson G4IXT
RF power meter programme for the AD8318/AD7887 power detector sold by Matkis SV1AFN https://www.sv1afn.com/
"""
# import sys
import numpy
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QMessageBox, QDataWidgetMapper, QFileDialog
from PyQt5.QtSql import QSqlDatabase, QSqlTableModel, QSqlQueryModel, QSqlRelationalTableModel
from skrf.io.touchstone import Touchstone
import spidev
# import SQLlite
import QtPowerMeter

spi = spidev.SpiDev()

# the spi max_speed_hz must be chosen from a value accepted by the driver : Pi does not work above 31.2e6
speedVal = [7.629e3, 15.2e3, 30.5e3, 61e3, 122e3, 244e3, 488e3, 976e3, 1.953e6, 3.9e6, 7.8e6, 15.6e6, 31.2e6, 62.5e6, 125e6]

# AD7887 ADC control register setting for external reference, single channel, always powered up
dOut = 0b00100001


##############################################################################
# classes

class spiMeasurement():
    '''Read AD8318 RF Power value via AD7887 ADC using the Serial Peripheral Interface (SPI)'''

    def __init__(self, indx):
        # initialise the SPI speed at one of the valid values for the rPi
        self.spiRate = speedVal[indx]
        self.dIn = 0

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
            self.dIn = 99  # test
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setText('No SPI device')
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()

class modelView():
    '''set up and process data models bound to the GUI widgets'''

    def __init__(self, tableName):
        self.table = tableName
        self.id = 0
        self.row = 0

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
        record = self.tm.record()
        record.setValue('AssetID', AssetID)
        record.setValue('Freq MHz', Freq)  # database field is set to MHz
        record.setValue('Loss dB', Loss)
        self.tm.insertRecord(-1, record)
        # self.tm.submit()
        self.updateModel()
        app.processEvents()

    # def getRow(self):
    #     self.row = ui.browseDevices.currentIndex().row()  # set the row index for the currently selected row

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

    def saveData(self):
        self.tm.submit()

##############################################################################
# other methods

def openDatabase():

    meterData = QSqlDatabase.addDatabase('QSQLITE')

    if QtCore.QFile.exists('powerMeter.db'):
        meterData.setDatabaseName('powerMeter.db')
        meterData.open()
    else:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText('Database file missing')
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()
    # meterData.close()
    # QSqlRelationalTableModel


def widgetMap():  # this is just here to remind me how to do it
    # map model to Form widgets of the GUI

    attenUpdate = QDataWidgetMapper()
    attenUpdate.setModel(attenuators.tm)
    attenUpdate.setSubmitPolicy(QDataWidgetMapper.ManualSubmit)  # find out how it works
    attenUpdate.addMapping(ui.partID, 1)
    attenUpdate.addMapping(ui.serialID, 2)
    attenUpdate.addMapping(ui.Description, 3)
    attenUpdate.addMapping(ui.powerRating, 4)
    attenUpdate.addMapping(ui.nominalValue, 5)
    attenUpdate.addMapping(ui.minFreq, 6)
    attenUpdate.addMapping(ui.maxFreq, 7)
    # attenUpdate.toFirst()

    selAnt = ui.AttenIDspin.value()
    selAnt += 1
    attenUpdate.setCurrentIndex(selAnt)


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


##############################################################################
# respond to GUI signals

def measPwr():
    power = meter.readSPI()  # need to convert it to RF power
    ui.lcd.display(power)  # need to convert it to RF power
    ui.meterWidget.update_value(power, mouse_controlled=False)  # this is how to set the value - must convert  first


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
    if ui.vHigh.isChecked():
        high.readSPI()
        record.setValue('Sensor vHigh', high.dIn)
    if ui.vLow.isChecked():
        low.readSPI()
        record.setValue('Sensor vLow', low.dIn)
    calibration.tm.setRecord(calibration.row, record)  # append the contents of 'record' to the table via the model
    calibration.updateModel()


##############################################################################
# instantiate classes

meter = spiMeasurement(1)
high = spiMeasurement(1)
low = spiMeasurement(1)

attenuators = modelView("Device")
calibration = modelView("calibration")
parameters = modelView("deviceParameters")
# details = modelView("update")

# meter = AGW()


##############################################################################
# interfaces to the GUI
app = QtWidgets.QApplication([])  # create QApplication for the GUI
window = QtWidgets.QMainWindow()
ui = QtPowerMeter.Ui_MainWindow()
ui.setupUi(window)

# adjust analog gauge meter
ui.meterWidget.update_value(150, mouse_controlled=False)  # this is how to set the value

# Connect the signals from buttons
# ui.runButton.clicked.connect(measPwr)

ui.addDevice.clicked.connect(attenuators.addRow)
ui.deleteDevice.clicked.connect(delDevices)
ui.saveDevice.clicked.connect(attenuators.saveData)

ui.addRow.clicked.connect(addParameter)
ui.importS2P.clicked.connect(importS2P)
ui.showParameters.clicked.connect(attenuators.showParameters)
ui.deleteRow.clicked.connect(deleteParameter)
ui.saveData.clicked.connect(parameters.saveData)

ui.addCalData.clicked.connect(calibration.addRow)
ui.deleteCal.clicked.connect(deleteCal)
ui.calibrate.clicked.connect(updateCal)


##############################################################################
# run the application

openDatabase()

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

# details.createMapping(attenuators.model)
# details.model.addMapping(ui.partID, 1)
# details.model.setCurrentIndex(ui.AttenIDspin.value())
# details.model.setCurrentIndex(0)
# widgetMap()

window.show()
window.setWindowTitle('Qt Power Meter')
app.exec_()  # run the application until the user closes it.  Need to close the database!
