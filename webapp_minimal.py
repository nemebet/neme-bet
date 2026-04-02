import os
from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    return '<h1>NEME BET OK</h1>'

@app.route('/health')
def health():
    return 'ok', 200
