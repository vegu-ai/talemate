import io
import base64
from PIL import Image
import httpx
import structlog

from .handlers import register
from .schema import Resolution
from .style import STYLE_MAP

log = structlog.get_logger("talemate.agents.visual.automatic1111")


@register(backend_name="automatic1111", label="AUTOMATIC1111")
class Automatic1111Mixin:
    
    async def automatic1111_generate(self, prompt:str, resolution:Resolution):
        url = self.api_url
        render_settings = self.render_settings
        style = self.style
        prompt = f"{style}, {prompt}"
        payload = {
            "prompt": prompt,
            "negative_prompt": str(STYLE_MAP["negative_prompt_1"]),
            "steps": render_settings.steps,
            "width": resolution.width,
            "height": resolution.height,
        }
        
        
        log.info("automatic1111_generate", payload=payload, url=url)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url=f'{url}/sdapi/v1/txt2img', json=payload, timeout=90)
            
        r = response.json()
        
        image = Image.open(io.BytesIO(base64.b64decode(r['images'][0])))
        image.save('a1111-test.png')
        
        log.info("automatic1111_generate", saved_to="a1111-test.png")
            