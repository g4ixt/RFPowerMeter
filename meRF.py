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
from PyQt5.QtWidgets import QMessageBox, QFileDialog, QDataWidgetMapper
from PyQt5.QtSql import QSqlDatabase, QSqlTableModel
import spidev
import pyqtgraph

import QtPowerMeter  # the GUI
from touchstone_subset import Touchstone  # for importing S2P files

spi = spidev.SpiDev()

# AD7887 ADC control register setting for external reference, single channel, mode 3
# dOut = 0b00100001 # stay powered on all the time
dOut = 0b00100000  # power down when CS high

# Meter scale values
Units = [' nW', ' uW', ' mW', ' W', ' kW']
dB = [-60, -30, 0, 30, 60, 90]

# Frequency radio button values
fBand = [14, 50, 70, 144, 432, 1296, 2320, 3400, 5650]


##############################################################################
# classes


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
        self.buffer = np.zeros(25, dtype=float)
        self.threadpool = QThreadPool()
        print("Multithreading with %d threads" % self.threadpool.maxThreadCount())

    def readSPI(self):
        # dOut is data sent from the Pi to the AD7887, i.e. MOSI.
        # dIn is the RF power measurement result, i.e. MISO.
        # This runs in separate Thread for performance, and samples power 25 times, storing results in a buffer
        for i in range(25):
            dIn = spi.xfer([dOut, dOut])  # AD7882 is 12 bit but Pi SPI only 8 bit so two bytes needed
            if dIn[0] > 13:  # anything > 13 is due to noise or spi errors
                ui.spiNoise.setText('SPI error')   # future: emit as a string signal for GUI

            self.dIn = (dIn[0] << 8) + dIn[1]  # shift first byte to be MSB of a 12-bit word and add second byte
            self.buffer[i] = self.dIn

            # if self.sensorPower >= 12 and self.dIn != 0:  # sensor absolute maximum input level exceeded
            #     ui.sensorOverload.setText('Sensor rating exceeded')  # emit this as string from worker thread for GUI

        # use calibration nearest to the measurement frequency obtained from selectCal method
        self.buffer = (self.buffer/calibration.slope) + (calibration.intercept)

        # Append buffer to Shift Register - slows sample rate.  Numpy roll is faster than collections.deque and slicing
        self.yAxis = np.roll(self.yAxis, -25)
        self.yAxis[-25:] = self.buffer
        self.counter += 25

    def updateGUI(self):
        self.averagePower = np.average(self.yAxis[-self.averages:])
        self.measuredPdBm = self.averagePower - attenuators.loss  # subtract total loss of couplers and attenuators

        # uses the average powers apart from the moving graph, which uses the individual measurements
        ui.sensorPower.setValue(self.averagePower)
        ui.inputPower.setValue(self.measuredPdBm)

        # update power meter range and label
        if ui.autoRangeButton.isChecked():
            try:
                self.autoRange()
            except StopIteration:
                ui.spiNoise.setText('SPI error')
                meter.timer.stop()  # stops the measurement worker thread - it loops when timer is active
                popUp('Sensor missing, not powered, or faulty', 'OK')
                stopMeter()
                return
        else:
            self.userRange()

        self.powerW = 10 ** ((self.measuredPdBm - dB[self.range]) / 10)  # dBm to Watts
        # convert it to display according to meter range selected
        ui.meterWidget.set_MaxValue(1000)
        if self.powerW <= 10:
            ui.meterWidget.set_MaxValue(10)

        if self.powerW >= 10 and self.powerW <= 100:
            ui.meterWidget.set_MaxValue(100)

        # update the analogue gauge widget
        ui.meterWidget.update_value(self.powerW, mouse_controlled=False)
        ui.powerWatts.setValue(self.powerW)
        ui.measurementRate.setValue(self.rate)

        # update the moving pyqtgraph
        powerCurve.setData(meter.xAxis, self.yAxis)

    def setTimebase(self):
        self.samples = ui.memorySize.value() * 1000
        self.xAxis = np.arange(self.samples, dtype=int)  # test
        self.yAxis = np.full(self.samples, -75, dtype=float)  # test

    def autoRange(self):
        # determine if the power units are nW, uW, mW, or W
        self.range = next(index for index, listValue in enumerate(dB) if listValue > self.measuredPdBm)
        if self.range > 0:
            self.range += -1
        ui.powerUnit.setText(str(Units[self.range]))
        ui.powerWatts.setSuffix(str(Units[self.range]))

    def userRange(self):
        # set the units from the main steps of the slider
        self.range = ui.rangeSlider.value()
        ui.powerUnit.setText(Units[int(self.range)])
        ui.powerWatts.setSuffix(Units[int(self.range)])


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
        # self.tm.setEditStrategy(QSqlTableModel.OnManualSubmit)
        self.dwm = QDataWidgetMapper()
        self.dwm.setModel(self.tm)
        self.dwm.setSubmitPolicy(QDataWidgetMapper.ManualSubmit)


    def addRow(self):  # adds a single blank row with autonumbered assetID
        record = self.tm.record()
        record.setGenerated('AssetID', False)  # think this is needed?
        self.tm.insertRecord(-1, record)
        self.tm.submitAll()
        self.updateModel()

    def insertData(self, AssetID, Freq, Loss):  # used by ImportS2P

        # needs error trapping for positive insertion losses **************************************************

        record = self.tm.record()
        record.setValue('AssetID', AssetID)
        record.setValue('Freq MHz', Freq)  # database field is set to MHz
        record.setValue('Value dB', Loss)
        self.tm.insertRecord(-1, record)
        # self.tm.submit()
        self.updateModel()
        app.processEvents()

    # def getID(self):  # no longer needed?
    #     self.id = self.tm.record(self.row).value('AssetID')  # set the Primary Key of the selected row

    # def deleteRow(self, selectedRow, numRows):  # removes numRows rows starting at selectedRow
    #     self.tm.setEditStrategy(QSqlTableModel.OnManualSubmit)
    #     self.tm.removeRows(selectedRow, numRows)
    #     self.tm.submitAll()
    #     self.tm.setEditStrategy(QSqlTableModel.OnRowChange)
    #     self.updateModel()

    # def showParameters(self):  # no longer needed?
    #     # identify which attenuator the user has clicked ('self' is always 'attenuators' when called)
    #     attenuators.row = ui.browseDevices.currentIndex().row()  # set the row index for the currently selected device
    #     self.getID()
    #     # filter to show only matching data from the parameters table
    #     parameters.tm.setFilter('AssetID =' + str(attenuators.id))
    #     parameters.updateModel()

    def updateModel(self):  # what uses this?
        # model must be re-populated when python code changes data
        self.tm.select()
        self.tm.layoutChanged.emit()

    def nextDevice(self):  # user selected next device using arrow button
        self.dwm.toNext()
        parameters.showValues()
        devMark.updateLine(ui.freqIndex)

    def prevDevice(self):  # user selected previous device using arrow button
        self.dwm.toPrevious()
        parameters.showValues()
        devMark.updateLine(ui.freqIndex)

    def nextFreq(self):  # user selected next frequency using arrow button
        self.dwm.toNext()
        devMark.updateLine(ui.freqIndex)
        calMark.updateLine(ui.calFreq)

    def prevFreq(self):  # user selected previous frequency using arrow button
        self.dwm.toPrevious()
        devMark.updateLine(ui.freqIndex)
        calMark.updateLine(ui.calFreq)

    def showValues(self):  # display frequency response (loss) parameters of chosen device
        fValue = []
        lValue = []
        self.tm.setFilter('AssetID =' + str(ui.assetID.value()))  # filter parameter table for the selected device
        self.tm.sort(1, QtCore.Qt.AscendingOrder)  # sort by frequency, ascending
        self.dwm.toFirst()
        # iterate through selected values and display on graph.  Catch error if no data.
        for i in range(0, self.tm.rowCount()):
            fValue.append(self.tm.record(i).value('Freq MHz'))
            lValue.append(self.tm.record(i).value('Value dB'))
        try:
            ui.deviceGraph.setYRange(0, min(lValue))  # user can zoom if they want to
            ui.deviceGraph.setXRange(0, max(fValue))
            deviceCurve.setData(fValue, lValue)
        except ValueError:
            print('Device has no parameters')
            deviceCurve.setData([], [])
            ui.freqIndex.setValue(0)
            ui.loss.setValue(0)
            ui.directivity.setValue(0)

    def addFreqValue(self):
        # print(ui.assetID.value())
        self.insertData(ui.assetID.value(), 0, 0)  # needs to add in the current attenuators.id
        self.tm.setFilter('AssetID =' + str(ui.assetID.value()))
        self.tm.select()
        self.dwm.toLast()

    def saveChanges(self):
        self.dwm.submit()

    def showCal(self):  # display calibration point (slope and intercept) values by frequency
        fValue = []
        iValue = []
        sValue = []
        self.tm.sort(0, QtCore.Qt.AscendingOrder)  # sort by frequency, ascending
        # self.dwm.toFirst()
        # iterate through selected values and display on graph
        for i in range(0, self.tm.rowCount()):
            fValue.append(self.tm.record(i).value('Freq MHz'))
            iValue.append(self.tm.record(i).value('Intercept'))
            sValue.append(self.tm.record(i).value('Slope'))
            sValue[i] = sValue[i]+70  # temporary workaround until I learn how to use two Y-axes
        calIntercept.setData(fValue, iValue)
        calSlope.setData(fValue, sValue)


class Marker():
    '''Create markers for GUI using infinite lines'''

    def __init__(self, graphName):
        # self.Value = markerValue
        self.graphName = graphName
        self.line = self.graphName.addLine()

    def createLine(self, markerFreq):
        markerPen = pyqtgraph.mkPen(color='g', width=0.5)
        self.line = self.graphName.addLine(x=markerFreq, movable=True, pen=markerPen, label="{value:.2f}")
        # self.line.label.setPosition('bottom')

    def updateLine(self, uiFreq):
        # update line value and position to SpinBox settings
        self.line.setValue(uiFreq.value())

    def updateSpinBox(self, uiFreq, modelName):
        # update GUI boxes to discrete value marker was dragged to
        modelName.tm.sort(modelName.tm.fieldIndex('Freq MHz'), QtCore.Qt.AscendingOrder)  # sort by Freq, ascending
        modelName.dwm.toFirst()
        while uiFreq.value() < self.line.value(): # and modelName.dwm.currentIndex()+1 < modelName.tm.rowCount():
            # print(modelName.dwm.currentIndex(), '    ', modelName.tm.rowCount())
            modelName.dwm.toNext()
        self.line.setValue(uiFreq.value())



##############################################################################
# other methods

def exit_handler():
    meter.timer.stop()
    app.processEvents()
    config.disconnect()
    spi.close()
    print('Closed')


def importS2P():
    # Import the (Touchstone) file containing attenuator/coupler/cable calibration data and extract
    # insertion loss or coupling factors by frequency
    index = ui.assetID.value()  # if User clicks arrows during import, data would associate with wrong Device

    # pop up a dialogue box for user to select the file
    s2pFile = QFileDialog.getOpenFileName(None, 'Import s-parameter file for selected device', '', '*.s2p')
    sParam = Touchstone(s2pFile[0])  # use skrf.io method to read file - error trapping needed.  Very slow.

    # extract the device parameters (insertion loss or coupling factors)
    sParamData = sParam.get_sparameter_data('db')
    Freq = sParamData['frequency'].tolist()
    Loss = sParamData['S21DB'].tolist()

    # filter on parameter values for the currently selected Device and delete existing ones
    parameters.tm.setFilter('AssetID =' + str(index))
    if not ui.appendS2P.isChecked():
        parameters.deleteRow(0, parameters.tm.rowCount())  # is very slow

    # insert the nominal value to the Device data ***** shows on GUI but doesnt update database **** fix later ********
    ui.nominaldB.setValue(Loss[int(len(Freq)/2)])

    # read the frequency and S21db data from the lists and insert into SQL database rows
    for i in range(len(Freq)):
        parameters.insertData(index, Freq[i] / 1e6, Loss[i])
        parameters.showValues()


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
        parameters.tm.sort(1, 0)  # sort by frequency, ascending: required for numpy interpolate
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
            ui.calQualLabel.setText(calRecord.value('CalQuality') + " " + str(int(calRecord.value('Freq MHz'))) + "MHz")


def popUp(message, button):
    msg = QMessageBox(parent=(window))
    msg.setIcon(QMessageBox.Warning)
    msg.setText(message)
    msg.addButton(button, QMessageBox.ActionRole)
    msg.exec_()

##############################################################################
# respond to GUI signals


def delDevices():  # no longer needed?
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


def addDevice():
    attenuators.addRow()
    attenuators.dwm.toLast()


def addParameter():
    attenuators.row = ui.browseDevices.currentIndex().row()  # set the row index for the currently selected device
    attenuators.getID()
    parameters.insertData(attenuators.id, 0, 0)


def deleteParameter():
    parameters.row = ui.deviceParameters.currentIndex().row()  # set the row index for the currently selected paranmeter
    parameters.deleteRow(parameters.row, 1)


def calibrate():
    # calibration.row = ui.calTable.currentIndex().row()  # set the row index for the currently selected calibration
    # record = calibration.tm.record(calibration.row)

    record = calibration.tm.record(calibration.dwm.currentIndex())  # table model record for the displayed freq
    # slope = (record.value('High Code')-record.value('Low Code'))/((record.value('Cal High dBm')-record.value('Cal Low dBm')))
    # intercept = record.value('Cal High dBm')-(record.value('High Code')/slope)

    slope = (ui.highCode.value()-ui.lowCode.value())/(ui.highRef.value()-ui.lowRef.value())
    intercept = (ui.highRef.value()-ui.lowRef.value())/slope
    record.setValue('Slope', slope)
    record.setValue('Intercept', intercept)
    calibration.tm.setRecord(calibration.row, record)  # append the contents of 'record' to the table via the model
    calibration.updateModel()


def deleteCal():
    calibration.row = ui.calTable.currentIndex().row()  # set the row index for the currently selected calibration
    calibration.deleteRow(calibration.row, 1)


def updateCal(str):
    try:
        openSPI()
    except FileNotFoundError:
        popUp('No SPI device found', 'OK')
    else:
        record = calibration.tm.record(calibration.dwm.currentIndex())  # table model record for the displayed freq
        meter.setTimebase()  # why?
        meter.readSPI()
        record.setValue(str, meter.dIn)
        calibration.tm.setRecord(calibration.row, record)  # append the contents of 'record' to the table via the model
        calibration.updateModel()
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
        # ui.sensorOverload.setText('')
        activeButtons(False)
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

    # update the analog gauge widget
    ui.meterWidget.update_value(0, mouse_controlled=False)
    ui.powerWatts.setValue(0)
    ui.measurementRate.setValue(0)
    ui.sensorPower.setValue(-70)
    ui.inputPower.setValue(-70)
    activeButtons(True)

    attenuators.tm.setFilter('')  # remove all filters
    attenuators.updateModel()  # probably not necessary
    parameters.tm.setFilter('')  # remove all filters
    parameters.updateModel()  # probably not necessary
    spi.close()


def slidersMoved():
    if meter.timer.isActive():
        stopMeter()
        startMeter()


def freqChanged():
    if meter.timer.isActive():
        stopMeter()
        startMeter()
    else:
        userFreq()
    # deselect band radio buttons
    if ui.hamBands.checkedId() != -11:
        ui.GHzSlider.setEnabled(False)
        ui.freqBox.setEnabled(False)


def bandSelect():
    buttonID = ui.hamBands.checkedId()
    if buttonID == -11:
        ui.GHzSlider.setEnabled(True)
        ui.freqBox.setEnabled(True)
        return
    buttonID = (-buttonID)-2  # exclusive group button index starts at -2 and decreases. Convert to list index.
    ui.GHzSlider.setValue(fBand[buttonID])
    ui.freqBox.setValue(fBand[buttonID])


def userFreq():
    sumLosses()
    selectCal()
    attenuators.tm.setFilter('')  # is this needed?
    attenuators.tm.select()
    attenuators.dwm.toFirst()
    parameters.tm.select()
    parameters.dwm.toFirst()
    parameters.showValues()
    calibration.showCal()


def rangeSelect():
    if ui.setRangeButton.isChecked():
        ui.rangeSlider.setEnabled(True)
    else:
        ui.rangeSlider.setEnabled(False)


def addFreqVal():
    parameters.addFreqValue()  # needs to add in the current attenuators.id
    parameters.dwm.toLast()


def measHCode():
    updateCal('High Code')


def measLCode():
    updateCal('Low Code')


def calMarkerMoved():
    calMark.updateSpinBox(ui.calFreq, calibration)


def activeButtons(tF):
    # prevent User button presses that may affect readings when meter is running
    ui.saveDevice.setEnabled(tF)
    ui.loadS2P.setEnabled(tF)
    ui.saveValues.setEnabled(tF)
    ui.measHigh.setEnabled(tF)
    ui.measLow.setEnabled(tF)
    ui.addDevice.setEnabled(tF)
    ui.deleteDevice.setEnabled(tF)
    ui.addFreq.setEnabled(tF)
    ui.delFreq.setEnabled(tF)
    ui.calibrate.setEnabled(tF)
    ui.saveCal.setEnabled(tF)
    ui.addCal.setEnabled(tF)
    ui.deleteCal.setEnabled(tF)


##############################################################################
# instantiate classes

config = database()
config.connect()
meter = Measurement()
attenuators = modelView("Device")
calibration = modelView("calibration")
parameters = modelView("deviceParameters")
app = QtWidgets.QApplication([])  # create QApplication for the GUI
window = QtWidgets.QMainWindow()
ui = QtPowerMeter.Ui_MainWindow()
ui.setupUi(window)
devMark = Marker(ui.deviceGraph)
calMark = Marker(ui.calGraph)

##############################################################################
# GUI settings and interfaces

# adjust analog gauge meter
ui.meterWidget.set_MaxValue(10)
ui.meterWidget.set_enable_CenterPoint(enable=False)
ui.meterWidget.set_enable_barGraph(enable=True)
ui.meterWidget.set_enable_value_text(enable=False)
ui.meterWidget.set_enable_filled_Polygon(enable=True)
ui.meterWidget.set_start_scale_angle(90)
ui.meterWidget.set_total_scale_angle_size(270)

# pyqtgraph settings for power vs time display
red = pyqtgraph.mkPen(color='r', width=1.0)
blue = pyqtgraph.mkPen(color='c', width=0.5, style=QtCore.Qt.DashLine)
yellow = pyqtgraph.mkPen(color='y', width=1.0)
ui.graphWidget.setYRange(-60, 10)
ui.graphWidget.setBackground('k')  # black
ui.graphWidget.showGrid(x=True, y=True)
ui.graphWidget.addLine(y=10, movable=False, pen=red, label='max', labelOpts={'position':0.05, 'color':('r')})
ui.graphWidget.addLine(y=-5, movable=False, pen=blue, label='', labelOpts={'position':0.025, 'color':('c')})
ui.graphWidget.addLine(y=-50, movable=False, pen=blue, label='', labelOpts={'position':0.025, 'color':('c')})
ui.graphWidget.setLabel('left', 'Sensor Power', 'dBm')
ui.graphWidget.setLabel('bottom', 'Power Measurement', 'Samples')
powerCurve = ui.graphWidget.plot([], [], name='Sensor', pen=yellow, width=1)

# pyqtgraph settings for device parameters display
ui.deviceGraph.setYRange(0, -40, padding=0)
ui.deviceGraph.setXRange(0, 3000, padding=0)
ui.deviceGraph.showGrid(x=True, y=True)
ui.deviceGraph.setBackground('k')  # white
ui.deviceGraph.setLabel('left', 'Gain', 'dB')
ui.deviceGraph.setLabel('bottom', 'Frequency', '')
# ui.deviceGraph.addLine(x=0, movable=True, pen=red, label='freq', labelOpts={'position':0.05, 'color':('r')})
deviceCurve = ui.deviceGraph.plot([], [], name='Parameters', pen=red, width=4)
devMark.createLine(50)

# pyqtgraph settings for clibration display
ui.calGraph.addLegend(offset=(825, 10))
calSlope = ui.calGraph.plot([], [], name='slope', pen=red, width=6, symbol='x')
# ui.calGraph.addLegend()
calIntercept = ui.calGraph.plot([], [], name='intercept', width=6, symbol='x')
ui.calGraph.setXRange(0, 3200, padding=0)
ui.calGraph.showGrid(x=True, y=True)
ui.calGraph.setBackground('k')  # white
ui.calGraph.setLabel('bottom', 'Sensor Calibration Point Frequency', '')
calMark.createLine(1296)

# Connect signals from buttons ################################################

# update display attenuation when tabs changed
ui.tabWidget.currentChanged.connect(userFreq)

# attenuators, couplers and cables    *******************add/delete needed *************
ui.nextDevice.clicked.connect(attenuators.nextDevice)
ui.previousDevice.clicked.connect(attenuators.prevDevice)
ui.saveDevice.clicked.connect(attenuators.saveChanges)
ui.addDevice.clicked.connect(addDevice)

ui.nextFreq.clicked.connect(parameters.nextFreq)
ui.previousFreq.clicked.connect(parameters.prevFreq)
ui.addFreq.clicked.connect(parameters.addFreqValue)
ui.saveValues.clicked.connect(parameters.saveChanges)
ui.loadS2P.clicked.connect(importS2P)

# calibration
# ui.addCalData.clicked.connect(calibration.addRow)
# ui.deleteCal.clicked.connect(deleteCal)
ui.prevCal.clicked.connect(calibration.prevFreq)
ui.nextCal.clicked.connect(calibration.nextFreq)
ui.saveCal.clicked.connect(calibration.saveChanges)
ui.measHigh.clicked.connect(measHCode)
ui.measLow.clicked.connect(measLCode)
ui.calibrate.clicked.connect(calibrate)
calibration.showCal

# start and stop
ui.runButton.clicked.connect(startMeter)
ui.stopButton.clicked.connect(stopMeter)

# touchscreen controls
ui.freqBox.valueChanged.connect(freqChanged)
ui.memorySize.valueChanged.connect(slidersMoved)
ui.averaging.valueChanged.connect(slidersMoved)
ui.hamBands.buttonClicked.connect(bandSelect)
ui.rangeSlider.valueChanged.connect(meter.userRange)
ui.autoRangeButton.clicked.connect(rangeSelect)
ui.setRangeButton.clicked.connect(rangeSelect)
devMark.line.sigPositionChanged.connect(lambda: devMark.updateSpinBox(ui.freqIndex, parameters))
# calMark.line.sigPositionChanged.connect(lambda: calMark.updateSpinBox(ui.calFreq, calibration))
calMark.line.sigPositionChanged.connect(calMarkerMoved)

##############################################################################
# set up the application

attenuators.createTableModel()  # attenuator/coupler etc devices
attenuators.dwm.addMapping(ui.assetID, 0)
attenuators.dwm.addMapping(ui.description, 1)
attenuators.dwm.addMapping(ui.partNum, 2)
attenuators.dwm.addMapping(ui.identifier, 3)
attenuators.dwm.addMapping(ui.maxPower, 4)
attenuators.dwm.addMapping(ui.nominaldB, 5)
attenuators.dwm.addMapping(ui.inUse, 8)
# attenuators.tm.select()
# attenuators.dwm.toFirst()

calibration.createTableModel()
calibration.dwm.addMapping(ui.calFreq, 0)
calibration.dwm.addMapping(ui.lowRef, 1)
calibration.dwm.addMapping(ui.highRef, 2)
calibration.dwm.addMapping(ui.highCode, 3)
calibration.dwm.addMapping(ui.lowCode, 4)
calibration.dwm.addMapping(ui.slope, 5)
calibration.dwm.addMapping(ui.intercept, 6)
calibration.dwm.addMapping(ui.refMeter, 7)

parameters.createTableModel()  # loss vs frequency for each device
parameters.dwm.addMapping(ui.freqIndex, 1)
parameters.dwm.addMapping(ui.loss, 2)
parameters.dwm.addMapping(ui.directivity, 3)
# parameters.tm.select()
# parameters.dwm.toFirst()

meter.timer.timeout.connect(readMeter)  # A Qtimer defined in the Measurement Class init
window.show()

##############################################################################
# run the application until the user closes it

try:
    app.exec()
finally:
    exit_handler()  # close database
