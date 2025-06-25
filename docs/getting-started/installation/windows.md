## Quick install instructions

1. Download and install Python 3.10 - 3.13 from the [official Python website](https://www.python.org/downloads/windows/).
    - [Click here for direct link to python 3.11.9 download](https://www.python.org/downloads/release/python-3119/)
    - June 2025: people have reported issues with python 3.13 still, due to some dependencies not being available yet, if you run into issues during installation try downgrading.
1. Download and install Node.js from the [official Node.js website](https://nodejs.org/en/download/prebuilt-installer). This will also install npm.
1. Install uv by running `pip install uv` in a command prompt.
1. Download the Talemate project to your local machine. Download from [the Releases page](https://github.com/vegu-ai/talemate/releases).
1. Unpack the download and run `install.bat` by double clicking it. This will set up the project on your local machine.
1. **Optional:** If you are using an nvidia graphics card with CUDA support you may want to also run `install-cuda.bat` **afterwards**, to install the cuda enabled version of torch - although this is only needed if you want to run some bigger embedding models where CUDA can be helpful.
1. Once the installation is complete, you can start the backend and frontend servers by running `start.bat`.
1. Once the talemate logo shows up, navigate your browser to http://localhost:8080

!!! note "First start up may take a while"
    We have seen cases where the first start of talemate will sit at a black screen for a minute or two. Just wait it out, eventually the Talemate logo should show up.

If everything went well, you can proceed to [connect a client](../../connect-a-client).

## Additional Information

### How to Install Python

--8<-- "docs/snippets/common.md:python-versions"

1. Visit the official Python website's download page for Windows at [https://www.python.org/downloads/windows/](https://www.python.org/downloads/windows/).
2. Find the latest updated of Python 3.13 and click on one of the download links. (You will likely want the Windows installer (64-bit))
4. Run the installer file and follow the setup instructions. Make sure to check the box that says Add Python 3.13 to PATH before you click Install Now.

### How to Install npm

1. Download Node.js from the official site [https://nodejs.org/en/download/prebuilt-installer](https://nodejs.org/en/download/prebuilt-installer).
2. Run the installer (the .msi installer is recommended).
3. Follow the prompts in the installer (Accept the license agreement, click the NEXT button a bunch of times and accept the default installation settings).

### Usage of the Supplied bat Files

#### install.bat

This batch file is used to set up the project on your local machine. It creates a virtual environment using uv and installs dependencies. It then navigates to the frontend directory and installs the necessary npm packages.

To run this file, simply double click on it or open a command prompt in the same directory and type `install.bat`.

#### update.bat

If you are inside a git checkout of talemate you can use this to pull and reinstall talemate if there have been updates.

!!! note "CUDA needs to be reinstalled manually"
    Running `update.bat` will downgrade your torch install to the non-CUDA version, so if you want CUDA support you will need to run the `install-cuda.bat` script after the update is finished.

#### start.bat

This batch file is used to start the backend and frontend servers.

To run this file, simply double click on it or open a command prompt in the same directory and type `start.bat`.