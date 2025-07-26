from flask import Flask

# Create a simple test app first
app = Flask(__name__)

@app.route('/')
def hello():
    return "Hello from Vercel!"

@app.route('/<path:path>')
def catch_all(path):
    return f"Path: {path}"

# For Vercel
def handler(request):
    return app

# Export for Vercel
app = app