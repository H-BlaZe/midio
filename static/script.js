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
        
        embedResult.classList.add('hidden');
        extractResult.classList.add('hidden');

        if (mode === 'embed') {
            embedMode.classList.remove('hidden');
            extractMode.classList.add('hidden');
        } else {
            embedMode.classList.add('hidden');
            extractMode.classList.remove('hidden');
        }
    });
});

// Audio input switching
inputTypeButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        const type = btn.dataset.type;

        inputTypeButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        if (type === "upload") {
            uploadAudioDiv.classList.remove('hidden');
            recordAudioDiv.classList.add('hidden');
        } else {
            uploadAudioDiv.classList.add('hidden');
            recordAudioDiv.classList.remove('hidden');
        }
    });
});

// File inputs
audioFileInput.addEventListener('change', e => {
    if (e.target.files.length > 0) {
        audioFileName.textContent = "📁 " + e.target.files[0].name;
        audioFileName.classList.add("show");
        recordedBlob = null;
    }
});

imageFileInput.addEventListener('change', e => {
    if (e.target.files.length > 0) {
        const file = e.target.files[0];
        imageFileName.textContent = "📁 " + file.name;
        imageFileName.classList.add("show");

        const reader = new FileReader();
        reader.onload = ev => {
            imagePreview.innerHTML = `<img src="${ev.target.result}">`;
            imagePreview.classList.add("show");
        };
        reader.readAsDataURL(file);
    }
});

extractImageFileInput.addEventListener('change', e => {
    if (e.target.files.length > 0) {
        const file = e.target.files[0];
        extractImageFileName.textContent = "📁 " + file.name;
        extractImageFileName.classList.add("show");

        const reader = new FileReader();
        reader.onload = ev => {
            extractImagePreview.innerHTML = `<img src="${ev.target.result}">`;
            extractImagePreview.classList.add("show");
        };
        reader.readAsDataURL(file);
    }
});

// Sliders
nFftSlider.oninput = e => (fftValue.textContent = e.target.value);
hopLengthSlider.oninput = e => (hopValue.textContent = e.target.value);

// Recording
startRecordBtn.addEventListener("click", async () => {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

        audioContext = new AudioContext();
        mediaStreamSource = audioContext.createMediaStreamSource(stream);

        const bufferSize = 4096;
        recorder = audioContext.createScriptProcessor(bufferSize, 1, 1);
        const chunks = [];

        recorder.onaudioprocess = e => {
            chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
        };

        mediaStreamSource.connect(recorder);
        recorder.connect(audioContext.destination);

        window.currentRecording = { stream, chunks, sampleRate: audioContext.sampleRate };

        startRecordBtn.disabled = true;
        stopRecordBtn.disabled = false;
        recordingStatus.textContent = "🔴 Recording...";
        recordingStatus.classList.add("show");

    } catch (err) {
        alert("Error accessing mic: " + err.message);
    }
});

stopRecordBtn.addEventListener("click", () => {
    if (!window.currentRecording) return;

    const { stream, chunks, sampleRate } = window.currentRecording;

    recorder.disconnect();
    mediaStreamSource.disconnect();
    stream.getTracks().forEach(t => t.stop());

    const merged = mergeBuffers(chunks);
    recordedBlob = createWavBlob(merged, sampleRate);

    recordedAudio.src = URL.createObjectURL(recordedBlob);
    recordedAudio.classList.remove("hidden");

    recordingStatus.textContent = "✅ Saved!";
    stopRecordBtn.disabled = true;
    startRecordBtn.disabled = false;

    audioFileInput.value = "";
    audioFileName.classList.remove("show");

    window.currentRecording = null;
});

// WAV helper functions
function mergeBuffers(chunks) {
    const len = chunks.reduce((a, c) => a + c.length, 0);
    const out = new Float32Array(len);
    let off = 0;
    chunks.forEach(c => {
        out.set(c, off);
        off += c.length;
    });
    return out;
}

function createWavBlob(buf, sr) {
    const header = new ArrayBuffer(44 + buf.length * 2);
    const view = new DataView(header);

    writeString(view, 0, "RIFF");
    view.setUint32(4, 36 + buf.length * 2, true);
    writeString(view, 8, "WAVE");
    writeString(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sr, true);
    view.setUint32(28, sr * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(view, 36, "data");
    view.setUint32(40, buf.length * 2, true);

    let offset = 44;
    for (let i = 0; i < buf.length; i++) {
        const s = Math.max(-1, Math.min(1, buf[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
        offset += 2;
    }

    return new Blob([view], { type: "audio/wav" });
}

function writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) view.setUint8(offset + i, string.charCodeAt(i));
}

// 🔥 FIXED — EMBED (BINARY RESPONSE)
embedBtn.addEventListener("click", async () => {
    try {
        let audioFile = null;

        if (uploadAudioDiv.classList.contains("hidden")) {
            if (!recordedBlob) return alert("Record audio first!");
            audioFile = new File([recordedBlob], "recorded.wav", { type: "audio/wav" });
        } else {
            if (!audioFileInput.files.length) return alert("Choose audio!");
            audioFile = audioFileInput.files[0];
        }

        if (!imageFileInput.files.length) return alert("Choose image!");

        const form = new FormData();
        form.append("audio_file", audioFile);
        form.append("image_file", imageFileInput.files[0]);
        form.append("n_fft", nFftSlider.value);
        form.append("hop_length", hopLengthSlider.value);

        loading.classList.remove("hidden");

        const response = await fetch("/api/embed", {
            method: "POST",
            body: form
        });

        if (!response.ok) throw new Error(await response.text());

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);

        // Auto download
        const a = document.createElement("a");
        a.href = url;
        a.download = "embedded.png";
        a.click();

        embedResult.innerHTML = `
            <h3 class="result-title">✅ Embedded!</h3>
            <img src="${url}" style="max-width:300px;border:2px solid #000;">
        `;
        embedResult.classList.remove("hidden");

    } catch (err) {
        alert("Error: " + err.message);
    } finally {
        loading.classList.add("hidden");
    }
});

// 🔥 FIXED — EXTRACT (BINARY RESPONSE)
extractBtn.addEventListener("click", async () => {
    try {
        if (!extractImageFileInput.files.length) return alert("Choose PNG!");

        const form = new FormData();
        form.append("image_file", extractImageFileInput.files[0]);

        loading.classList.remove("hidden");

        const response = await fetch("/api/extract", {
            method: "POST",
            body: form
        });

        if (!response.ok) throw new Error(await response.text());

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);

        const a = document.createElement("a");
        a.href = url;
        a.download = "extracted.wav";
        a.click();

        extractResult.innerHTML = `
            <h3 class="result-title">✅ Extracted!</h3>
            <audio controls src="${url}"></audio>
        `;
        extractResult.classList.remove("hidden");

    } catch (err) {
        alert("Error: " + err.message);
    } finally {
        loading.classList.add("hidden");
    }
});
