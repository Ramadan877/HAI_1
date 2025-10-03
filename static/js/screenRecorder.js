// V1 single-session screen recorder (IIFE)
(function(){
    let mediaRecorder = null;
    let recordedChunks = [];
    let isRecording = false;
    let recordingStream = null;
    let recordingStartTime = null;
    let recordingTimer = null;
    let isSaving = false;

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

            mediaRecorder.onstop = async () => {
                const elapsed = recordingStartTime ? Math.round((Date.now() - recordingStartTime)/1000) : 0;
                console.log(`V1: stopped after ${elapsed}s, chunks=${recordedChunks.length}`);
                if (recordedChunks.length === 0) return;
                const blob = new Blob(recordedChunks, { type: mediaRecorder.mimeType || 'video/webm' });
                try { await uploadSessionRecordingV1(blob); }
                catch (err) {
                    console.error('V1 upload error', err);
                    try { const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=`V1_session_${Date.now()}.webm`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url); } catch(e){console.error(e);} 
                } finally { recordedChunks=[]; if (recordingStream) { recordingStream.getTracks().forEach(t=>t.stop()); recordingStream=null; } isRecording=false; clearInterval(recordingTimer); recordingTimer=null; }
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
        const resp = await fetch(renderExportUrl, { method: 'POST', body: form });
        if (!resp.ok) { const t = await resp.text().catch(()=>'<no-body>'); throw new Error(`V1 upload failed ${resp.status} ${t}`); }
        const j = await resp.json().catch(()=>null); console.log('V1 upload finished', j); return j;
    }

    async function cleanupScreenRecording() {
        if (mediaRecorder && mediaRecorder.state !== 'inactive' && !isSaving) {
            try {
                const elapsed = recordingStartTime ? Math.round((Date.now() - recordingStartTime) / 1000) : 0;
                console.log(`V1 Cleaning up recording after ${elapsed} seconds...`);

                const savePromise = new Promise((resolve) => {
                    const originalOnStop = mediaRecorder.onstop;
                    mediaRecorder.onstop = async () => {
                        if (recordedChunks.length > 0) {
                            const mimeType = mediaRecorder.mimeType || 'video/webm';
                            const blob = new Blob(recordedChunks, { type: mimeType });
                            try { await uploadSessionRecordingV1(blob); }
                            catch (e) { console.error('V1 cleanup upload failed', e); try { const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=`V1_session_${Date.now()}.webm`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url); } catch(le){console.error(le);} }
                        }
                        if (originalOnStop) { try { originalOnStop(); } catch(_){} }
                        resolve();
                    };
                });

                mediaRecorder.stop();
                await savePromise;

                recordedChunks = [];

                if (recordingStream) {
                    recordingStream.getTracks().forEach(track => track.stop());
                    recordingStream = null;
                } else if (mediaRecorder.stream) {
                    mediaRecorder.stream.getTracks().forEach(track => track.stop());
                }

                if (recordingTimer) {
                    clearInterval(recordingTimer);
                    recordingTimer = null;
                }

                mediaRecorder = null;
                isRecording = false;
                recordingStartTime = null;
            } catch (error) {
                console.error('V1 Error during cleanup:', error);
            }
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
        if (document.visibilityState === 'hidden' && isRecording) {
            console.log('V1 visibilitychange: saving');
            await cleanupScreenRecording();
        }
    });

    window.addEventListener('unload', async () => {
        if (isRecording) await cleanupScreenRecording();
    });

})();