
from flask import Flask, request, redirect, Response, send_from_directory
from twilio.twiml.voice_response import VoiceResponse, Gather
import openai
import os
import requests
from bs4 import BeautifulSoup
import yt_dlp ## --- FIX 1 ---: Added yt-dlp import for YouTube search

app = Flask(__name__)

# ## --- FIX 2 ---: Updated OpenAI client initialization for v1.0.0+ of the library
# Make sure the OPENAI_API_KEY environment variable is set
if "OPENAI_API_KEY" not in os.environ:
    raise ValueError("Missing OPENAI_API_KEY environment variable")
client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# ---- GPT session storage ----
sessions = {}      # call_sid -> chat history (list of messages)
gpt_replies = {}   # call_sid -> list of assistant replies (plain text)
gpt_indexes = {}   # call_sid -> int pointer for 4/6 navigation

# Beep sound (forward-at-latest, and before playback if you like)
BEEP_URL = "https://actions.google.com/sounds/v1/alarms/beep_short.ogg"

# Store song query and the found URL to avoid re-searching
recent_songs = {} # call_sid -> list of {"query": "...", "url": "..."}

# רשימת ערוצים לשידור חי
live_streams = {
    "1": "https://keshet-livestream.cdn.mk12.streamweb.co.il/live/keshet.stream/playlist.m3u8",
    "2": "https://kan11live.makan.org.il/kan11/live/playlist.m3u8",
    "3": "https://13tv-live.cdnwiz.com/live/13tv/13tv/playlist.m3u8",
    "4": "https://kan14live.makan.org.il/kan14/live/playlist.m3u8",
    "5": "https://i24hls-i.akamaihd.net/hls/live/2037040/i24newsenglish/index.m3u8"
}

## --- FIX 1 (Implementation) ---: Added the missing search_youtube function
def search_youtube(query):
    """
    Searches YouTube for a query and returns a direct audio stream URL.
    Returns None if no suitable stream is found.
    """
    ydl_opts = {
        'format': 'bestaudio/best', # Prioritize the best audio-only format
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch1:', # Search YouTube and get the first result
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if 'entries' in info and info['entries']:
                # The search result is in 'entries'
                video_info = info['entries'][0]
            elif 'url' in info:
                # Direct URL was passed
                video_info = info
            else:
                return None
            
            # Find the best audio stream URL
            best_audio_url = None
            for f in video_info.get('formats', []):
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    best_audio_url = f['url']
                    break # Found a good audio-only stream
            
            # Fallback to the primary URL if no audio-only stream is found
            return best_audio_url or video_info.get('url')

    except Exception as e:
        print(f"Error during YouTube search for '{query}': {e}")
        return None


@app.route("/voice", methods=['GET', 'POST'])
def voice():
    resp = VoiceResponse()

    gather = Gather(num_digits=1, action="/menu", method="POST", timeout=5)
    prompt = (
        "Welcome to the system. "
        "To talk with GPT, press 1. "
        "To request a song, press 2. "
        "For live broadcasts, press 3. "
        "For a news bulletin, press 4. "
        "For the Yinon and Ben show, press 5. "
        "To hear the latest songs, press 6. "
        "To exit, press 9."
    )
    # Using a Polly voice for better quality
    gather.say(prompt, voice="Polly.Joanna", language="en-US")
    resp.append(gather)

    # If the user doesn't input anything, we can hang up or redirect to /voice
    resp.redirect("/voice") 
    return Response(str(resp), mimetype='text/xml')


@app.route("/menu", methods=['POST'])
def menu():
    choice = request.form.get("Digits")
    route_map = {
        "1": "/gpt-prompt",
        "2": "/song-prompt",
        "3": "/live-prompt",
        "4": "/ynet-news",
        "5": "/yinon-podcast",
        "6": "/recent-songs",
    }
    if choice in route_map:
        return redirect(route_map[choice])
    elif choice == "9":
        resp = VoiceResponse()
        resp.say("Thank you for calling! Goodbye.")
        resp.hangup()
        return str(resp)
    else:
        resp = VoiceResponse()
        resp.say("invalid choice, please try again.")
        resp.redirect("/voice")
        return str(resp)

# ---------------- GPT MODE (updated) ----------------

@app.route("/gpt-prompt", methods=['GET', 'POST'])
def gpt_prompt():
    """Enter GPT conversation mode. Supports speech + DTMF (4/6)."""
    resp = VoiceResponse()
    prompt = (
       "You have entered conversation mode with GPT. "
       "Press 4 to go back to an earlier answer. Press 6 to go forward. "
       "Say 'return to menu' to go back to the main menu. "
       "What is your first question?"
    )
    # IMPORTANT: allow BOTH speech and DTMF, and point to handler
    gather = Gather(input="speech dtmf", action="/handle-gpt-response", timeout=7, language="en-US")
    gather.say(prompt, language="en-US", voice="Polly.Joanna")
    resp.append(gather)
    resp.redirect("/voice")  # fallback if no input
    return str(resp)


@app.route("/handle-gpt-response", methods=['POST'])
def handle_gpt_response():
    """Handles GPT conversation + 4/6 navigation."""
    resp = VoiceResponse()
    call_sid = request.form.get("CallSid")
    speech_result = request.form.get("SpeechResult", "") or ""
    digit = request.form.get("Digits")

    # init containers if first time
    if call_sid not in sessions:
        sessions[call_sid] = [
            {"role": "system", "content": "Answer in English, briefly and clearly, for a voice call. Do not use markdown or special characters."}
        ]
        gpt_replies[call_sid] = []
        gpt_indexes[call_sid] = -1

    # ---- DTMF NAVIGATION (4/6) ----
    if digit in ("4", "6"):
        # nothing to navigate
        if not gpt_replies[call_sid]:
            resp.say("No answers yet. Please ask a question first.", language="en-US", voice="Polly.Joanna")
        else:
            if digit == "4":  # back
                if gpt_indexes[call_sid] > 0:
                    gpt_indexes[call_sid] -= 1
                    replay_text = gpt_replies[call_sid][gpt_indexes[call_sid]]
                    resp.play(BEEP_URL)
                    resp.say(replay_text, language="en-US", voice="Polly.Joanna")
                else:
                    resp.say("No earlier response available.", language="en-US", voice="Polly.Joanna")

            elif digit == "6":  # forward
                if gpt_indexes[call_sid] < len(gpt_replies[call_sid]) - 1:
                    gpt_indexes[call_sid] += 1
                    replay_text = gpt_replies[call_sid][gpt_indexes[call_sid]]
                    resp.play(BEEP_URL)
                    resp.say(replay_text, language="en-US", voice="Polly.Joanna")
                else:
                    # already at latest
                    resp.play(BEEP_URL)
                    resp.say("This is the latest response.", language="en-US", voice="Polly.Joanna")

        # keep the loop open
        gather = Gather(input="speech dtmf", action="/handle-gpt-response", timeout=7, language="en-US")
        gather.say("You can speak now, or press 4 to go back, 6 to go forward.",
                   language="en-US", voice="Polly.Joanna")
        resp.append(gather)
        return str(resp)

    # ---- SPEECH HANDLING ----
    # Go back to main menu phrase
    if speech_result and ("return to menu" in speech_result.lower() or "main menu" in speech_result.lower()):
        resp.say("Returning to the main menu.", language="en-US", voice="Polly.Joanna")
        resp.redirect("/voice")
        return str(resp)

    if not speech_result:
        resp.say("I didn't hear you.", language="en-US", voice="Polly.Joanna")
        gather = Gather(input="speech dtmf", action="/handle-gpt-response", timeout=7, language="en-US")
        gather.say("Please ask your question, or press 4 to go back, 6 to go forward.",
                   language="en-US", voice="Polly.Joanna")
        resp.append(gather)
        return str(resp)

    # Add user message
    sessions[call_sid].append({"role": "user", "content": speech_result})

    try:
        # ## --- FIX 2 (Implementation) ---: Updated the OpenAI API call to the new syntax
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=sessions[call_sid]
        )
        answer = response.choices[0].message.content.strip()

        # Save GPT answer to history and navigation lists
        sessions[call_sid].append({"role": "assistant", "content": answer})
        gpt_replies[call_sid].append(answer)
        gpt_indexes[call_sid] = len(gpt_replies[call_sid]) - 1

        # Trim memory if it gets big
        if len(sessions[call_sid]) > 40:
            # Keep system prompt + last 38 messages
            sessions[call_sid] = [sessions[call_sid][0]] + sessions[call_sid][-38:]

        # Beep then say answer
        resp.play(BEEP_URL)
        resp.say(answer, language="en-US", voice="Polly.Joanna")

        # Loop for next turn (speech + DTMF)
        gather = Gather(input="speech dtmf", action="/handle-gpt-response", timeout=7, language="en-US")
        gather.say("You can speak again, or press 4 to go back, 6 to go forward.",
                   language="en-US", voice="Polly.Joanna")
        resp.append(gather)

    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        resp.say("Sorry, there was an error receiving the answer from GPT. Returning to the main menu.",
                 language="en-US", voice="Polly.Joanna")
        resp.redirect("/voice")

    return str(resp)

# ---------------- END GPT MODE (rest unchanged) ----------------


@app.route("/song-prompt", methods=['GET', 'POST'])
def song_prompt():
    resp = VoiceResponse()
    gather = Gather(input="speech", action="/play-song", timeout=5, language="en-US")
    gather.say("Please say the name of the song you are looking for", language="en-US", voice="Polly.Joanna")
    resp.append(gather)
    resp.redirect("/voice")
    return str(resp)


@app.route("/play-song", methods=['POST'])
def play_song():
    resp = VoiceResponse()
    speech = request.form.get("SpeechResult")
    call_sid = request.form.get("CallSid")

    if speech:
        song_url = search_youtube(speech)

        if song_url:
            resp.say(f"Playing the song you requested: {speech}.", language="en-US", voice="Polly.Joanna")
            # ## --- SUGGESTION ---: Store both query and URL for recent songs
            recent_songs.setdefault(call_sid, []).append({"query": speech, "url": song_url})
            resp.play(song_url)
        else:
            resp.say(f"I was not able to find that song. Returning to the main menu.", language="en-US", voice="Polly.Joanna")
    else:
        resp.say("I wasn't able to detect a song name.", language="en-US", voice="Polly.Joanna")

    resp.redirect("/voice")
    return str(resp)


@app.route("/recent-songs", methods=['GET', 'POST'])
def recent_songs_playback():
    resp = VoiceResponse()
    call_sid = request.form.get("CallSid")
    # Retrieve list of song dicts
    songs_to_play = recent_songs.get(call_sid, [])

    if songs_to_play:
        resp.say("Playing the last songs you requested." , language="en-US", voice="Polly.Joanna")
        # Play in reverse order (most recent first)
        for song_info in reversed(songs_to_play):
            # ## --- SUGGESTION ---: Use the stored URL instead of searching again
            song_query = song_info["query"]
            song_url = song_info["url"]
            resp.say(f"Next up is: {song_query}", language="en-US", voice="Polly.Joanna")
            resp.play(song_url)
    else:
        resp.say("No songs were found in your history" , language="en-US", voice="Polly.Joanna")

    resp.redirect("/voice")
    return str(resp)


@app.route("/live-prompt", methods=['GET', 'POST'])
def live_prompt():
    resp = VoiceResponse()
    gather = Gather(num_digits=1, action="/play-live", method="POST")
    prompt = (
        "לערוץ 12, הקש 1. "
        "לערוץ 11, הקש 2. "
        "לערוץ 13, הקש 3. "
        "לערוץ 14, הקש 4. "
        "לערוץ i24, הקש 5."
    )
    # ## --- FIX 3 ---: Use Hebrew language and a compatible voice
    gather.say(prompt, language="he-IL", voice="Polly.Vicki")
    resp.append(gather)
    resp.redirect("/voice")
    return str(resp)


@app.route("/play-live", methods=['POST'])
def play_live():
    resp = VoiceResponse()
    digit = request.form.get("Digits")
    url = live_streams.get(digit)
    if url:
        resp.say("Connecting to the live broadcast.", language="en-US", voice="Polly.Joanna")
        resp.play(url)
    else:
        resp.say("Invalid channel.", language="en-US", voice="Polly.Joanna")
    resp.redirect("/voice")
    return str(resp)


@app.route("/ynet-news", methods=['GET', 'POST'])
def ynet_news():
    resp = VoiceResponse()
    resp.say("בדיקת הכותרות הראשיות מאתר וויינט", language="he-IL", voice="Polly.Vicki")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
        r = requests.get("https://www.ynet.co.il/news", timeout=5, headers=headers)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        # Note: This selector is fragile and may break if Ynet changes their site structure.
        headlines = [item.get_text(strip=True) for item in soup.select(".slotTitle a")[:5]]
        if headlines:
            news_string = ". ".join(headlines)
            resp.say(news_string, language="he-IL", voice="Polly.Vicki")
        else:
            resp.say("לא הצלחתי למצוא כותרות חדשות.", language="he-IL", voice="Polly.Vicki")
    except Exception as e:
        print(f"Error fetching Ynet news: {e}")
        resp.say("אירעה שגיאה בקבלת עדכוני החדשות.", language="he-IL", voice="Polly.Vicki")
    resp.redirect("/voice")
    return str(resp)


@app.route("/yinon-podcast", methods=['GET', 'POST'])
def yinon_podcast():
    resp = VoiceResponse()
    # Note: This is a static link to one episode. See review notes.
    resp.say("Playing The show of Yinon Magal and Ben Caspit.", language="en-US", voice="Polly.Joanna")
    resp.play("https://103fm.maariv.co.il/media/podcast/mp3/1030_podcast_19620.mp3")
    resp.redirect("/voice")
    return str(resp)

# This route is currently unused by the rest of the application logic.
# See review notes for explanation.
SONGS_FOLDER = os.path.join(os.getcwd(), "songs")
@app.route("/songs/<path:filename>", methods=['GET'])
def serve_song(filename):
    """Serve a song file from the songs folder."""
    return send_from_directory(SONGS_FOLDER, filename)


if __name__ == "__main__":
    # For local testing, consider using ngrok to expose your Flask app to the internet
    # so Twilio's webhooks can reach it.
    app.run(debug=True)
