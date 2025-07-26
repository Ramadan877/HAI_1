from flask import Flask

app = Flask(__name__)

@app.route('/')
def index():
    return 'Hello from Flask on Vercel!'

@app.route('/test')
def test():
    return 'Test route working!'

@app.route('/<path:path>')
def catch_all(path):
    return f'You requested: {path}'

# This is crucial for Vercel
def handler(request, response):
    return app(request.environ, response)

# For local development
if __name__ == '__main__':
    app.run(debug=True)