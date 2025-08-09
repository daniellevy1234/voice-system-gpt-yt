# -- coding: utf-8 --
# recovery code for twillo 56ZGZ6L8P7Q59M7LVGA2BKQ5
from flask import Flask, request, redirect, Response, send_from_directory
from twilio.twiml.voice_response import VoiceResponse, Gather
import openai
import os
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

# הגדרת מפתח ה-API של OpenAI ממשתנה סביבה
openai.api_key = os.environ.get("OPENAI_API_KEY")

# מילונים לשמירת היסטוריית שיחות ושירים אחרונים בזיכרון
# הערה: בסביבת ייצור, מומלץ להשתמש במסד נתונים כמו Redis
sessions = {}
recent_songs = {}

# רשימת ערוצים לשידור חי
live_streams = {
    "1": "https://keshet-livestream.cdn.mk12.streamweb.co.il/live/keshet.stream/playlist.m3u8",
    "2": "https://kan11live.makan.org.il/kan11/live/playlist.m3u8",
    "3": "https://13tv-live.cdnwiz.com/live/13tv/13tv/playlist.m3u8",
    "4": "https://kan14live.makan.org.il/kan14/live/playlist.m3u8",
    "5": "https://i24hls-i.akamaihd.net/hls/live/2037040/i24newsenglish/index.m3u8"
}


@app.route("/voice", methods=['GET', 'POST'])
def voice():
    resp = VoiceResponse()

    gather = Gather(num_digits=1, action="/menu", method="POST", timeout=5)
    prompt = (
        # "ברוך הבא למערכת. "
        # "לשיחה עם ג'י-פי-טי, הקש 1. "
        # "לבקשת שיר, הקש 2. "
        # "לשידורים חיים, הקש 3. "
        # "למבזק חדשות, הקש 4. "
        # "לתוכנית של ינון ובן, הקש 5. "
        # "לשמיעת השירים האחרונים, הקש 6. "
        # "ליציאה, הקש 9."
        "Welcome to the system."
        "To talk with GPT, press 1."
        "To request a song, press 2."
        "For live broadcasts, press 3."
        "For a news bulletin, press 4."
        "For the Yinon and Ben show, press 5."
        "To hear the latest songs, press 6."
        "To exit, press 9."
    )
    gather.say(prompt)
    # gather.say(prompt, language="he-IL", voice="Polly.Tomer")
    resp.append(gather)

    # If no input is received, say goodbye and hang up
    # resp.say("לא התקבלה קלט. נסה שוב מאוחר יותר.", language="he-IL", voice="Polly.Tomer")
    resp.hangup()

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

@app.route("/gpt-prompt", methods=['GET', 'POST'])
def gpt_prompt():
    resp = VoiceResponse()
    prompt = (
       "You have entered conversation mode with GPT. "
"To return to the main menu at any time, say 'Return to menu'. "
"What is your first question?"
    )
    gather = Gather()
    gather.say(prompt, language="en-US", voice="Polly.Joanna")
    
    resp.append(gather)
    resp.redirect("/voice")
    return str(resp)

@app.route("/handle-gpt-response", methods=['POST'])
def handle_gpt_response():
    resp = VoiceResponse()
    call_sid = request.form.get("CallSid")
    speech_result = request.form.get("SpeechResult")

    if speech_result and ("חזור לתפריט" in speech_result or "תפריט ראשי" in speech_result):
        resp.say("Sure, returning to the main menu." , language="en-US", voice="Polly.Joanna")
        # resp.say("בטח, חוזר לתפריט הראשי."Sure, returning to the main menu.", language="en-US", voice="Polly.Joanna")
        resp.redirect("/voice")
        return str(resp)

    if not speech_result:
        resp.say(" I didn't hear you. Returning to the main menu." , language="en-US", voice="Polly.Joanna")
        # resp.say("לא שמעתי אותך. חוזר לתפריט הראשי." I didn't hear you. Returning to the main menu.", language="en-US", voice="Polly.Joanna")
        resp.redirect("/voice")
        return str(resp)

    if call_sid not in sessions:
        sessions[call_sid] = [{"role": "system", "content": "Answer in Hebrew, briefly and clearly."}]
        # sessions[call_sid] = [{"role": "system", "content": "ענה בעברית, בקצרה ובבהירות."Answer in Hebrew, briefly and clearly."}]
    
    sessions[call_sid].append({"role": "user", "content": speech_result})
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=sessions[call_sid]
        )
        answer = response.choices[0].message.content
        sessions[call_sid].append({"role": "assistant", "content": answer})
        resp.say(answer, language="he-IL", voice="Polly.Tomer")

        # המשך הלולאה רק אם התשובה התקבלה בהצלחה
        gather = Gather(input="speech", action="/handle-gpt-response", timeout=7 , language="en-US", voice="Polly.Joanna")
        resp.append(gather)

    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        resp.say("Sorry, there was an error receiving the answer from GPT. Returning to the main menu." , language="en-US", voice="Polly.Joanna")
        # resp.say("ה בקבלת התשובה מ-GPT. חוזר לתפריט הראשי.מצטער, הייתה תקל"Sorry, there was an error receiving the answer from GPT. Returning to the main menu.", language="en-US", voice="Polly.Joanna")
        # במקרה של שגיאה, נשבור את הלולאה ונחזור לתפריט
        resp.redirect("/voice")
        
    return str(resp)

@app.route("/song-prompt", methods=['GET', 'POST'])
def song_prompt():
    resp = VoiceResponse()
    gather = Gather(input="speech", action="/play-song", timeout=5)
    gather.say("Please say the name of the song you are looking for", language="en-US", voice="Polly.Joanna")
    resp.append(gather)
    resp.redirect("/voice")
    return str(resp)

@app.route("/play-song", methods=['POST'])
def play_song():
    resp = VoiceResponse()
    speech = request.form.get("SpeechResult")
    call_sid = request.form.get("CallSid")

    song_map = {
        "esta vida.mp3": ["esta vida.mp3", "esta vida", "esta vida song", "happy song", "song 1", "song one"],
        "oa_ana_bekoach.mp3": ["ana bekoach", "ana bekoach song", "ana bekoach mp3", "song 2", "song two"],
        "oa_bukarest.mp3": ["bukarest", "bukarest song", "bukarest mp3", "song 3", "song three"],
        "oa_mishkafayim.mp3": ["mishkapayim", "mishkapayim song", "mishkapayim mp3", "song 4", "song four"],
        "yomim.mp3": ["yomim", "yomim song", "yomim mp3", "Rabbi", "days", "song 5", "song five"],
    }

    # Lowercase the speech input
    if speech:
        speech_lower = speech.lower()

        # Find the song that matches
        file_name = next(
            (k for k, aliases in song_map.items() if speech_lower in (alias.lower() for alias in aliases)),
            None
        )
        resp.say(f"Playing the song {file_name}.", language="en-US", voice="Polly.Joanna")
        resp.play(f"https://voice-system-gpt-yt.onrender.com/songs/{file_name}")

        if file_name:
            resp.say(f"Playing the song {speech_lower}.", language="en-US", voice="Polly.Joanna")
            recent_songs.setdefault(call_sid, []).append(file_name.replace(".mp3", ""))
            resp.play(f"https://voice-system-gpt-yt.onrender.com/songs/{file_name}")
            # return str(resp)

    # Fallback if no match
    resp.say("Wasn't able to detect the song", language="en-US", voice="Polly.Joanna")
    return str(resp)


@app.route("/recent-songs", methods=['GET', 'POST'])
def recent_songs_playback():
    resp = VoiceResponse()
    call_sid = request.form.get("CallSid")
    songs_to_play = recent_songs.get(call_sid, [])
    
    if songs_to_play:
        resp.say("Playing the last songs you requested." , language="en-US", voice="Polly.Joanna")
        # resp.say("מנגן את השירים האחרונים שביקשת.Playing the last songs you requested.", language="en-US", voice="Polly.Joanna")
        for song_query in reversed(songs_to_play):
            song_url = f"https://yt-api.stream.sh/play?search={song_query}"
            resp.say(f"השיר הבא: {song_query}", language="en-US", voice="Polly.Joanna")
            resp.play(song_url)
    else:
        resp.say("No songs were found in your history" , language="en-US", voice="Polly.Joanna")
        # resp.say("לא נמצאו שירים בהיסטוריה שלך.No songs were found in your history", language="en-US", voice="Polly.Joanna")
    
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
    gather.say(prompt, language="en-US", voice="Polly.Joanna")
    resp.append(gather)
    resp.redirect("/voice")
    return str(resp)

@app.route("/play-live", methods=['POST'])
def play_live():
    resp = VoiceResponse()
    digit = request.form.get("Digits")
    url = live_streams.get(digit)
    if url:
        resp.say("Connecting to the live broadcast.")

        resp.play(url)
    else:
        resp.say("Invalid channel.")
    
    resp.redirect("/voice")
    return str(resp)

@app.route("/ynet-news", methods=['GET', 'POST'])
def ynet_news():
    resp = VoiceResponse()
    resp.say("Checking the top headlines from Ynet.")

    
    try:
        r = requests.get("https://www.ynet.co.il/news", timeout=5)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        headlines = [item.get_text(strip=True) for item in soup.select(".slotTitle a")[:5]]
        if headlines:
            news_string = ". ".join(headlines)
            resp.say("news_string,")
        else:
            resp.say("I couldn't find any news headlines.")
            
    except Exception as e:
        print(f"Error fetching Ynet news: {e}")
        resp.say("There was an error retrieving the news.")

    resp.redirect("/voice")
    return str(resp)

@app.route("/yinon-podcast", methods=['GET', 'POST'])
def yinon_podcast():
    resp = VoiceResponse()
    resp.say("Playing The show of Yinon Magal and Ben Caspit.", language="en-US", voice="Polly.Joanna")
    resp.play("https://103fm.maariv.co.il/media/podcast/mp3/1030_podcast_19620.mp3")
    resp.redirect("/voice")
    return str(resp)


# Path to your songs folder
SONGS_FOLDER = os.path.join(os.getcwd(), "songs")

@app.route("/songs/<path:filename>", methods=['GET'])
def serve_song(filename):
    """Serve a song file from the songs folder."""
    return send_from_directory(SONGS_FOLDER, filename)


if __name__ == "__main__":
    app.run(debug=True)
