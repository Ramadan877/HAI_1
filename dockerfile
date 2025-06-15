# Use a smaller, more optimized base image for Python applications
# `slim-buster` is a good balance between size and compatibility
FROM python:3.9-slim-buster

# Set environment variables for non-interactive apt-get installations
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies:
# - ffmpeg: Required by pydub and Whisper for audio processing
# - build-essential: Needed for compiling some Python packages (e.g., those with C extensions)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean

# Set the working directory inside the container
WORKDIR /app

# Copy only the requirements file first to leverage Docker's build cache
# If requirements.txt doesn't change, this step won't re-run
COPY requirements.txt .

# Install Python dependencies
# `--no-cache-dir` prevents pip from storing its cache, reducing image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Expose the port that your Flask application listens on
# Railway will use this, but it's good practice for Docker images
EXPOSE 5000

# Define the command to run your application when the container starts
CMD ["python", "app.py"]