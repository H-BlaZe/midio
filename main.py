from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
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
os.makedirs("uploads", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
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
    
    def convert_to_wav(self, input_file, output_file):
        """Convert any audio format to WAV using FFmpeg"""
        try:
            # FFmpeg command to convert to WAV
            # -i: input file
            # -ac 1: convert to mono
            # -ar 22050: sample rate (you can change this)
            # -y: overwrite output file
            command = [
                'ffmpeg',
                '-i', input_file,
                '-ac', '1',  # mono
                '-ar', '22050',  # sample rate
                '-acodec', 'pcm_s16le',  # PCM 16-bit little-endian
                '-y',  # overwrite
                output_file
            ]
            
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return True
            else:
                print(f"FFmpeg error: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("FFmpeg conversion timed out")
            return False
        except Exception as e:
            print(f"FFmpeg conversion failed: {e}")
            return False
    
    def load_audio(self, audio_path):
        """Load audio with FFmpeg fallback"""
        try:
            # Try soundfile first
            y, sr = sf.read(audio_path)
            if len(y.shape) > 1:  # Stereo to mono
                y = np.mean(y, axis=1)
            return y, sr
        except Exception as e:
            print(f"Soundfile failed: {e}, trying FFmpeg...")
            
            try:
                # Convert to WAV first using FFmpeg
                temp_wav = audio_path.rsplit('.', 1)[0] + '_temp.wav'
                if self.convert_to_wav(audio_path, temp_wav):
                    y, sr = sf.read(temp_wav)
                    os.remove(temp_wav)
                    if len(y.shape) > 1:  # Stereo to mono
                        y = np.mean(y, axis=1)
                    return y, sr
                else:
                    raise Exception("FFmpeg conversion failed")
            except Exception as e2:
                print(f"FFmpeg method failed: {e2}")
            
            try:
                # Last resort: librosa
                y, sr = librosa.load(audio_path, sr=None, mono=True)
                return y, sr
            except Exception as e3:
                raise Exception(f"All audio loading methods failed. Error: {e3}")
    
    def audio_to_image(self, audio_path, base_image_file, output_file, n_fft=1024, hop_length=512):
        """Hide audio data inside image"""
        
        # Load audio with fallback methods
        audio_data, sr = self.load_audio(audio_path)
        
        # Compute spectrogram
        D = librosa.stft(audio_data, n_fft=n_fft, hop_length=hop_length)
        magnitude = np.abs(D)
        phase = np.angle(D)
        
        # Load base image
        base_img = Image.open(base_image_file)
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
        
        # Save PNG with embedded data
        base_img.save(output_file, "PNG", pnginfo=pnginfo, optimize=False)
        
        return {
            "file_size_mb": os.path.getsize(output_file) / (1024 * 1024),
            "dimensions": base_img.size,
            "duration": len(audio_data) / sr,
            "sample_rate": sr
        }
    
    def image_to_audio(self, image_file, output_audio):
        """Extract hidden audio from image"""
        
        img = Image.open(image_file)
        
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
        
        # Save audio
        sf.write(output_audio, y, sr)
        
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
    """Embed audio into image"""
    try:
        # Check FFmpeg availability
        if not converter.check_ffmpeg():
            print("Warning: FFmpeg not available. Some audio formats may not work.")
        
        # Generate unique ID
        unique_id = str(uuid.uuid4())
        
        # Get file extension
        audio_ext = Path(audio_file.filename).suffix.lower()
        if not audio_ext:
            audio_ext = '.wav'
        
        # Save uploaded files
        audio_path = f"uploads/{unique_id}_audio{audio_ext}"
        image_path = f"uploads/{unique_id}_image{Path(image_file.filename).suffix}"
        output_path = f"outputs/{unique_id}_embedded.png"
        
        # Save audio file
        with open(audio_path, "wb") as f:
            shutil.copyfileobj(audio_file.file, f)
        
        # Save image file
        with open(image_path, "wb") as f:
            shutil.copyfileobj(image_file.file, f)
        
        # Embed audio in image
        result = converter.audio_to_image(
            audio_path=audio_path,
            base_image_file=image_path,
            output_file=output_path,
            n_fft=n_fft,
            hop_length=hop_length
        )
        
        # Clean up uploaded files
        try:
            os.remove(audio_path)
            os.remove(image_path)
        except:
            pass
        
        return {
            "success": True,
            "output_file": f"/outputs/{unique_id}_embedded.png",
            "file_id": unique_id,
            **result
        }
    
    except Exception as e:
        # Clean up on error
        try:
            if 'audio_path' in locals():
                os.remove(audio_path)
            if 'image_path' in locals():
                os.remove(image_path)
            if 'output_path' in locals() and os.path.exists(output_path):
                os.remove(output_path)
        except:
            pass
        
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/extract")
async def extract_audio(image_file: UploadFile = File(...)):
    """Extract audio from image"""
    try:
        # Generate unique ID
        unique_id = str(uuid.uuid4())
        
        # Save uploaded image
        image_path = f"uploads/{unique_id}_image.png"
        output_audio = f"outputs/{unique_id}_extracted.wav"
        
        with open(image_path, "wb") as f:
            shutil.copyfileobj(image_file.file, f)
        
        # Extract audio
        result = converter.image_to_audio(image_path, output_audio)
        
        # Clean up
        try:
            os.remove(image_path)
        except:
            pass
        
        return {
            "success": True,
            "output_file": f"/outputs/{unique_id}_extracted.wav",
            "file_id": unique_id,
            **result
        }
    
    except Exception as e:
        # Clean up on error
        try:
            if 'image_path' in locals():
                os.remove(image_path)
            if 'output_audio' in locals() and os.path.exists(output_audio):
                os.remove(output_audio)
        except:
            pass
        
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


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