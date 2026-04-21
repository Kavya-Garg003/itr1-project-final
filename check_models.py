import os
from pathlib import Path
from openai import OpenAI

# Load .env
env_path = Path('.env')
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1)
            os.environ[key.strip()] = val.strip()

try:
    c_groq = OpenAI(api_key=os.environ.get('GROQ_API_KEY'), base_url='https://api.groq.com/openai/v1')
    print("GROQ Models:")
    models = c_groq.models.list().data
    for m in models:
        # Just scan for 3.2 or vision
        if '3.2' in m.id.lower() or 'vision' in m.id.lower():
            print(m.id)
except Exception as e:
    print(f"Groq error: {e}")

try:
    c_openrouter = OpenAI(api_key=os.environ.get('OPENROUTER_API_KEY'), base_url='https://openrouter.ai/api/v1')
    print("\nOpenRouter Models (free vision):")
    # OpenRouter doesn't expose list elegantly for free filter easily without raw requests, we'll just check models
    import requests
    r = requests.get("https://openrouter.ai/api/v1/models")
    if r.status_code == 200:
        data = r.json().get('data', [])
        for m in data:
            if 'free' in m['id'].lower() and ('vision' in m['id'].lower() or 'vl' in m['id'].lower() or 'llama-3.2' in m['id'].lower()):
                print(m['id'])
except Exception as e:
    print(f"OpenRouter error: {e}")
