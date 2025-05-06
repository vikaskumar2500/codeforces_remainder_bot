# Step 1: Specify the base image
# We'll use an official Python image. Choose a version that matches your development environment.
# The "-slim" versions are smaller and good for production.
FROM python:3.12-slim
# You can use other versions like python:3.8-slim, python:3.10-slim, python:3.11-slim etc.

# Step 2: Set the working directory inside the container
# This is where your application code will live and commands will be run from.
WORKDIR /app

# Step 3: Copy the requirements file into the working directory
# We copy this first to leverage Docker's layer caching.
# If requirements.txt doesn't change, Docker won't re-install dependencies on subsequent builds
# unless the requirements.txt file itself has changed.
COPY requirements.txt .

# Step 4: Install the Python dependencies
# --no-cache-dir reduces the image size by not storing the pip download cache.
# The --trusted-host flags can help if your build environment has issues accessing PyPI.
RUN pip install --no-cache-dir --trusted-host pypi.python.org --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# Step 5: Copy the rest of your application code into the working directory
# The first "." refers to the source (your project directory on your machine).
# The second "." refers to the destination (the WORKDIR /app inside the container).
COPY . .
# If your bot code is in a subfolder, e.g., "src", you would do:
# COPY src/ .

# Step 6: Specify the command to run your application
# This is what Docker will execute when a container is started from this image.
# Replace 'bot.py' with the actual name of your main Python script.
# Using the JSON array format is the preferred way for CMD.
CMD ["python", "bot.py"]