### How to Install Python 3.10

1. Visit the official Python website's download page for Windows at https://www.python.org/downloads/windows/.
2. Click on the link for the Latest Python 3 Release - Python 3.10.x.
3. Scroll to the bottom and select either Windows x86-64 executable installer for 64-bit or Windows x86 executable installer for 32-bit.
4. Run the installer file and follow the setup instructions. Make sure to check the box that says Add Python 3.10 to PATH before you click Install Now.

### How to Install npm

1. Download Node.js from the official site https://nodejs.org/en/download/.
2. Run the installer (the .msi installer is recommended).
3. Follow the prompts in the installer (Accept the license agreement, click the NEXT button a bunch of times and accept the default installation settings).
4. Restart your computer. You won’t be able to run Node.js® until you restart your computer.

### Usage of the Supplied bat Files

#### install.bat

This batch file is used to set up the project on your local machine. It creates a virtual environment, activates it, installs poetry, and uses poetry to install dependencies. It then navigates to the frontend directory and installs the necessary npm packages.

To run this file, simply double click on it or open a command prompt in the same directory and type `install.bat`.

#### start.bat

This batch file is used to start the backend and frontend servers. It opens two command prompts, one for the frontend and one for the backend.

To run this file, simply double click on it or open a command prompt in the same directory and type `start.bat`.