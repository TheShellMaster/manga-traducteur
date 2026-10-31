import asyncio
import base64
import hashlib
import io
import json
import os
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from app.archives import ArchiveHandler, ArchiveItem
from app.cloud_vision import CloudVisionClient
from app.config import load_env, save_env_key, PROVIDER_PRESETS, USER_DIR
from app.groq_refine import refine_translations_with_groq
from app.typesetter import render_manga_page

# ...
# The repository source file is intentionally large; source details not echoed here.