// V1 single-session screen recorder (IIFE)
(function(){
    let mediaRecorder = null;
    let recordedChunks = [];
    let isRecording = false;
    let recordingStream = null;
    let recordingStartTime = null;
    let recordingTimer = null;
    let isSaving = false;
    let pendingRecordingBlob = null;
    let hasPendingRecording = false;

    function checkRecordingStatus() {
        if (mediaRecorder) {
            console.log(`V1 Recording Status: ${mediaRecorder.state}, chunks: ${recordedChunks.length}, isRecording: ${isRecording}`);
            if (recordingStartTime) {
                const elapsed = Math.round((Date.now() - recordingStartTime)/1000);
                const mm = Math.floor(elapsed/60), ss = elapsed%60;
                console.log(`V1 elapsed: ${mm}:${ss.toString().padStart(2,'0')}`);
            }
        } else {
            console.log('V1 No media recorder active');
        }
    }

    window.checkRecordingStatus = checkRecordingStatus;

    async function startScreenRecording() {
        try {
            console.log('V1: startScreenRecording called');
            recordedChunks = [];
            recordingStartTime = Date.now();

            recordingStream = await navigator.mediaDevices.getDisplayMedia({
                video: { cursor: 'always', width: { ideal: 1920, max: 3840 }, height: { ideal: 1080, max: 2160 }, frameRate: { ideal: 15, max: 30 } },
                audio: false
            });

            const candidates = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm', 'video/mp4'];
            let mimeType = '';
            for (const c of candidates) { if (c && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(c)) { mimeType = c; break; } }

            const options = {};
            if (mimeType) options.mimeType = mimeType;

            mediaRecorder = new MediaRecorder(recordingStream, options);

            mediaRecorder.ondataavailable = (ev) => { if (ev.data && ev.data.size > 0) recordedChunks.push(ev.data); };
            mediaRecorder.onerror = (ev) => { console.error('V1 MediaRecorder error', ev.error); };

            mediaRecorder.onstop = () => {
                const elapsed = recordingStartTime ? Math.round((Date.now() - recordingStartTime)/1000) : 0;
                console.log(`V1: stopped after ${elapsed}s, chunks=${recordedChunks.length}`);
                if (recordedChunks.length === 0) {
                    hasPendingRecording = false;
                    pendingRecordingBlob = null;
                    return;
                }

                try {
                    const blob = new Blob(recordedChunks, { type: mediaRecorder.mimeType || 'video/webm' });
                    pendingRecordingBlob = blob;
                    hasPendingRecording = true;
                    console.log('V1: pending recording assembled (no upload yet), bytes=', blob.size);
                } catch (err) {
                    console.error('V1: failed to assemble pending blob', err);
                    pendingRecordingBlob = null;
                    hasPendingRecording = false;
                }
            };

            mediaRecorder.start(); isRecording=true; console.log('V1 recording started');

            recordingTimer = setInterval(()=>{ if(!isRecording) return; const elapsed=Math.round((Date.now()-recordingStartTime)/1000); const mm=Math.floor(elapsed/60), ss=elapsed%60; console.log(`V1 recording ${mm}:${ss.toString().padStart(2,'0')}`); },30000);

            recordingStream.getVideoTracks()[0].onended = () => { console.log('V1 display track ended'); if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop(); };
            return Promise.resolve();
        } catch (err) { console.error('V1 startScreenRecording error', err); throw err; }
    }

    async function stopScreenRecording() { if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop(); if (recordingTimer) { clearInterval(recordingTimer); recordingTimer=null; } recordingStartTime=null; }

    async function uploadSessionRecordingV1(blob) {
        console.log('V1: uploading session recording');
        const form = new FormData();
        const filename = `session_recording_${new Date().toISOString().replace(/[:.]/g,'')}.webm`;
        form.append('screen_recording', blob, filename);
        form.append('trial_type', window.currentTrialType || 'unknown');
        form.append('participant_id', window.participantId || 'unknown');
        const renderExportUrl = 'https://hai-v1-app.onrender.com/export_complete_data';
        try {
            const resp = await fetch(renderExportUrl, { method: 'POST', body: form, keepalive: true });
            if (!resp.ok) { const t = await resp.text().catch(()=>'<no-body>'); throw new Error(`V1 upload failed ${resp.status} ${t}`); }
            const j = await resp.json().catch(()=>null); console.log('V1 upload finished', j); return j;
        } catch (err) {
            console.error('V1 uploadSessionRecordingV1 error', err);
            throw err;
        }
    }

    async function cleanupScreenRecording() {
        try {
            if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                console.log('V1 cleanup: stopping mediaRecorder to assemble pending blob');
                const stopPromise = new Promise((resolve) => {
                    const originalOnStop = mediaRecorder.onstop;
                    mediaRecorder.onstop = () => { try { if (originalOnStop) originalOnStop(); } catch(_){}; resolve(); };
                });
                mediaRecorder.stop();
                await stopPromise;
            }

            if (hasPendingRecording && pendingRecordingBlob) {
                try {
                    await uploadPendingRecordingV1();
                } catch (e) {
                    console.error('V1 cleanup upload failed (left pending for retry):', e);
                }
            }

            if (recordingStream) { recordingStream.getTracks().forEach(track=>track.stop()); recordingStream=null; }
            else if (mediaRecorder && mediaRecorder.stream) { try { mediaRecorder.stream.getTracks().forEach(track=>track.stop()); } catch(_){} }

            if (recordingTimer) { clearInterval(recordingTimer); recordingTimer=null; }
            mediaRecorder = null; isRecording=false; recordingStartTime=null; recordedChunks=[];
        } catch (error) { console.error('V1 Error during cleanup:', error); }
    }

    async function uploadPendingRecordingV1() {
        if (!hasPendingRecording || !pendingRecordingBlob) { console.log('V1: no pending recording to upload'); return null; }
        console.log('V1: uploadPendingRecordingV1 attempting upload, bytes=', pendingRecordingBlob.size);
        const renderExportUrl = 'https://hai-v1-app.onrender.com/export_complete_data';
        try {
            const form = new FormData();
            const filename = `session_recording_${new Date().toISOString().replace(/[:.]/g,'')}.webm`;
            form.append('screen_recording', pendingRecordingBlob, filename);
            form.append('trial_type', window.currentTrialType || 'unknown');
            form.append('participant_id', window.participantId || 'unknown');
            const resp = await fetch(renderExportUrl, { method: 'POST', body: form, keepalive: true });
            if (!resp.ok) { const t = await resp.text().catch(()=>'<no-body>'); throw new Error(`V1 upload failed ${resp.status} ${t}`); }
            const j = await resp.json().catch(()=>null); console.log('V1 upload finished', j);
            hasPendingRecording = false; pendingRecordingBlob = null; return j;
        } catch (err) {
            console.error('V1 uploadPendingRecordingV1 failed', err);
            try { if (navigator && navigator.sendBeacon) { const ok = navigator.sendBeacon(renderExportUrl, pendingRecordingBlob); console.log('V1 sendBeacon fallback', ok); if (ok) { hasPendingRecording=false; pendingRecordingBlob=null; return { beacon:true }; } } } catch(e){ console.error('V1 sendBeacon error', e); }
            throw err;
        }
    }

    // expose
    window.startScreenRecording = startScreenRecording;
    window.stopScreenRecording = stopScreenRecording;

    window.addEventListener('beforeunload', async (event) => {
        if (isRecording && mediaRecorder && mediaRecorder.state !== 'inactive') {
            console.log('V1 beforeunload: attempting cleanup');
            try {
                event.preventDefault();
                await cleanupScreenRecording();
                event.returnValue = '';
            } catch (e) { console.warn('V1 beforeunload cleanup failed', e); }
        }
    });

    document.addEventListener('visibilitychange', async () => {
        console.log('V1 visibilitychange event:', document.visibilityState);
    });

    window.addEventListener('unload', async () => {
        if (isRecording) await cleanupScreenRecording();
    });

})();