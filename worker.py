"""Run with uvicorn worker:app. This service needs persistent disk and FFmpeg."""
import os
os.environ['SHIYING_WORKER_MODE']='1'
from server import app
