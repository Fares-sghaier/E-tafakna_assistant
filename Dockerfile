# Use the official Python image from Docker Hub
FROM python:3.12.2


RUN pip install --upgrade pip

# Install Python dependencies directly
RUN pip install Flask \
    Flask-Cors \
    python-dotenv \
    openai \
    typing-extensions \
    requests \
    PyPDF2 \
    edge_tts \
    langdetect \
    cloudinary

# Expose the port Flask will run on

COPY . .

EXPOSE 8000


# Command to run the Flask application
CMD ["python", "assistant.py"]

