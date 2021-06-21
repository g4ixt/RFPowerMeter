#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jun  8 18:10:10 2021

@author: ian jefferson
"""
# import sys
# import numpy
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtSql import QSqlDatabase
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
            spi.open(0,0)
            spi.max_speed_hz = speedVal[self.spiRate]
            self.dIn = spi.xfer3(dOut, 2)
            spi.close()
            self.dIn = int(self.dIn,base=2)
        except FileNotFoundError:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setText('No SPI device')
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()


##############################################################################

# functions
def calData():
    cal = QSqlDatabase.addDatabase('QSQLITE')
    cal.setDatabaseName('calibration.sqlite')
    cal.open()
    cal.close()

def measPwr():
    power = slow.readSPI()
    ui.lcd.display(power)

# instantiate measurements
slow = Measurement(1)

# interfaces to the GUI

app = QtWidgets.QApplication([])  # create QApplication for the GUI
window = QtWidgets.QMainWindow()
ui = QtPowerMeter.Ui_MainWindow()
ui.setupUi(window)

# Connect the form control events
ui.measureButton.clicked.connect(measPwr)

calData()

window.show()
window.setWindowTitle('Qt Power Meter')
app.exec_()  # run the application until the user closes it

    


        
