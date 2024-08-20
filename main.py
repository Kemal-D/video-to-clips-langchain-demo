import os
import subprocess
import json
from typing import List
from pytube import YouTube
from youtube_transcript_api import YouTubeTranscriptApi
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv, find_dotenv
from concurrent.futures import ThreadPoolExecutor
import logging

# Setup logging
logging.basicConfig(level=logging.DEBUG, filename='debug.log', filemode='w', 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Script started.")

# Load the environment variables
load_dotenv(find_dotenv())

youtube_url = "https://www.youtube.com/watch?v=4WO5kJChg3w"

# Create necessary directories
os.makedirs("downloaded_videos", exist_ok=True)
os.makedirs("generated_clips", exist_ok=True)

# Download video from YouTube
try:
    yt = YouTube(youtube_url)
    video = yt.streams.filter(file_extension='mp4').first()
    safe_title = yt.title.replace(' ', '_')
    filename = f"downloaded_videos/{safe_title}.mp4"
    video.download(filename=filename)
    logging.info(f"Downloaded video: {filename}")
except Exception as e:
    logging.error(f"Failed to download video: {e}")
    exit(1)

# Retrieve transcript
try:
    video_id = yt.video_id
    transcript = YouTubeTranscriptApi.get_transcript(video_id)
    logging.info(f"Transcript retrieved with {len(transcript)} entries.")
    if len(transcript) < 10:
        logging.warning("The transcript is too short to extract meaningful segments.")
        exit(1)
except Exception as e:
    logging.error(f"Failed to retrieve transcript: {e}")
    exit(1)

# LLM setup and processing
llm = ChatOpenAI(model='gpt-4', temperature=0.7, max_tokens=None, timeout=None, max_retries=2)
prompt = f"""Provided to you is a transcript of a video. 
Please identify all segments that can be extracted as subtopics from the video based on the transcript.
Make sure each segment is between 30-500 seconds in duration.
Make sure you provide extremely accurate timestamps and respond only in the format provided.
\n Here is the transcription: \n {transcript}"""

messages = [
    {"role": "system", "content": "You are a viral content producer."},
    {"role": "user", "content": prompt}
]

class Segment(BaseModel):
    start_time: float
    end_time: float
    yt_title: str
    description: str
    duration: int

class VideoTranscript(BaseModel):
    segments: List[Segment]

structured_llm = llm.with_structured_output(VideoTranscript)

try:
    ai_msg = structured_llm.invoke(messages)
    parsed_content = ai_msg.dict()['segments']
    logging.info(f"LLM returned {len(parsed_content)} segments.")
except Exception as e:
    logging.error(f"LLM processing error: {e}")
    exit(1)

# Validate timestamps
video_length = yt.length
for segment in parsed_content:
    if segment['start_time'] > video_length or segment['end_time'] > video_length:
        logging.warning(f"Invalid segment timestamps: {segment}")

# Define function for FFmpeg processing
def process_segment(segment, i):
    logging.info(f"Starting processing of segment {i+1}")
    start_time = segment['start_time']
    end_time = segment['end_time']
    output_file = f"generated_clips/{safe_title}_{str(i+1)}.mp4"
    command = f"ffmpeg -y -i {filename} -ss {start_time} -to {end_time} -c:v libx264 -c:a aac -b:a 192k {output_file}"

    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        logging.info(f"FFmpeg output: {result.stdout}")
        if result.returncode != 0:
            logging.error(f"FFmpeg error: {result.stderr}")
        else:
            logging.info(f"Successfully created segment {i+1}: {output_file}")
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                return f"Sub-Topic {i+1}: {segment['yt_title']}, Duration: {segment['duration']}s\nDescription: {segment['description']}\n"
    except Exception as e:
        logging.error(f"Error processing segment {i+1}: {e}")
        return None

# Process segments with multi-threading
segment_labels = []
with ThreadPoolExecutor() as executor:
    futures = [executor.submit(process_segment, segment, i) for i, segment in enumerate(parsed_content)]
    for future in futures:
        result = future.result()
        if result:
            segment_labels.append(result)

# Save segment labels and JSON data
with open('generated_clips/segment_labels.txt', 'w') as f:
    for label in segment_labels:
        f.write(label + "\n")

try:
    with open('generated_clips/segments.json', 'w') as f:
        json.dump(parsed_content, f, indent=4)
    logging.info("Segments data successfully written to JSON.")
except Exception as e:
    logging.error(f"Error writing segments to JSON: {e}")
