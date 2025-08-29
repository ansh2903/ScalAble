import requests
import json

model = 'huihui_ai/deepseek-r1-abliterated:8b'
prompt = 'write a long response. this is a test'

payload = {
    'model': model,
    'prompt': prompt,
    'stream': True,
}

def get_streamed_response(payload):
    output = requests.post('http://localhost:11434/api/generate', json=payload, stream=True)
    for token in output.iter_lines():
        token = json.loads(token)
        yield token.get('response')

output = get_streamed_response(payload)

for token in output:
    print(token, end='')