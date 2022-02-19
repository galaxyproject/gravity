DEFAULT_INSTANCE_NAME = "_default_"
DEFAULT_GUNICORN_BIND = "localhost:8080"
DEFAULT_GUNICORN_TIMEOUT = 300
DEFAULT_GUNICORN_WORKERS = 1
DEFAULT_GUNICORN_EXTRA_ARGS = ""
GUNICORN_DEFAULT_CONFIG = {
    "bind": DEFAULT_GUNICORN_BIND,
    "workers": DEFAULT_GUNICORN_WORKERS,
    "timeout": DEFAULT_GUNICORN_TIMEOUT,
    "extra_args": DEFAULT_GUNICORN_EXTRA_ARGS
}
CELERY_DEFAULT_CONFIG = {
    "loglevel": "debug",
    "concurrency": 2,
    "extra_args": ""
}