import os
from pathlib import Path
from openai import OpenAI
import base64

# Load .env
env_path = Path('.env')
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1)
            os.environ[key.strip()] = val.strip()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
)

# 1 pixel png
b64_img = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

models_to_test = [
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "google/gemma-3-27b-it:free",
]

for model in models_to_test:
    print(f"Testing {model}...")
    try:
        response = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "https://test.local",
                "X-Title": "Test",
            },
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "What is the color of this pixel?"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64_img}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=50
        )
        print(f"SUCCESS {model}: {response.choices[0].message.content.strip()}")
    except Exception as e:
        print(f"FAILED {model}: {e}")
