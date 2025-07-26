from flask import Flask
import sys
import os

# Add the parent directory to the path so we can import from app.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# This is the entry point for Vercel - correct format
def handler(request):
    return app

# Alternative Vercel entry point
app = app

# For development
if __name__ == '__main__':
    app.run()