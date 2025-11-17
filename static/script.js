// Global variables
let audioContext;
let mediaStreamSource;
let recorder;
let recordedBlob = null;

// DOM Elements
const modeButtons = document.querySelectorAll('.mode-btn');
const embedMode = document.getElementById('embed-mode');
const extractMode = document.getElementById('extract-mode');

const inputTypeButtons = document.querySelectorAll('.input-type-btn');
const uploadAudioDiv = document.getElementById('upload-audio');
const recordAudioDiv = document.getElementById('record-audio');

const audioFileInput = document.getElementById('audio-file');
const audioFileName = document.getElementById('audio-file-name');

const imageFileInput = document.getElementById('image-file');
const imageFileName = document.getElementById('image-file-name');
const imagePreview = document.getElementById('image-preview');

const startRecordBtn = document.getElementById('start-record');
const stopRecordBtn = document.getElementById('stop-record');
const recordingStatus = document.getElementById('recording-status');
const recordedAudio = document.getElementById('recorded-audio');

const nFftSlider = document.getElementById('n-fft');
const hopLengthSlider = document.getElementById('hop-length');
const fftValue = document.getElementById('fft-value');
const hopValue = document.getElementById('hop-value');

const embedBtn = document.getElementById('embed-btn');
const extractBtn = document.getElementById('extract-btn');

const extractImageFileInput = document.getElementById('extract-image-file');
const extractImageFileName = document.getElementById('extract-image-file-name');
const extractImagePreview = document.getElementById('extract-image-preview');

const embedResult = document.getElementById('embed-result');
const extractResult = document.getElementById('extract-result');

const loading = document.getElementById('loading');

// Mode switching
modeButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        const mode = btn.dataset.mode;
        
        modeButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        
        if (mode === 'embed') {
            embedMode.classList.remove('hidden');
            extractMode.classList.add('hidden');
        } else {
            embedMode.classList.add('hidden');
            extractMode.classList.remove('hidden');
        }
        
        // Reset results
        embedResult.classList.add('hidden');
        extractResult.classList.add('hidden');
    });
});

// Audio input type switching
inputTypeButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        const type = btn.dataset.type;
        
        inputTypeButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        
        if (type === 'upload') {
            uploadAudioDiv.classList.remove('hidden');
            recordAudioDiv.classList.add('hidden');
        } else {
            uploadAudioDiv.classList.add('hidden');
            recordAudioDiv.classList.remove('hidden');
        }
    });
});

// File inputs
audioFileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        audioFileName.textContent = `📁 ${e.target.files[0].name}`;
        audioFileName.classList.add('show');
        recordedBlob = null; // Clear recorded audio
    }
});

imageFileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        const file = e.target.files[0];
        imageFileName.textContent = `📁 ${file.name}`;
        imageFileName.classList.add('show');
        
        // Show preview
        const reader = new FileReader();
        reader.onload = (event) => {
            imagePreview.innerHTML = `<img src="${event.target.result}" alt="Preview">`;
            imagePreview.classList.add('show');
        };
        reader.readAsDataURL(file);
    }
});

extractImageFileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        const file = e.target.files[0];
        extractImageFileName.textContent = `📁 ${file.name}`;
        extractImageFileName.classList.add('show');
        
        // Show preview
        const reader = new FileReader();
        reader.onload = (event) => {
            extractImagePreview.innerHTML = `<img src="${event.target.result}" alt="Preview">`;
            extractImagePreview.classList.add('show');
        };
        reader.readAsDataURL(file);
    }
});

// Sliders
nFftSlider.addEventListener('input', (e) => {
    fftValue.textContent = e.target.value;
});

hopLengthSlider.addEventListener('input', (e) => {
    hopValue.textContent = e.target.value;
});

// Audio Recording with WAV format
startRecordBtn.addEventListener('click', async () => {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        
        // Use Web Audio API for WAV recording
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        mediaStreamSource = audioContext.createMediaStreamSource(stream);
        
        // Use ScriptProcessor for recording
        const bufferSize = 4096;
        const numberOfChannels = 1;
        
        recorder = audioContext.createScriptProcessor(bufferSize, numberOfChannels, numberOfChannels);
        
        const audioChunks = [];
        
        recorder.onaudioprocess = (e) => {
            const channelData = e.inputBuffer.getChannelData(0);
            audioChunks.push(new Float32Array(channelData));
        };
        
        mediaStreamSource.connect(recorder);
        recorder.connect(audioContext.destination);
        
        startRecordBtn.disabled = true;
        stopRecordBtn.disabled = false;
        recordingStatus.textContent = '🔴 Recording in progress...';
        recordingStatus.classList.add('show');
        
        // Store for stop function
        window.currentRecording = {
            stream,
            audioChunks,
            sampleRate: audioContext.sampleRate
        };
        
    } catch (error) {
        alert('❌ Could not access microphone: ' + error.message);
    }
});

stopRecordBtn.addEventListener('click', () => {
    if (!window.currentRecording) return;
    
    const { stream, audioChunks, sampleRate } = window.currentRecording;
    
    // Stop recording
    if (recorder) {
        recorder.disconnect();
        mediaStreamSource.disconnect();
    }
    
    // Stop tracks
    stream.getTracks().forEach(track => track.stop());
    
    // Convert to WAV
    const audioBuffer = mergeBuffers(audioChunks);
    const wavBlob = createWavBlob(audioBuffer, sampleRate);
    
    recordedBlob = wavBlob;
    const audioUrl = URL.createObjectURL(wavBlob);
    recordedAudio.src = audioUrl;
    recordedAudio.classList.remove('hidden');
    
    recordingStatus.textContent = '✅ Recording saved!';
    recordingStatus.style.background = '#95E1D3';
    
    startRecordBtn.disabled = false;
    stopRecordBtn.disabled = true;
    
    // Clear file input when recording is used
    audioFileInput.value = '';
    audioFileName.classList.remove('show');
    
    window.currentRecording = null;
});

// Helper functions for WAV creation
function mergeBuffers(chunks) {
    const totalLength = chunks.reduce((acc, chunk) => acc + chunk.length, 0);
    const result = new Float32Array(totalLength);
    let offset = 0;
    
    for (const chunk of chunks) {
        result.set(chunk, offset);
        offset += chunk.length;
    }
    
    return result;
}

function createWavBlob(audioBuffer, sampleRate) {
    const numberOfChannels = 1;
    const bitDepth = 16;
    
    const bytesPerSample = bitDepth / 8;
    const blockAlign = numberOfChannels * bytesPerSample;
    
    const dataLength = audioBuffer.length * blockAlign;
    const buffer = new ArrayBuffer(44 + dataLength);
    const view = new DataView(buffer);
    
    // WAV header
    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + dataLength, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true); // fmt chunk size
    view.setUint16(20, 1, true); // PCM format
    view.setUint16(22, numberOfChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * blockAlign, true); // byte rate
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitDepth, true);
    writeString(view, 36, 'data');
    view.setUint32(40, dataLength, true);
    
    // Write audio data
    let offset = 44;
    for (let i = 0; i < audioBuffer.length; i++) {
        const sample = Math.max(-1, Math.min(1, audioBuffer[i]));
        view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7FFF, true);
        offset += 2;
    }
    
    return new Blob([buffer], { type: 'audio/wav' });
}

function writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
    }
}

// Embed Audio
embedBtn.addEventListener('click', async () => {
    try {
        // Validate inputs
        let audioFile = null;
        
        if (uploadAudioDiv.classList.contains('hidden')) {
            // Using recorded audio
            if (!recordedBlob) {
                alert('❌ Please record audio first!');
                return;
            }
            audioFile = new File([recordedBlob], 'recorded.wav', { type: 'audio/wav' });
        } else {
            // Using uploaded audio
            if (!audioFileInput.files.length) {
                alert('❌ Please select an audio file!');
                return;
            }
            audioFile = audioFileInput.files[0];
        }
        
        if (!imageFileInput.files.length) {
            alert('❌ Please select an image file!');
            return;
        }
        
        // Show loading
        loading.classList.remove('hidden');
        
        // Prepare form data
        const formData = new FormData();
        formData.append('audio_file', audioFile);
        formData.append('image_file', imageFileInput.files[0]);
        formData.append('n_fft', nFftSlider.value);
        formData.append('hop_length', hopLengthSlider.value);
        
        // Send request
        const response = await fetch('/api/embed', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (!response.ok) {
            throw new Error(result.detail || 'Embedding failed');
        }
        
        // Display result
        embedResult.innerHTML = `
            <h3 class="result-title">✅ AUDIO SUCCESSFULLY EMBEDDED!</h3>
            <div class="result-info">
                <div class="result-item">
                    <span class="result-label">File Size:</span>
                    <span>${result.file_size_mb.toFixed(2)} MB</span>
                </div>
                <div class="result-item">
                    <span class="result-label">Image Dimensions:</span>
                    <span>${result.dimensions[0]} × ${result.dimensions[1]}</span>
                </div>
                <div class="result-item">
                    <span class="result-label">Audio Duration:</span>
                    <span>${result.duration.toFixed(2)} seconds</span>
                </div>
                <div class="result-item">
                    <span class="result-label">Sample Rate:</span>
                    <span>${result.sample_rate} Hz</span>
                </div>
            </div>
            <a href="/api/download/${result.file_id}/image" class="download-btn" download>
                📥 DOWNLOAD IMAGE
            </a>
            <div class="result-preview">
                <img src="${result.output_file}?t=${Date.now()}" alt="Result">
            </div>
        `;
        embedResult.classList.remove('hidden');
        
        // Scroll to result
        embedResult.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        
    } catch (error) {
        alert('❌ Error: ' + error.message);
    } finally {
        loading.classList.add('hidden');
    }
});

// Extract Audio
extractBtn.addEventListener('click', async () => {
    try {
        if (!extractImageFileInput.files.length) {
            alert('❌ Please select a PNG image with hidden audio!');
            return;
        }
        
        // Show loading
        loading.classList.remove('hidden');
        
        // Prepare form data
        const formData = new FormData();
        formData.append('image_file', extractImageFileInput.files[0]);
        
        // Send request
        const response = await fetch('/api/extract', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (!response.ok) {
            throw new Error(result.detail || 'Extraction failed');
        }
        
        // Display result
        extractResult.innerHTML = `
            <h3 class="result-title">✅ AUDIO SUCCESSFULLY EXTRACTED!</h3>
            <div class="result-info">
                <div class="result-item">
                    <span class="result-label">Audio Duration:</span>
                    <span>${result.duration.toFixed(2)} seconds</span>
                </div>
                <div class="result-item">
                    <span class="result-label">Sample Rate:</span>
                    <span>${result.sample_rate} Hz</span>
                </div>
            </div>
            <a href="/api/download/${result.file_id}/audio" class="download-btn" download>
                📥 DOWNLOAD AUDIO
            </a>
            <div class="result-preview">
                <audio src="${result.output_file}?t=${Date.now()}" controls class="audio-player"></audio>
            </div>
        `;
        extractResult.classList.remove('hidden');
        
        // Scroll to result
        extractResult.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        
    } catch (error) {
        alert('❌ Error: ' + error.message);
    } finally {
        loading.classList.add('hidden');
    }
});

// Clean up audio context on page unload
window.addEventListener('beforeunload', () => {
    if (audioContext && audioContext.state !== 'closed') {
        audioContext.close();
    }
});