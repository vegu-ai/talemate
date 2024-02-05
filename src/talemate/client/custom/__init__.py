import importlib
import os

import structlog

log = structlog.get_logger("talemate.client.custom")

# import every submodule in this directory
#
# each directory in this directory is a submodule

# get the current directory
current_directory = os.path.dirname(__file__)

# get all subdirectories
subdirectories = [
    os.path.join(current_directory, name)
    for name in os.listdir(current_directory)
    if os.path.isdir(os.path.join(current_directory, name))
]

# import every submodule

for subdirectory in subdirectories:
    # get the name of the submodule
    submodule_name = os.path.basename(subdirectory)

    if submodule_name.startswith("__"):
        continue

    log.info("activating custom client", module=submodule_name)

    # import the submodule
    importlib.import_module(f".{submodule_name}", __package__)
