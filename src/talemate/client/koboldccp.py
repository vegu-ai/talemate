import asyncio
import random
import json
import logging
from abc import ABC, abstractmethod
from typing import Callable, Union

import requests

import talemate.util as util
from talemate.client.registry import register
import talemate.client.system_prompts as system_prompts
from talemate.client.textgenwebui import RESTTaleMateClient
from talemate.emit import Emission, emit

# NOT IMPLEMENTED AT THIS POINT