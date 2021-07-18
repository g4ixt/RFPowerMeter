#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Created on Tue Jun  8 18:10:10 2021
@author: Ian Jefferson G4IXT
RF power meter programme for the AD8318/AD7887 power detector sold by Matkis SV1AFN https://www.sv1afn.com/
"""
# import sys
# import numpy
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QMessageBox, QDataWidgetMapper
from PyQt5.QtSql import QSqlDatabase, QSqlTableModel, QSqlQueryModel, QSqlRelationalTableModel
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

class Measurement():
    '''Read AD8318 RF Power value via AD7887 ADC using the Serial Peripheral Interface (SPI)'''

    def __init__(self, indx):
        # initialise the SPI speed at one of the valid values for the rPi
        self.spiRate = speedVal[indx]

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
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setText('No SPI device')
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()


class dataModel():
    '''set up data models to bind to the GUI widgets'''

    def __init__(self, modelName, tableName):
        self.model = modelName
        self.table = tableName
        x = 0

    def createModel(self):
        # add exception handling?

        self.model = QSqlTableModel() # wrong!!!
        self.model.setTable(self.table)
        self.model.setEditStrategy(QSqlTableModel.OnRowChange)  # find out how it works
        # self.model.removeColumn(0)  # no need to show primary key
        self.model.select()

    def createMapping(self):

        self.model = QDataWidgetMapper()
        self.model.setModel(devices.model)
        self.model.setSubmitPolicy(QDataWidgetMapper.ManualSubmit)


##############################################################################
# methods

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


def widgetMap():  # change to a class so it can be updated by other methods
    # map model to form widgets of the GUI

    attenUpdate = QDataWidgetMapper()
    attenUpdate.setModel(devices.model)
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


def selectDevice():
    # record in the database which devices are in use
    # select or highlight row in devices table and populate parameters table

    if ui.useButton.isChecked():
        # update database
        x = 0

    if ui.unuseButton.isChecked():
        # update database
        x = 0

    if ui.importButton.isChecked():
        # open s2p import tab
        x = 0

    if ui.editButton.clicked():
        # activate details area and calibration values
        devices.model.setFilter("AssetID = " + str(ui.AttenIDspin.value()))

        # attenUpdate.setCurrentIndex(selRecord)
        # devices.select()

    if ui.deleteButton.isChecked():
        # are you sure?
        # delete from devices and parameters tables
        x = 0


##############################################################################
# respond to GUI signals


def measPwr():
    power = slow.readSPI()
    ui.lcd.display(power)

    ui.meterWidget.update_value(150, mouse_controlled=False)  # this is how to set the value


##############################################################################
# instantiate classes
slow = Measurement(1)
devices = dataModel("attenuators", "Device")
calibration = dataModel("calibration", "calibration")
details = dataModel("update", devices.model)

# meter = AGW()

# interfaces to the GUI
app = QtWidgets.QApplication([])  # create QApplication for the GUI
window = QtWidgets.QMainWindow()
ui = QtPowerMeter.Ui_MainWindow()
ui.setupUi(window)

# adjust analog gauge meter


# Connect the form control events
# ui.measureButton.clicked.connect(measPwr)

##############################################################################
# run the application

openDatabase()
devices.createModel()
calibration.createModel()
ui.browseDevices.setModel(devices.model)
ui.calTable.setModel(calibration.model)

details.createMapping()
details.model.addMapping(ui.partID, 1)
# details.model.setCurrentIndex(ui.AttenIDspin.value())
details.model.setCurrentIndex(0)
# widgetMap()

ui.editButton.clicked.connect(selectDevice)


window.show()
window.setWindowTitle('Qt Power Meter')
app.exec_()  # run the application until the user closes it



