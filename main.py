from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
import numpy as np
import librosa
from PIL import Image, PngImagePlugin
import soundfile as sf
import os
import uuid
from pathlib import Path
import shutil
from typing import Optional
import io
import wave
import subprocess

app = FastAPI(title="🎭 Audio Steganography")

# Create directories
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)
# os.makedirs("uploads", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
templates = Jinja2Templates(directory="templates")
class AudioImageConverter:

    def check_ffmpeg(self):
        """Check if FFmpeg exists."""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except:
            return False

    def ffmpeg_to_wav_bytes(self, fileobj):
        """
        Convert ANY audio → WAV in memory using FFmpeg pipes.
        Input: BytesIO
        Output: BytesIO (WAV PCM)
        """
        fileobj.seek(0)
        input_bytes = fileobj.read()

        process = subprocess.Popen(
            [
                "ffmpeg",
                "-i", "pipe:0",
                "-ac", "1",                    # mono
                "-ar", "22050",                # sample rate
                "-acodec", "pcm_s16le",        # 16-bit WAV
                "-f", "wav",
                "pipe:1"
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        wav_data, err = process.communicate(input_bytes)

        if process.returncode != 0:
            raise Exception("FFmpeg failed: " + err.decode())

        return io.BytesIO(wav_data)

    def load_audio(self, fileobj):
        """
        Try soundfile → librosa → FFmpeg.
        All in-memory.
        """
        fileobj.seek(0)

        try:
            y, sr = sf.read(fileobj)
            if len(y.shape) > 1:
                y = np.mean(y, axis=1)
            return y, sr
        except:
            pass

        # Try librosa directly
        try:
            fileobj.seek(0)
            y, sr = librosa.load(fileobj, sr=None, mono=True)
            return y, sr
        except:
            pass

        # LAST RESORT: FFmpeg → WAV → soundfile
        try:
            wav_bytes = self.ffmpeg_to_wav_bytes(fileobj)
            wav_bytes.seek(0)
            y, sr = sf.read(wav_bytes)
            if len(y.shape) > 1:
                y = np.mean(y, axis=1)
            return y, sr
        except Exception as e:
            raise Exception("All audio loading methods failed: " + str(e))

    def audio_to_image(self, audio_fileobj, base_image_fileobj, output_fileobj, n_fft=1024, hop_length=512):
        """Embed audio into PNG in-memory."""
        audio_data, sr = self.load_audio(audio_fileobj)

        D = librosa.stft(audio_data, n_fft=n_fft, hop_length=hop_length)
        magnitude = np.abs(D).astype(np.float32)
        phase = np.angle(D).astype(np.float32)

        base_image_fileobj.seek(0)
        img = Image.open(base_image_fileobj)
        if img.mode != "RGB":
            img = img.convert("RGB")

        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("magnitude", magnitude.tobytes().hex())
        pnginfo.add_text("phase", phase.tobytes().hex())
        pnginfo.add_text("shape_0", str(magnitude.shape[0]))
        pnginfo.add_text("shape_1", str(magnitude.shape[1]))
        pnginfo.add_text("sample_rate", str(sr))
        pnginfo.add_text("hop_length", str(hop_length))
        pnginfo.add_text("original_length", str(len(audio_data)))

        img.save(output_fileobj, "PNG", pnginfo=pnginfo)

        return {
            "duration": len(audio_data) / sr,
            "sample_rate": sr,
            "dimensions": img.size
        }

    def image_to_audio(self, image_fileobj, output_audioobj):
        """Extract audio from image in memory."""
        image_fileobj.seek(0)
        img = Image.open(image_fileobj)

        if "magnitude" not in img.info:
            raise ValueError("This image has no embedded audio")

        shape_0 = int(img.info["shape_0"])
        shape_1 = int(img.info["shape_1"])
        sr = int(img.info["sample_rate"])
        hop_length = int(img.info["hop_length"])
        original_length = int(img.info["original_length"])

        magnitude = np.frombuffer(bytes.fromhex(img.info["magnitude"]), dtype=np.float32).reshape(shape_0, shape_1)
        phase = np.frombuffer(bytes.fromhex(img.info["phase"]), dtype=np.float32).reshape(shape_0, shape_1)

        D = magnitude * np.exp(1j * phase)
        y = librosa.istft(D, hop_length=hop_length, length=original_length)

        sf.write(output_audioobj, y, sr, format='WAV')

        return {
            "duration": len(y) / sr,
            "sample_rate": sr
        }

converter = AudioImageConverter()


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve the main page"""
    # Check FFmpeg on startup
    ffmpeg_available = converter.check_ffmpeg()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "ffmpeg_available": ffmpeg_available
    })


@app.get("/api/health")
async def health_check():
    """Check system health and dependencies"""
    ffmpeg_available = converter.check_ffmpeg()
    return {
        "status": "ok",
        "ffmpeg_installed": ffmpeg_available,
        "message": "FFmpeg is installed and ready" if ffmpeg_available else "FFmpeg not found. Please install it."
    }

@app.post("/api/embed")
async def embed_audio(
    audio_file: UploadFile = File(...),
    image_file: UploadFile = File(...),
    n_fft: int = Form(1024),
    hop_length: int = Form(512)
):
    try:
        # Convert files to memory buffers
        audio_bytes = io.BytesIO(await audio_file.read())
        image_bytes = io.BytesIO(await image_file.read())
        output_bytes = io.BytesIO()

        result = converter.audio_to_image(
            audio_fileobj=audio_bytes,
            base_image_fileobj=image_bytes,
            output_fileobj=output_bytes,
            n_fft=n_fft,
            hop_length=hop_length
        )

        output_bytes.seek(0)

        return StreamingResponse(
            output_bytes,
            media_type="image/png",
            headers={"Content-Disposition": "attachment; filename=embedded.png"}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/extract")
async def extract_audio(image_file: UploadFile = File(...)):
    try:
        image_bytes = io.BytesIO(await image_file.read())
        output_bytes = io.BytesIO()

        result = converter.image_to_audio(
            image_fileobj=image_bytes,
            output_audioobj=output_bytes
        )

        output_bytes.seek(0)

        return StreamingResponse(
            output_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename=extracted.wav"}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/download/{file_id}/{file_type}")
async def download_file(file_id: str, file_type: str):
    """Download generated file"""
    if file_type == "image":
        file_path = f"outputs/{file_id}_embedded.png"
        media_type = "image/png"
        filename = "embedded_audio.png"
    elif file_type == "audio":
        file_path = f"outputs/{file_id}_extracted.wav"
        media_type = "audio/wav"
        filename = "extracted_audio.wav"
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        file_path, 
        media_type=media_type, 
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
    
@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    """Serve the about page"""
    return templates.TemplateResponse("about.html", {"request": request})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)