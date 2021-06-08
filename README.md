# RF Power Meter
Python AD8318 RF Power Meter application for the Raspberry Pi

A RF Power Meter programme in Python using the AD8318 Digital RF Power Detector pcb by made by SV1AFN, communicating with the Pi using SPI.

https://www.sv1afn.com/en/products/ad8318-digital-rf-power-detector.html

Ideas / reminders:

AnalogGaugeWidgetPyQT

Calibration saving including view and update.  Intercept point?

Frequency setting (needed for AD8318 optimum accuracy)

Cable attenuation compensation

Attenuator offset scaling of readout

Store, retrieve, update, delete 'known' attenuator/cable calibration data

Peak Hold with reset

Average over selected number of samples

Interface to LimeSDR VNA programme for swept power plotting (if it's faster than LimeSDR receive)

dBm / Watts display simultaneously

Power vs time graph in realtime with axes calibrated respecting attenuator & cable settings

Notification of input signal outside best dynamic range

