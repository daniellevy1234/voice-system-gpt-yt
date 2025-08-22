# Download the helper library from https://www.twilio.com/docs/python/install
import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

# Set environment variables for your credentials
# Read more at http://twil.io/secure

account_sid = os.environ.get("TWILIO_ACCOUNT_SID", False)
auth_token = os.environ.get("TWILIO_AUTH_TOKEN", False)

client = Client(account_sid, auth_token)

call = client.calls.create(
  url="https://voice-system-gpt-yt.onrender.com/voice",
  # to="+14077779425",
  # to="+14072058238",
  to="+14076308943",
  from_="+12253965461"
)

print(call.sid)