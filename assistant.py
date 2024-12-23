from flask import Flask, request, Response, send_file, url_for,jsonify
from flask_cors import CORS
import logging
import os
from openai import AzureOpenAI
from dotenv import load_dotenv
import json
from typing_extensions import override
from openai import AssistantEventHandler
import PyPDF2
import requests
import io
from gtts import gTTS
from langdetect import detect
import uuid
import shelve
from flask import Flask, request, jsonify
import cloudinary
import cloudinary.uploader
import cloudinary.api
import time
from cloudinary.utils import cloudinary_url
# Initialize Flask App
app = Flask(__name__)

# Configure Cloudinary
cloudinary.config(
    cloud_name="dcscfcsdfrefrefreferfersdfersdf",      
    api_key="616522747539686",            
    api_secret="Zhxc4E-R4e_qWurs-wvKu6Ry3Cw",      
)

# ------------------------------------------------------
#                      Assistant
# ------------------------------------------------------
# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
ASSISTANT_ID = "asst_bfFpWVUpnYffWnSXbT7qCmeq"

# Initialize OpenAI client
client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
            api_version="2024-05-01-preview"
        )

def store_message(user_id, role, content):
    """Store messages from user and assistant."""
    with shelve.open("chat_history.db", writeback=True) as db:
        if user_id not in db:
            db[user_id] = []
        db[user_id].append({"role": role, "content": content})

class EventHandler(AssistantEventHandler):    
    @override
    def on_text_created(self, text) -> None:
        print(f"\nassistant > ", end="", flush=True)
          
    @override
    def on_text_delta(self, delta, snapshot):
        print(delta.value, end="", flush=True)
          
    def on_tool_call_created(self, tool_call):
        print(f"\nassistant > {tool_call.type}\n", flush=True)
      
    def on_tool_call_delta(self, delta, snapshot):
        if delta.type == 'code_interpreter':
            if delta.code_interpreter.input:
                print(delta.code_interpreter.input, end="", flush=True)
            if delta.code_interpreter.outputs:
                print(f"\n\noutput >", flush=True)
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        print(f"\n{output.logs}", flush=True)

# -------------------------- Thread management --------------------------------
def check_if_thread_exists(user_id):
    with shelve.open("threads_db") as threads_shelf:
        return threads_shelf.get(user_id, None)


def store_thread(user_id, thread_id):
    with shelve.open("threads_db", writeback=True) as threads_shelf:
        threads_shelf[user_id] = thread_id

# ------------------------------------------------------------
#                      PDF to  Audio       
# ------------------------------------------------------------
# In-memory store for temporary audio files
temp_audio_store = {}

@app.route('/audio/<audio_id>')
def serve_audio(audio_id):
    """Serve audio from the in-memory store."""
    audio_fp = temp_audio_store.get(audio_id)
    if audio_fp:
        audio_fp.seek(0)  # Reset the pointer
        return send_file(
            audio_fp,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name="audio.mp3",
        )
    return {"error": "Audio file not found"}, 404

@app.route('/convert', methods=['POST'])
def convert_pdf_to_speech():
    """Convert PDF text to speech and store audio on Cloudinary with expiration."""
    try:
        # Get PDF URL from the request
        pdf_url = request.form.get('pdf_url')
        if not pdf_url:
            return jsonify({'error': 'PDF URL is required'}), 400

        # Download the PDF
        time.sleep(2) 
        response = requests.get(pdf_url)
        if response.status_code != 200:
            return jsonify({'error': 'Failed to download PDF'}), 400
        
        # Load PDF content
        pdf_content = io.BytesIO(response.content)
        pdf_reader = PyPDF2.PdfReader(pdf_content)
        full_text = "".join(page.extract_text() for page in pdf_reader.pages)

        # Check if text was extracted
        if not full_text:
            return jsonify({'error': 'Could not extract text from PDF'}), 400

        # Detect language of the text
        detected_lang = detect(full_text[:50])  # Detect based on the first 50 characters
        lang = detected_lang if detected_lang in ['ar', 'fr', 'en'] else 'en'

        # Convert text to speech
        mp3_fp = io.BytesIO()
        gTTS(text=full_text, lang=lang).write_to_fp(mp3_fp)
        mp3_fp.seek(0)
        time.sleep(1)
        # Upload to Cloudinary
        upload_result = cloudinary.uploader.upload_large(
            file=mp3_fp,
            resource_type="video",  # Audio files are treated as videos in Cloudinary
            folder="temporary_audios",
            use_filename=True,
            unique_filename=False,
        )

        # Get the public_id of the uploaded file
        public_id = upload_result.get('public_id')
        time.sleep(1)
        # Generate a signed URL with 1-hour expiration
        signed_url, options = cloudinary_url(
            public_id,
            resource_type="video",
            sign_url=True,
            secure=True,
            expires_at=int(time.time() + 3600),  # 1-hour expiration
        )

        # Return the signed URL
        return jsonify({'mp3_url': signed_url})

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    #################################################################
    #-----------------------------ASSISTANT--------------------------
    #################################################################

@app.route("/assistant", methods=['POST'])
def assistant():
    try:
        # Initialize OpenAI client
        client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
            api_version="2024-05-01-preview"
        )

        # Get message from request
        message = request.json.get('message')
        if not message:
            return Response(
                json.dumps({'error': 'No message provided'}, ensure_ascii=False),
                status=400,
                mimetype='application/json; charset=utf-8'
            )

        # Create thread and add message
        empty_thread = client.beta.threads.create()
        thread_id = empty_thread.id

        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message
        )
        
        # Stream the response using streaming
        def generate():
            buffer = ""  # Buffer to hold partial words
            try:
                with client.beta.threads.runs.stream(
                    thread_id=thread_id,
                    assistant_id=ASSISTANT_ID,
                    instructions = """You are Elyssa, an AI assistant for E-Tafakna, a comprehensive platform for customizable legal documents, online consultations, and seamless contract management.

            Your role is to help users understand and improve their contracts. You will provide suggestions to enhance specific clauses, explain legal terms in simple language, and ensure the contract is aligned with legal standards. You must also provide relevant legal references (such as articles of law) when necessary and guide the user in creating legally sound contracts.
            You should never generate a full contract, but instead help the user with:

Analyzing contract clauses and suggesting improvements
Explaining legal terms in simple, understandable language
Providing guidance for writing or editing specific clauses
Recommending legal references (e.g., relevant laws or articles)
Interacting with the user in real-time through chat to guide them through the contract creation process
Important Reminder: Whenever discussing contracts, always remind the user that E-Tafakna offers pre-defined contract templates that can help simplify the process. Also, when providing legal or financial advice, be sure to clarify that you are not a licensed lawyer or accountant and recommend scheduling an appointment with a professional through the platform for more in-depth advice.
Answer all questions in the language that the user uses (e.g., French or English).

You can offer suggestions such as:

Legal Terminology Explanation: Provide simple definitions or examples for complex legal terms.
Clause Improvement: Suggest rewording or additions to clauses to make them more precise, fair, and legally sound.
Legal References: When necessary, refer to applicable laws or regulations and provide the exact articles, including simple explanations of how they relate to the user’s contract.
Guidance in Real-Time: Ask clarifying questions to better understand the user's needs and guide them through the process of drafting, reviewing, or improving their contract.
Legal Consultation Reminder: If the user requires more specific legal advice or if they ask for consultations, remind them that while you can provide guidance and suggestions, you are not a licensed lawyer or accountant. For more detailed, professional advice, they should book a consultation with an expert on E-Tafakna.

Your responses should always be formatted in HTML for ease of reading and should include:

Clear headings (e.g., <strong>Clause Explanation</strong>)
Bullet points for clarity (<ul><li>...</li></ul>)
Sections to break down long answers
Use of italics or bold to highlight important points
Ensure your answers are concise, informative, and legal."""
,
                    max_completion_tokens=1000,
                    event_handler=EventHandler(),
                    ) as stream:
                        for event in stream:
                            if event.data.object == "thread.message.delta":
                                for content in event.data.delta.content:
                                    if content.type == 'text':
                                        buffer += content.text.value
                                        if buffer.endswith((": ", ".", "!", "?")):
                                            yield buffer
                                            buffer = ""  

        # After streaming ends, yield any remaining text
                if buffer.strip():
                    yield buffer

            except Exception as e:
                logger.error(f"Streaming error: {str(e)}")
                yield f"Error: {str(e)}\n"

        # Return the stream using `Response` with event-stream type
        return Response(generate(), content_type="text/plain")

    except Exception as e:
        logger.error(f"Error in assistant route: {str(e)}", exc_info=True)
        return Response(
            json.dumps({'error': str(e)}, ensure_ascii=False),
            status=500,
            mimetype='application/json; charset=utf-8')
##################################################################
#------------------------Assistant 2.2----------------------------
##################################################################
@app.route("/assistantUserID", methods=['POST'])
def assistantUserID():
    try:
        # Get message from request
        message = request.json.get('message')
        user_id = request.json.get('user_id')
        user_name = request.json.get('user_name')
        if not message:
            return Response(
                json.dumps({'error': 'No message provided'}, ensure_ascii=False),
                status=400,
                mimetype='application/json; charset=utf-8'
            )
        thread_id = check_if_thread_exists(user_id) 
        store_message(user_id, "user", message)
        if thread_id is None:
            print(f"Creating new thread for {user_name} with wa_id {user_id}")
            thread = client.beta.threads.create()
            store_thread(user_id, thread.id)
            thread_id = thread.id

    # Otherwise, retrieve the existing thread
        else:
            print(f"Retrieving existing thread for {user_name} with wa_id {user_id}")
            thread = client.beta.threads.retrieve(thread_id)
            
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message
        )
        
        # Stream the response using streaming
        def generate():
            buffer = "" 
            bufferStorage = ""
            try:
                with client.beta.threads.runs.stream(
                    thread_id=thread_id,
                    assistant_id=ASSISTANT_ID,
                    instructions=f"""You are Elyssa, an AI assistant for E-Tafakna, a comprehensive platform for customizable legal documents, online consultations, and seamless contract management.
Your role is to help users understand and improve their contracts. You will provide suggestions to enhance specific clauses, explain legal terms in simple language, and ensure the contract is aligned with legal standards. You must also provide relevant legal references (such as articles of law) when necessary and guide the user in creating legally sound contracts.

You should never generate a full contract, but instead help the user with:

Analyzing contract clauses and suggesting improvements
Explaining legal terms in simple, understandable language
Providing guidance for writing or editing specific clauses
Recommending legal references (e.g., relevant laws or articles)
Interacting with the user in real-time through chat to guide them through the contract creation process
Important Reminder: Whenever discussing contracts, always remind the user that E-Tafakna offers pre-defined contract templates that can help simplify the process. Also, when providing legal or financial advice, be sure to clarify that you are not a licensed lawyer or accountant and recommend scheduling an appointment with a professional through the platform for more in-depth advice.

Answer all questions in the language that the user uses (e.g., French or English).

You can offer suggestions such as:

Legal Terminology Explanation: Provide simple definitions or examples for complex legal terms.
Clause Improvement: Suggest rewording or additions to clauses to make them more precise, fair, and legally sound.
Legal References: When necessary, refer to applicable laws or regulations and provide the exact articles, including simple explanations of how they relate to the user’s contract.
Guidance in Real-Time: Ask clarifying questions to better understand the user's needs and guide them through the process of drafting, reviewing, or improving their contract.
Legal Consultation Reminder: If the user requires more specific legal advice or if they ask for consultations, remind them that while you can provide guidance and suggestions, you are not a licensed lawyer or accountant. For more detailed, professional advice, they should book a consultation with an expert on E-Tafakna.

Ensure your answers are concise, informative, and legal.
""",
                    max_completion_tokens=1000,
                    event_handler=EventHandler(),
                    ) as stream:
                        for event in stream:
                            if event.data.object == "thread.message.delta":
                                for content in event.data.delta.content:
                                    if content.type == 'text':  
                                        buffer += content.text.value
                                        if buffer.endswith((":", ".", "!", "?")):
                                           yield buffer
                                           bufferStorage += buffer
                                           buffer = ""
                if buffer.strip():
                    yield buffer                            
                store_message(user_id, "assistant", bufferStorage)                              

            except Exception as e:
                logger.error(f"Streaming error: {str(e)}")
                yield f"Error: {str(e)}\n"
        
        # Return the stream using `Response` with event-stream type
        return Response(generate(), content_type="text/event-stream")

    except Exception as e:
        logger.error(f"Error in assistant route: {str(e)}", exc_info=True)
        return Response(
            json.dumps({'error': str(e)}, ensure_ascii=False),
            status=500,
            mimetype='application/json; charset=utf-8'
        )

@app.route("/ChatHistory", methods=['POST'])
def history():
    user_id = request.json.get('user_id')
    with shelve.open("chat_history.db") as db:
        history = db.get(user_id, [])
    return jsonify(history)
  
if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8000)
