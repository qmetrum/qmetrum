# Dockerfile

# Use a slim Python image to keep size down, but ensure compatibility
FROM python:3.9-slim

# Install system dependencies required for Prophet and Science libraries
RUN apt-get update && apt-get install -y \
    build-essential \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
# (Ensure your requirements.txt includes: fastapi, uvicorn, pandas, numpy, prophet, tensorflow, qiskit, sentence-transformers, scikit-learn, requests)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port FastAPI runs on
EXPOSE 8000

# Run the application using Uvicorn
# We point to the 'app' folder, 'main' file, and 'app' instance
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
