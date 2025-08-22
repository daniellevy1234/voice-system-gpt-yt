import openai
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

openai.api_key = os.environ.get("OPENAI_API_KEY")

client = OpenAI()

# Send a prompt
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Write a haiku about the ocean."}
    ]
)

# Print the model's reply
print(response.choices[0].message.content)
