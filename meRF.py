#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Created on Tue Jun  8 18:10:10 2021
@author: Ian Jefferson G4IXT
A RF power meter programme for the AD8318/AD7887 RF power detector sold by Matkis SV1AFN https://www.sv1afn.com/
"""
# import sys
# import numpy
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QMessageBox, QDataWidgetMapper
from PyQt5.QtSql import QSqlDatabase, QSqlTableModel
import spidev
# import SQLlite
import QtPowerMeter

spi = spidev.SpiDev()

# the spi max_speed_hz must be chosen from a value accepted by the driver : Pi does not work above 31.2e6
speedVal = [7.629e3, 15.2e3, 30.5e3, 61e3, 122e3, 244e3, 488e3, 976e3, 1.953e6, 3.9e6, 7.8e6, 15.6e6, 31.2e6, 62.5e6, 125e6]
# AD7887 ADC control register setting for external reference, single channel, always powered up
dOut = 0b00100001

class Measurement():
    '''Read AD8318 RF Power value via AD7887 ADC using the Serial Peripheral Interface (SPI)'''

    def __init__(self, indx):
        # initialise the SPI speed at one of the valid values for the rPi
        self.spiRate = speedVal[indx]
            
    def readSPI(self):
        # dOut is data sent from the Pi to the AD7887, i.e. MOSI.
        # dIn is the RF power measurement result, i.e. MISO.
        try:
            spi.open(1,0)  # bus 0, device 0
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

         
##############################################################################

# functions
def openDatabase():
    
    meterData = QSqlDatabase.addDatabase('QSQLITE')
    
    if not QtCore.QFile.exists('powerMeter.db'):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText('Database file missing')
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()
    else:        
        meterData.setDatabaseName('powerMeter.db')
        meterData.open()
    
   # dataModels()
    
    # cal.close()
    # QSqlRelationalTableModel
    
def dataModels():
    # set up data models and bind them to the table widgets of the GUI
    
    # add exception handling?
  
    attenuators = QSqlTableModel()
    attenuators.setTable("Device")
    attenuators.select()
    attenuators.setEditStrategy(QSqlTableModel.OnRowChange) # find out how it works
    ui.browseDevices.setModel(attenuators)
    
    powerCal = QSqlTableModel()
    powerCal.setTable("Calibration")
    powerCal.select()
    powerCal.setEditStrategy(QSqlTableModel.OnRowChange) # find out how it works
    ui.calTable.setModel(powerCal)
    
    attenUpdate = QDataWidgetMapper()
    attenUpdate.setModel(attenuators)
    attenUpdate.setSubmitPolicy(QDataWidgetMapper.ManualSubmit) # find out how it works
    attenUpdate.addMapping(ui.lineEdit, 3)
    attenUpdate.toFirst()
    
    

def measPwr():
    power = slow.readSPI()
    ui.lcd.display(power)
    
    ui.meterWidget.update_value(150, mouse_controlled=False) # this is how to set the value

# instantiate measurements
slow = Measurement(1)
# meter = AGW()

# interfaces to the GUI

app = QtWidgets.QApplication([])  # create QApplication for the GUI
window = QtWidgets.QMainWindow()
ui = QtPowerMeter.Ui_MainWindow()
ui.setupUi(window)

# adjust analog gauge meter
# meter.widget.update_value(int(299))

# Connect the form control events
# ui.measureButton.clicked.connect(measPwr)

openDatabase()
dataModels()

window.show()
window.setWindowTitle('Qt Power Meter')
app.exec_()  # run the application until the user closes it

    


        
