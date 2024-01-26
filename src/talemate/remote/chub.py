"""
Util to search and download character card images from the characterhub.org API.



"""

import os

import requests

from talemate.emit import emit


class CharacterHub:
    def __init__(self):
        self.api_url = "https://v2.chub.ai"
        self.search_url = f"{self.api_url}/search"
        self.download_url = "https://api.chub.ai/api/v4/projects/{node_id}/repository/files/raw%252Ftavern_raw.png/raw?ref=main&response_type=blob"

    def search(self, search):
        params = {
            "nsfw": "true",
            "search": search,
        }

        result = requests.get(self.search_url, params=params)
        for node in result.json()["data"]["nodes"]:
            yield node

    def download(self, node):
        # download the image and save to tales/characters

        url = self.download_url.format(node_id=node["id"])

        result = requests.get(url)

        # save the image to the characters folder

        filename = node["name"].replace(" ", "_").lower()

        if not os.path.exists("scenes/characters"):
            os.makedirs("scenes/characters")

        with open(f"scenes/characters/{filename}.png", "wb") as f:
            f.write(result.content)

        emit("system", f"Downloaded {filename}.png")
