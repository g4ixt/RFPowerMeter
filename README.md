# RF Power Meter

Python AD8318 RF Power Meter application for the Raspberry Pi using a PyQT5 GUI.  Multi-threaded and capable of over 7,000 measurements per second.

The AD8318 Digital RF Power Detector pcb is by made by SV1AFN and communicates with the Pi using SPI.  Calibration and Attenuator data is stored in a sqlite database.  https://www.sv1afn.com/en/products/ad8318-digital-rf-power-detector.html

![image](/Pictures/Screenshot_20220615_161224.png)

* Note: the AD7887 ADC is operating at 5V, this should not be directly connected to the Pi GPIO which operates at 3.3V

Tested on Raspberry Pi3b running a clean installation of 32-bit Raspbian Buster 5.10.63-v7+

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

Enter the frequency on the display tab and press 'run'.
The 'averaging' setting affects the analogue gauge meter only.
The 'memory depth' setting controls the number of points shown on the moving graph and can be set up to maximum of 100,000 (for no particular reason).
  
You can zoom in and out of either axis on the moving graph, using the mouse, with or without measurements running.  To restore, click on the 'A' on bottom left corner of graph.  This is a standard feature provided by pyqtgraph.

To calibrate:
Enter the frequency and the known powers 'cal high' and cal low' in dBm.  Feed sensor with the known 'high' power, select 'high code' and press measure.  Similar for the known low power.
  
You have to tab out of the row to get the database to update.

Once both values are measured, click in the row and press the calibrate button

The slope and intercept should populate.

To add attenuators or couplers:
Add a row in the 'devices' table, enter details, tab or click in another row.
Add a row or import s2p for the selected device and tab or click another row.
Enter '1' in the 'inUse' column to have attenuator or couplers included in the power calculation on the display tab.

To do:
More instructions
Improve calibrate and attenuator tabs.  They work but not without quirks.

I added an electrolytic and 10nF decoupling capacitors to the sensor power line and this made significant improvements to 'noise' spi measurements, essentially eliminating them.  I also removed the paint on the enclosure lids and end caps to improve grounding.  Running it from a battery made no difference.
