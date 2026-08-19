import os
import requests

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_ENDPOINT = os.environ.get('GEMINI_ENDPOINT', 'https://api.gemini.example/v1')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-1')


def call_gemini(prompt, max_tokens=256):
    """Call the Gemini-like API endpoint. Returns text or raises."""
    if not GEMINI_API_KEY:
        raise RuntimeError('GEMINI_API_KEY not configured')
    url = f"{GEMINI_ENDPOINT}/models/{GEMINI_MODEL}/completions"
    headers = {'Authorization': f'Bearer {GEMINI_API_KEY}', 'Content-Type': 'application/json'}
    payload = {'prompt': prompt, 'max_tokens': max_tokens}
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # adapt to provider response
    if 'choices' in data and len(data['choices']) > 0:
        return data['choices'][0].get('text') or data['choices'][0].get('message', {}).get('content')
    if 'output' in data:
        return data['output']
    return ''


def generate_summary_and_tags(title, author, description):
    prompt = f"Generate a concise summary (2-3 sentences) and 5 tags for the following book.\nTitle: {title}\nAuthor: {author}\nDescription: {description}\nRespond in JSON with keys: summary, tags (array)."
    out = call_gemini(prompt, max_tokens=200)
    return out


def generate_embedding(text):
    """Dummy embedding generator via Gemini text -> numeric vector. The actual Gemini embedding API may differ; this is a placeholder.
    We will request a compact JSON array from the model.
    """
    prompt = f"Generate a compact numeric embedding as a JSON array for the following text (no extra text):\n{text}\nRespond only with a JSON array of numbers."
    out = call_gemini(prompt, max_tokens=300)
    return out
