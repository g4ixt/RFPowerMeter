# RF Power Meter

Python AD8318 RF Power Meter application for the Raspberry Pi using a PyQT5 GUI.  Uses multi-processing to make over 35,000 measurements per second when using a Pi4b, or 10,000 using a Pi3b.
Calibration and Attenuator data is stored in a SQLite database.

The AD8318 Digital RF Power Detector pcb is by made by SV1AFN and communicates with the Pi using SPI. https://www.sv1afn.com/en/products/ad8318-digital-rf-power-detector.html
  
<img width="1023" height="560" alt="image" src="https://github.com/user-attachments/assets/29faf89d-113c-4227-84ee-eed1b4dd8a8b" />

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

The windows are designed for a 1024x600 display.

## Meter view

Contains an analogue-style meter with pointer and adjustable time interval for paek or average processing, up to 10s.   There is a time-power moving display with adjustable 'time points' of up to 250,000 samples which is enough for about 6 seconds of display at maximum measurement rate.
  
The sensor calibration varies with frequency, so the frequency of the RF to be measured is required. The AD8318 sensor has an absolute maximum input power (damage level) of +10dBm but becomes less linear between -10dBm and 0dBm and for this reason a reminder not to exceed 0dBm is shown in red on the graph.  It does not matter if the programme is running or not, if the Ad8318 sensor input power maximum is exceeded it will be damaged.

The analogue-style meter range can be set to auto or manual scales using comboboxes.

The time-power moving display shows the sensor power only, not taking into account any selected attenuation. A red horizontal line at 0dBm labelled 'max' is there as a reminder. Dotted blue horizontal lines show the optimum linear range of the sensor and are intended to be the nominal power calibration points. Either or both axes can be zoomed, using a mouse, with or without measurement running.  To restore, click on the 'A' on bottom left corner of graph.  This is a standard feature provided by pyqtgraph.

The screen shows the sensor power and the total attenuation which has been set 'in use' on the Devices tab, along with the RF power calculated from the sensor power and total attenuation.  The current measurement sample rate is also shown below the meter.  The measurement rate can be adjusted with the SPI speed combobox - on my system anything over 976562 results in SPI data errors.

## Devices view

Devices are cables, couplers, attenuators, filters etc., used in series with the AD8318 power sensor and the device under test. Device details are entered with information to identify them. Performance data for each device can be entered 'by hand' for discrete frequencies, or from a measurement S2P file, e.g. from a NanoVNA.  As many devices as desired may be entered and only those used for the measurement set as 'in use' each time.  The information is stored in a SQLite database file. 

S2P import was tested only with files from a Sysjoint NanoVNA-F V2.

As each device is selected its insertion loss graph is shown.

Note: The 'directivity' box is not used at present.

## Calibration view

The sensor must be calibrated using known reference power meter(s).  'Add Freq' adds a new calibration point frequency, for which the reference high and low known RF powers from the reference meter must be entered and saved. The two powers are them measured using the AD8318 sensor and the resulting ADC codes are stored in the database.  For each frequency, the 'Calibrate' button is pressed and the Slope and Intercept are calculated, this data is saved and stored in the SQLite database.

The calculated Slope is displayed on a graph for all calibration frequencies. Data sheet maximum and minimum slope values are also shown on the graph.  The red line for the sensor should lie inside the specification lines.

The slope and intercept are used along with the device total insertion loss to calculate the RF power on the Display tab.
