import asyncio
import json
import logging
import random
from abc import ABC, abstractmethod
from typing import Callable, Union

import requests

import talemate.client.system_prompts as system_prompts
import talemate.util as util
from talemate.client.registry import register
from talemate.client.textgenwebui import RESTTaleMateClient
from talemate.emit import Emission, emit

# NOT IMPLEMENTED AT THIS POINT
