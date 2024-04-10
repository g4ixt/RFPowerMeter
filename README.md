# RF Power Meter

Python AD8318 RF Power Meter application for the Raspberry Pi using a PyQT5 GUI.  Multi-threaded and capable of over 45,000 measurements per second when using a Pi4b, or 12,000 using a Pi3b.

The AD8318 Digital RF Power Detector pcb is by made by SV1AFN and communicates with the Pi using SPI.  Calibration and Attenuator data is stored in a SQLite database.  https://www.sv1afn.com/en/products/ad8318-digital-rf-power-detector.html
  
![Display_tab__20230108_215539](https://github.com/g4ixt/RFPowerMeter/assets/76836635/11034406-7b20-4d46-990b-4ca77bc0434a)
  
## Note: The AD7887 ADC on the PCB has a 5V supply.
It must not be directly connected to the Pi GPIO SPI which operates at 3.3V.  I changed R5 to 180R and put a 3.3V zener diode across C9 (soldered directly across pins 2 and 3 of the AD7887) to reduce Vdd to 3.3V.  See picture.

I also added an electrolytic and 10nF decoupling capacitors to the sensor power line and this made significant improvements to 'noise' spi measurements, essentially eliminating them.  I also removed the paint on the enclosure lids and end caps to improve grounding.  Running it from a battery made no difference.

# Install and run
Tested on Raspberry Pi3b running a clean installation of 32-bit Raspbian Buster 5.10.63-v7+ and on 5.10.103-v7+

Dependencies: Install from the repository - python3-pyqt5, python3-numpy, python3-spidev, python3-pyqtgraph

SPI must be enabled using Raspberry Pi Configuration on the Preferences menu, and the user must be in the spi and dialout groups.

A simplified subset of the code touchstone.py from scikit-rf, an open-source Python package for RF and Microwave applications, is included here.  This was necessary for Raspberry Pi without having to install the full scikit-rf, since this appears to be incompatible with PiOS 'Buster'.  It is used to import 's2p' files in a suitable format from NanoVNA-F_V2 or similar hardware.

To run:

cd {to folder containing code}
python3 meRF.py

You can connect via ssh -X to the Pi ip address and the X GUI will be on the local machine.  For example:

ssh -X ian@192.168.1.150
<enter password>  
cd RFPowerMeter  
python3 meRF.py

# Usage

The windows are designed for a 1024x600 display and I have tried to make them touch-screen friendly.  There are 3 tabs: Display, Devices and Calibration.

## Display tab

Contains an analogue-style meter with pointer and adjustable averaging, up to 5,000 samples, and a time-power moving display with adjustable 'memory size' of up to 100,000 samples. The sensor must be calibrated  at different frequencies, hence it is necessary to specify the frequency for which RF measurement is required. Frequencies can be set using radio buttons for the amateur bands up to 6cm, or to a specific frequency using the slider. The AD8318 sensor has an absolute maximum input power (damage level) of +10dBm but becomes less linear between -10dBm and 0dBm and for this reason a reminder not to exceed 0dBm is shown in red next to the 'Run' button.  It does not matter if the programme is running or not, if the Ad8318 sensor input power maximum is exceeded it will be damaged.

The analogue-style meter can be set to auto or manual scale using radio buttons and a slider.  Manual range settings are nW, uW, mW, W, kW.

The time-power moving display shows the sensor power only, not taking into account any selected attenuation. A red horizontal line at 0dBm labelled 'max' is there as a reminder. Dotted blue horizontal lines show the optimum linear range of the sensor and are intended to be the nominal power calibration points. A vertical green frequency marker is provided which can be dragged to different points.  Either or both axes can be zoomed, using a mouse, with or without measurement running.  To restore, click on the 'A' on bottom left corner of graph.  This is a standard feature provided by pyqtgraph.

The lower part of the screen shows the sensor power and the total attenuation which has been set 'in use' on the Devices tab, along with the RF power calculated from the sensor power and total attenuation.  The current measurement sample rate is also shown.  This is affected by meter Averaging and Memory Size.  On a Pi3B the maximum is around 9,000 Samples/second and the minimum around 3,500S/s.

## Devices tab

Devices are cables, couplers, attenuators, filters etc., that are to be used in series with the AD8318 power sensor and the device under test. Device details are entered with information to identify them in future and the 'Save Changes' button pressed. Performance data for each device can be entered 'by hand' for discrete frequencies, or from a measurement S2P file, e.g. from a NanoVNA.  As many devices as desired may be entered and only those used for the measurement set as 'in use' each time.  The information is stored in a SQLite database file. 

S2P import was tested only with files from a Sysjoint NanoVNA-F V2.

As each device is selected using the < and > buttons, the insertion loss graph of the device is shown.

Note: The 'directivity' box is not used at present.

## Calibration tab

A similar format to the Devices tab.  The sensor must be calibrated using a known reference power meter.  'Add Freq' adds a new calibration point frequency, for which the reference high and low known RF powers from the reference meter must be entered and saved. The two powers are them measured using the AD8318 sensor and the resulting ADC codes are stored in the database.  For each frequency, the 'Calibrate' button is pressed and the Slope and Intercept are calculated, this data is saved and stored in the SQLite database.

The calculated Slope is displayed on a graph for all calibration frequencies. Data sheet maximum and minimum slope values are also shown on the graph.  The red line for the sensor should lie inside the specification lines.

The slope and intercept are used along with the device total insertion loss to calculate the RF power on the Display tab.
