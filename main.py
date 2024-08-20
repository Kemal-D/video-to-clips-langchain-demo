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

# Load the environment variables (e.g., API keys)
load_dotenv(find_dotenv())

# Define the YouTube video URL you want to process
youtube_url = "https://www.youtube.com/watch?v=4WO5kJChg3w"

# Create necessary directories if they do not exist
os.makedirs("downloaded_videos", exist_ok=True)
os.makedirs("generated_clips", exist_ok=True)

# Download the video from YouTube
try:
    yt = YouTube(youtube_url)
    video = yt.streams.filter(file_extension='mp4').first()
    safe_title = yt.title.replace(' ', '_')
    filename = f"downloaded_videos/{safe_title}.mp4"
    video.download(filename=filename)
    print(f"Downloaded video: {filename}")
except Exception as e:
    print(f"Failed to download video: {e}")
    exit(1)

# Fetch the transcript for the YouTube video
try:
    video_id = yt.video_id
    transcript = YouTubeTranscriptApi.get_transcript(video_id)
    if len(transcript) < 10:
        print("The transcript is too short to extract meaningful segments.")
        exit(1)
except Exception as e:
    print(f"Failed to retrieve transcript: {e}")
    exit(1)

# Initialize the LLM for segment identification
llm = ChatOpenAI(model='gpt-4', temperature=0.7, max_tokens=None, timeout=None, max_retries=2)

# Define the LLM prompt to identify viral segments in the video
prompt = f"""Provided to you is a transcript of a video. 
Please identify all segments that can be extracted as subtopics from the video based on the transcript.
Make sure each segment is between 30-500 seconds in duration.
Make sure you provide extremely accurate timestamps and respond only in the format provided.
\n Here is the transcription: \n {transcript}"""

# Define the message structure for the LLM
messages = [
    {"role": "system", "content": "You are a viral content producer. You are master at reading youtube transcripts and identifying the most intriguing content. You have extraordinary skills to extract subtopic from content. Your subtopics can be repurposed as a separate video."},
    {"role": "user", "content": prompt}
]

# Define the data structure for segments
class Segment(BaseModel):
    """ Represents a segment of a video"""
    start_time: float = Field(..., description="The start time of the segment in seconds")
    end_time: float = Field(..., description="The end time of the segment in seconds")
    yt_title: str = Field(..., description="The youtube title to make this segment a viral sub-topic")
    description: str = Field(..., description="The detailed youtube description to make this segment viral ")
    duration: int = Field(..., description="The duration of the segment in seconds")

class VideoTranscript(BaseModel):
    """ Represents the transcript of a video with identified viral segments"""
    segments: List[Segment] = Field(..., description="List of viral segments in the video")

# Use structured output with the LLM for better parsing
structured_llm = llm.with_structured_output(VideoTranscript)

try:
    # Invoke the LLM to process the transcript and return structured segments
    ai_msg = structured_llm.invoke(messages)
    parsed_content = ai_msg.dict()['segments']
except Exception as e:
    print(f"Error during LLM processing: {e}")
    exit(1)

# Define a function to process each segment using ffmpeg
def process_segment(segment, i):
    start_time = segment['start_time']
    end_time = segment['end_time']
    yt_title = segment['yt_title']
    description = segment['description']
    duration = segment['duration']

    output_file = f"generated_clips/{safe_title}_{str(i+1)}.mp4"
    command = f"ffmpeg -y -i {filename} -ss {start_time} -to {end_time} -c:v libx264 -c:a aac -b:a 192k {output_file}"

    try:
        subprocess.run(command, shell=True, check=True)
        print(f"Successfully created segment {i+1}: {output_file}")
        return f"Sub-Topic {i+1}: {yt_title}, Duration: {duration}s\nDescription: {description}\n"
    except Exception as e:
        print(f"Error processing segment {i+1}: {e}")
        return None

# Process video segments in parallel to speed up the process
segment_labels = []
with ThreadPoolExecutor() as executor:
    futures = [executor.submit(process_segment, segment, i) for i, segment in enumerate(parsed_content)]
    for future in futures:
        result = future.result()
        if result:
            segment_labels.append(result)

# Save the segment labels to a text file
with open('generated_clips/segment_labels.txt', 'w') as f:
    for label in segment_labels:
        f.write(label + "\n")

# Save the segments to a JSON file
with open('generated_clips/segments.json', 'w') as f:
    json.dump(parsed_content, f, indent=4)

print("Video segments created and saved successfully.")
