"""
Groq API Configuration Example
-------------------------------
Configuration template for Groq API (fallback for Gemini)

To use:
1. Copy this file to: groq_config.py
2. Add your Groq API key from: https://console.groq.com/keys
3. groq_config.py is in .gitignore (won't be committed)

IMPORTANT:
- This is a TEMPLATE file (groq_config.example.py)
- Copy it to: groq_config.py
- Add your real API key in groq_config.py
- Never commit groq_config.py to git (it's in .gitignore)
"""

import os

# Your Groq API Key
# Get it from: https://console.groq.com/keys
GROQ_API_KEY = os.getenv('GROQ_API_KEY', 'your-api-key-here')

# Model selection is NOT configured here any more.
# `groq_client.resolve_model()` asks the API which models your key can use and
# picks the best available one, because Groq retires model IDs periodically
# (mixtral-8x7b-32768 was removed in March 2025) and a retired ID makes every
# call fail with HTTP 400.
# To pin a specific model anyway, set the GROQ_MODEL environment variable.

# Rate limiting (seconds between requests)
RATE_LIMIT_DELAY = 0.5

# Timeout for API requests (seconds)
REQUEST_TIMEOUT = 30

# Max retries on API errors
MAX_RETRIES = 2

# Enable/disable Groq as fallback
GROQ_ENABLED = True

