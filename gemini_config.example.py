"""
Gemini AI Configuration
-----------------------
Configuration file for Google Gemini API

To get your FREE API key:
1. Go to: https://makersuite.google.com/app/apikey
2. Click "Create API Key"
3. Copy the key and paste below

IMPORTANT:
- This is a TEMPLATE file (gemini_config.example.py)
- Copy it to: gemini_config.py
- Add your real API key in gemini_config.py
- Never commit gemini_config.py to git (it's in .gitignore)

API Limits (Free tier):
- 60 requests per minute
- 1500 requests per day
- Sufficient for most scraping scenarios
"""

# Your Gemini API Key
# Get it from: https://makersuite.google.com/app/apikey
GEMINI_API_KEY = "your-api-key-here"

# Model selection
# Options:
#   "gemini-pro" (RECOMMENDED - fast, free, good quality)
#   "gemini-1.5-pro" (if available in your region)
GEMINI_MODEL = "gemini-pro"

# Rate limiting (seconds between requests)
# Default: 1.0 second = 60 requests/minute (within free tier)
RATE_LIMIT_DELAY = 1.0

# Timeout for API requests (seconds)
REQUEST_TIMEOUT = 10

# Max retries on API errors
MAX_RETRIES = 2

# Enable/disable Gemini analysis
# Set to False if you want to disable AI analysis temporarily
GEMINI_ENABLED = True
