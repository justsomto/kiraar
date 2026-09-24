from pkg import app
import os

if __name__ == '__main__':
    # debug=True only runs locally. In production, Gunicorn serves the app via wsgi.py
    debug_mode = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    app.run(debug=debug_mode, port=5057)
