import base64
import io
import re
import struct
import structlog
from PIL import Image
import json

log = structlog.get_logger("talemate.util.image")

__all__ = [
    "fix_unquoted_keys",
    "extract_metadata",
    "read_metadata_from_png_text",
    "chara_read",
]


def fix_unquoted_keys(s):
    unquoted_key_pattern = r"(?<!\\)(?:(?<=\{)|(?<=,))\s*(\w+)\s*:"
    fixed_string = re.sub(
        unquoted_key_pattern, lambda match: f' "{match.group(1)}":', s
    )
    return fixed_string


def extract_metadata(img_path, img_format):
    return chara_read(img_path)


def read_metadata_from_png_text(image_path: str) -> dict:
    """
    Reads the character metadata from the tEXt chunk of a PNG image.
    Supports both chara_card_v3 (ccv3 chunk) and older formats (chara chunk).
    Per v3 spec, if both exist, prefer ccv3.
    """

    # Read the image
    with open(image_path, "rb") as f:
        png_data = f.read()

    # Split the PNG data into chunks
    offset = 8  # Skip the PNG signature
    ccv3_data = None
    chara_data = None

    while offset < len(png_data):
        length = struct.unpack("!I", png_data[offset : offset + 4])[0]
        chunk_type = png_data[offset + 4 : offset + 8]
        chunk_data = png_data[offset + 8 : offset + 8 + length]
        if chunk_type == b"tEXt":
            keyword, text_data = chunk_data.split(b"\x00", 1)
            if keyword == b"ccv3":
                ccv3_data = text_data
            elif keyword == b"chara":
                chara_data = text_data
        offset += 12 + length

    # Per v3 spec, prefer ccv3 if both exist
    if ccv3_data:
        return json.loads(base64.b64decode(ccv3_data).decode("utf-8"))
    elif chara_data:
        return json.loads(base64.b64decode(chara_data).decode("utf-8"))

    raise ValueError("No character metadata found.")


def chara_read(img_url, input_format=None):
    if input_format is None:
        if ".webp" in img_url:
            format = "webp"
        else:
            format = "png"
    else:
        format = input_format

    with open(img_url, "rb") as image_file:
        image_data = image_file.read()
        image = Image.open(io.BytesIO(image_data))

    exif_data = image.getexif()
    if format == "webp":
        try:
            if 37510 in exif_data:
                try:
                    description = exif_data[37510].decode("utf-8")
                except AttributeError:
                    description = fix_unquoted_keys(exif_data[37510])

                try:
                    char_data = json.loads(description)
                except Exception:
                    byte_arr = [int(x) for x in description.split(",")[1:]]
                    uint8_array = bytearray(byte_arr)
                    char_data_string = uint8_array.decode("utf-8")
                    return json.loads("{" + char_data_string)
            else:
                log.warn("chara_load", msg="No chara data found in webp image.")
                return False

            return char_data
        except Exception:
            raise

    elif format == "png":
        with Image.open(img_url) as img:
            img_data = img.info

            # Per v3 spec, prefer ccv3 if both exist
            if "ccv3" in img_data:
                base64_decoded_data = base64.b64decode(img_data["ccv3"]).decode("utf-8")
                return json.loads(base64_decoded_data)
            elif "chara" in img_data:
                base64_decoded_data = base64.b64decode(img_data["chara"]).decode(
                    "utf-8"
                )
                return json.loads(base64_decoded_data)
            if "comment" in img_data:
                base64_decoded_data = base64.b64decode(img_data["comment"]).decode(
                    "utf-8"
                )
                return base64_decoded_data
            else:
                log.warn("chara_load", msg="No chara data found in PNG image.")
                log.warn("chara_load", msg="Trying to read from PNG text.")

                try:
                    return read_metadata_from_png_text(img_url)
                except ValueError:
                    return False
                except Exception as exc:
                    log.error(
                        "chara_load",
                        msg="Error reading metadata from PNG text.",
                        exc_info=exc,
                    )
                    return False
    else:
        return None
