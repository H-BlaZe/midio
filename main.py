from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
import numpy as np
import librosa
from PIL import Image, PngImagePlugin
import soundfile as sf
import os
from pathlib import Path
from typing import Optional
import io
import subprocess

app = FastAPI(title="🎭 Audio Steganography")

# Create directories (only for static and templates)
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


class AudioImageConverter:
    """Audio steganography engine"""
    
    def check_ffmpeg(self):
        """Check if FFmpeg is installed"""
        try:
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=5)
            return result.returncode == 0
        except Exception as e:
            return False
    
    def convert_to_wav_memory(self, input_bytes, input_format='mp3'):
        """Convert any audio format to WAV using FFmpeg (in-memory)"""
        try:
            command = [
                'ffmpeg',
                '-i', 'pipe:0',  # Read from stdin
                '-f', input_format,
                '-ac', '1',  # mono
                '-ar', '22050',  # sample rate
                '-acodec', 'pcm_s16le',
                '-f', 'wav',  # Output format
                'pipe:1'  # Write to stdout
            ]
            
            result = subprocess.run(
                command,
                input=input_bytes,
                capture_output=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return result.stdout
            else:
                print(f"FFmpeg error: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            print("FFmpeg conversion timed out")
            return None
        except Exception as e:
            print(f"FFmpeg conversion failed: {e}")
            return None
    
    def load_audio_from_bytes(self, audio_bytes, filename):
        """Load audio from bytes with FFmpeg fallback"""
        try:
            # Try soundfile first
            audio_io = io.BytesIO(audio_bytes)
            y, sr = sf.read(audio_io)
            if len(y.shape) > 1:  # Stereo to mono
                y = np.mean(y, axis=1)
            return y, sr
        except Exception as e:
            print(f"Soundfile failed: {e}, trying FFmpeg...")
            
            try:
                # Get file extension
                ext = Path(filename).suffix.lower().replace('.', '')
                if not ext:
                    ext = 'wav'
                
                # Convert using FFmpeg
                wav_bytes = self.convert_to_wav_memory(audio_bytes, ext)
                if wav_bytes:
                    wav_io = io.BytesIO(wav_bytes)
                    y, sr = sf.read(wav_io)
                    if len(y.shape) > 1:
                        y = np.mean(y, axis=1)
                    return y, sr
                else:
                    raise Exception("FFmpeg conversion failed")
            except Exception as e2:
                print(f"FFmpeg method failed: {e2}")
            
            try:
                # Last resort: librosa
                audio_io = io.BytesIO(audio_bytes)
                y, sr = librosa.load(audio_io, sr=None, mono=True)
                return y, sr
            except Exception as e3:
                raise Exception(f"All audio loading methods failed. Error: {e3}")
    
    def audio_to_image(self, audio_bytes, audio_filename, base_image_bytes, n_fft=1024, hop_length=512):
        """Hide audio data inside image (in-memory)"""
        
        # Load audio with fallback methods
        audio_data, sr = self.load_audio_from_bytes(audio_bytes, audio_filename)
        
        # Compute spectrogram
        D = librosa.stft(audio_data, n_fft=n_fft, hop_length=hop_length)
        magnitude = np.abs(D)
        phase = np.angle(D)
        
        # Load base image
        base_img = Image.open(io.BytesIO(base_image_bytes))
        if base_img.mode != 'RGB':
            base_img = base_img.convert('RGB')
        
        # Prepare metadata
        pnginfo = PngImagePlugin.PngInfo()
        
        # Store magnitude
        magnitude_bytes = magnitude.astype(np.float32).tobytes()
        pnginfo.add_text("magnitude", magnitude_bytes.hex())
        
        # Store phase
        phase_bytes = phase.astype(np.float32).tobytes()
        pnginfo.add_text("phase", phase_bytes.hex())
        
        # Store metadata
        pnginfo.add_text("shape_0", str(magnitude.shape[0]))
        pnginfo.add_text("shape_1", str(magnitude.shape[1]))
        pnginfo.add_text("sample_rate", str(sr))
        pnginfo.add_text("n_fft", str(n_fft))
        pnginfo.add_text("hop_length", str(hop_length))
        pnginfo.add_text("original_length", str(len(audio_data)))
        pnginfo.add_text("duration", f"{len(audio_data)/sr:.2f}")
        
        # Save PNG to bytes
        output_io = io.BytesIO()
        base_img.save(output_io, "PNG", pnginfo=pnginfo, optimize=False)
        output_io.seek(0)
        
        return {
            "image_bytes": output_io.getvalue(),
            "file_size_mb": len(output_io.getvalue()) / (1024 * 1024),
            "dimensions": base_img.size,
            "duration": len(audio_data) / sr,
            "sample_rate": sr
        }
    
    def image_to_audio(self, image_bytes):
        """Extract hidden audio from image (in-memory)"""
        
        img = Image.open(io.BytesIO(image_bytes))
        
        if 'magnitude' not in img.info:
            raise ValueError("This image doesn't contain hidden audio data!")
        
        # Extract metadata
        shape_0 = int(img.info['shape_0'])
        shape_1 = int(img.info['shape_1'])
        sr = int(img.info['sample_rate'])
        hop_length = int(img.info['hop_length'])
        original_length = int(img.info['original_length'])
        
        # Extract magnitude
        magnitude_hex = img.info['magnitude']
        magnitude_bytes = bytes.fromhex(magnitude_hex)
        magnitude = np.frombuffer(magnitude_bytes, dtype=np.float32).reshape(shape_0, shape_1)
        
        # Extract phase
        phase_hex = img.info['phase']
        phase_bytes = bytes.fromhex(phase_hex)
        phase = np.frombuffer(phase_bytes, dtype=np.float32).reshape(shape_0, shape_1)
        
        # Reconstruct complex spectrogram
        D = magnitude * np.exp(1j * phase)
        
        # Inverse STFT
        y = librosa.istft(D, hop_length=hop_length, length=original_length)
        
        # Save audio to bytes
        audio_io = io.BytesIO()
        sf.write(audio_io, y, sr, format='WAV')
        audio_io.seek(0)
        
        return {
            "audio_bytes": audio_io.getvalue(),
            "duration": len(y) / sr,
            "sample_rate": sr
        }


converter = AudioImageConverter()


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve the main page"""
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
    """Embed audio into image (returns image directly)"""
    try:
        # Check FFmpeg availability
        if not converter.check_ffmpeg():
            print("Warning: FFmpeg not available. Some audio formats may not work.")
        
        # Read files into memory
        audio_bytes = await audio_file.read()
        image_bytes = await image_file.read()
        
        # Embed audio in image
        result = converter.audio_to_image(
            audio_bytes=audio_bytes,
            audio_filename=audio_file.filename,
            base_image_bytes=image_bytes,
            n_fft=n_fft,
            hop_length=hop_length
        )
        
        # Return image directly as streaming response
        return StreamingResponse(
            io.BytesIO(result["image_bytes"]),
            media_type="image/png",
            headers={
                "Content-Disposition": "attachment; filename=embedded_audio.png",
                "X-File-Size-MB": str(result["file_size_mb"]),
                "X-Duration": str(result["duration"]),
                "X-Sample-Rate": str(result["sample_rate"])
            }
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/extract")
async def extract_audio(image_file: UploadFile = File(...)):
    """Extract audio from image (returns audio directly)"""
    try:
        # Read image into memory
        image_bytes = await image_file.read()
        
        # Extract audio
        result = converter.image_to_audio(image_bytes)
        
        # Return audio directly as streaming response
        return StreamingResponse(
            io.BytesIO(result["audio_bytes"]),
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=extracted_audio.wav",
                "X-Duration": str(result["duration"]),
                "X-Sample-Rate": str(result["sample_rate"])
            }
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    """Serve the about page"""
    return templates.TemplateResponse("about.html", {"request": request})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)