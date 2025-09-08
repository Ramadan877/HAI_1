let mediaRecorder = null;
let recordedChunks = [];
let isRecording = false;
let isSaving = false;
let recordingStream = null;
let recordingStartTime = null;
let recordingTimer = null;

function checkRecordingStatus() {
    if (mediaRecorder) {
        console.log(`Recording Status: ${mediaRecorder.state}, Chunks: ${recordedChunks.length}, IsRecording: ${isRecording}`);
        if (recordingStartTime) {
            const elapsed = Math.round((Date.now() - recordingStartTime) / 1000);
            const minutes = Math.floor(elapsed / 60);
            const seconds = elapsed % 60;
            console.log(`Time elapsed: ${minutes}:${seconds.toString().padStart(2, '0')}`);
        }
    } else {
        console.log('No media recorder active');
    }
}

window.checkRecordingStatus = checkRecordingStatus;

async function startScreenRecording() {
    try {
        console.log('Starting screen recording for long session...');
        recordingStartTime = Date.now();
        
        recordingStream = await navigator.mediaDevices.getDisplayMedia({
            video: {
                cursor: "always",
                width: { ideal: 1920, max: 1920 },
                height: { ideal: 1080, max: 1080 },
                frameRate: { ideal: 15, max: 30 } 
            },
            audio: false
        });
        
        let mimeType = 'video/webm;codecs=vp8';
        if (!MediaRecorder.isTypeSupported(mimeType)) {
            mimeType = 'video/webm';
            if (!MediaRecorder.isTypeSupported(mimeType)) {
                mimeType = 'video/mp4';
                if (!MediaRecorder.isTypeSupported(mimeType)) {
                    mimeType = ''; 
                }
            }
        }
        
        console.log('Using MIME type for recording:', mimeType || 'browser default');
        
        const options = {
            videoBitsPerSecond: 500000, 
        };
        
        if (mimeType) {
            options.mimeType = mimeType;
        }
        
        mediaRecorder = new MediaRecorder(recordingStream, options);
        recordedChunks = [];
        
        mediaRecorder.ondataavailable = (event) => {
            if (event.data && event.data.size > 0) {
                recordedChunks.push(event.data);
                console.log(`Recording chunk ${recordedChunks.length}: ${event.data.size} bytes`);
                
                if (recordedChunks.length % 5 === 0) {
                    const totalSize = recordedChunks.reduce((sum, chunk) => sum + chunk.size, 0);
                    const elapsed = Math.round((Date.now() - recordingStartTime) / 1000);
                    console.log(`Recording progress: ${recordedChunks.length} chunks, ${Math.round(totalSize/1024/1024)}MB, ${elapsed}s`);
                }
            } else {
                console.log('Received empty data chunk - this is normal for continuous recording');
            }
        };
        
        mediaRecorder.onstop = async () => {
            const elapsed = Math.round((Date.now() - recordingStartTime) / 1000);
            console.log(`Recording stopped after ${elapsed} seconds, chunks collected: ${recordedChunks.length}`);
            
            if (recordedChunks.length > 0 && !isSaving) {
                isSaving = true;
                const blob = new Blob(recordedChunks, { type: mimeType.split(';')[0] });
                const sizeMB = Math.round(blob.size / 1024 / 1024);
                console.log(`Final recording: ${sizeMB}MB, duration: ${elapsed}s`);
                await saveScreenRecording(blob);
                isSaving = false;
            } else {
                console.error('No recording chunks available or already saving');
            }
            recordedChunks = [];
            
            if (recordingStream) {
                recordingStream.getTracks().forEach(track => track.stop());
                recordingStream = null;
            }
            
            if (recordingTimer) {
                clearInterval(recordingTimer);
                recordingTimer = null;
            }
        };
        
        mediaRecorder.onerror = (event) => {
            console.error('MediaRecorder error:', event.error);
            isRecording = false;
            if (recordingTimer) {
                clearInterval(recordingTimer);
                recordingTimer = null;
            }
        };
        

        mediaRecorder.start(); 
    mediaRecorder.start(10000); // 10 seconds timeslice for robust long recordings
    isRecording = true;
    console.log('Long-duration recording started successfully (continuous mode, 10s chunks)');
        
    recordingTimer = setInterval(() => {
            if (isRecording && mediaRecorder && mediaRecorder.state === 'recording') {
                const elapsed = Math.round((Date.now() - recordingStartTime) / 1000);
                const minutes = Math.floor(elapsed / 60);
                const seconds = elapsed % 60;
                console.log(`Recording active: ${minutes}:${seconds.toString().padStart(2, '0')}`);
            } else {
                console.warn('Recording stopped unexpectedly, state:', mediaRecorder?.state);
                if (recordingTimer) {
                    clearInterval(recordingTimer);
                    recordingTimer = null;
                }
            }
        }, 30000); 
        
        recordingStream.getVideoTracks()[0].onended = () => {
            console.log('Screen sharing ended by user');
            if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                mediaRecorder.stop();
                isRecording = false;
            }
        };
        
    } catch (error) {
        console.error('Error starting screen recording:', error);
        isRecording = false;
        recordingStartTime = null;
        if (recordingTimer) {
            clearInterval(recordingTimer);
            recordingTimer = null;
        }
    }
}

async function stopScreenRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        const elapsed = recordingStartTime ? Math.round((Date.now() - recordingStartTime) / 1000) : 0;
        console.log(`Manually stopping recording after ${elapsed} seconds...`);
        mediaRecorder.stop();
        isRecording = false;
    }
    
    if (recordingTimer) {
        clearInterval(recordingTimer);
        recordingTimer = null;
    }
    
    if (recordingStream) {
        recordingStream.getTracks().forEach(track => track.stop());
        recordingStream = null;
    }
    
    recordingStartTime = null;
}

async function saveScreenRecording(blob) {
    try {
        const sizeMB = Math.round(blob.size / 1024 / 1024);
        console.log(`Preparing to save ${sizeMB}MB recording...`);
        
        const formData = new FormData();
        
        const timestamp = new Date().toISOString().replace(/[:.]/g, '').slice(0, 15);
        const filename = `screen_recording_${timestamp}.webm`;
        
        formData.append('screen_recording', blob, filename);
        
        const currentTrialType = window.currentTrialType;
        const participantId = window.participantId;
        
        if (!currentTrialType || !participantId) {
            console.error('Missing trial type or participant ID:', { currentTrialType, participantId });
            return;
        }
        
        formData.append('trial_type', currentTrialType);
        formData.append('participant_id', participantId);
        
        console.log('Saving screen recording for:', {
            participant_id: participantId,
            trial_type: currentTrialType,
            filename: filename,
            blob_size_mb: sizeMB
        });
        
        if (sizeMB > 10) {
            console.log('Large file detected, this may take a while...');
        }
        
        const response = await fetch('/save_screen_recording', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
        }
        
        const result = await response.json();
        console.log(`Screen recording saved successfully: ${result.message || 'OK'}`);
        
        if (result.size_mb) {
            console.log(`Server confirmed size: ${result.size_mb}MB`);
        }
        
    } catch (error) {
        console.error('Error saving screen recording:', error);
        
        if (blob.size > 0) {
            console.log('Attempting to save recording locally as fallback...');
            try {
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `screen_recording_backup_${Date.now()}.webm`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                console.log('Recording saved locally as backup');
            } catch (localError) {
                console.error('Failed to save locally:', localError);
            }
        }
    }
}

async function cleanupScreenRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive' && !isSaving) {
        try {
            const elapsed = recordingStartTime ? Math.round((Date.now() - recordingStartTime) / 1000) : 0;
            console.log(`Cleaning up recording after ${elapsed} seconds...`);
            
            const savePromise = new Promise((resolve) => {
                const originalOnStop = mediaRecorder.onstop;
                mediaRecorder.onstop = async () => {
                    if (recordedChunks.length > 0) {
                        const mimeType = mediaRecorder.mimeType || 'video/webm';
                        const blob = new Blob(recordedChunks, { type: mimeType });
                        await saveScreenRecording(blob);
                    }
                    if (originalOnStop) {
                        originalOnStop();
                    }
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
            console.error('Error during cleanup:', error);
        }
    }
}

window.addEventListener('beforeunload', async (event) => {
    if (isRecording && mediaRecorder && mediaRecorder.state !== 'inactive') {
        console.log('Page unloading, attempting to save recording...');
        
        try {
            if (recordedChunks.length > 0) {
                const blob = new Blob(recordedChunks, { type: 'video/webm' });
                
                const formData = new FormData();
                formData.append('screen_recording', blob, 'screen_recording.webm');
                formData.append('trial_type', window.currentTrialType);
                formData.append('participant_id', window.participantId);
                
                const success = navigator.sendBeacon('/save_screen_recording', formData);
                console.log('SendBeacon result:', success);
            }
        } catch (error) {
            console.error('Error during beforeunload save:', error);
        }
        
        await cleanupScreenRecording();
    }
});

document.addEventListener('visibilitychange', async () => {
    if (document.visibilityState === 'hidden' && isRecording) {
        console.log('Page hidden, saving recording...');
        await cleanupScreenRecording();
    }
});

window.addEventListener('unload', async (event) => {
    if (isRecording && mediaRecorder && mediaRecorder.state !== 'inactive') {
        console.log('Page unloading (unload event), saving recording...');
        
        try {
            if (recordedChunks.length > 0) {
                const blob = new Blob(recordedChunks, { type: 'video/webm' });
                
                const formData = new FormData();
                formData.append('screen_recording', blob, 'screen_recording.webm');
                formData.append('trial_type', window.currentTrialType);
                formData.append('participant_id', window.participantId);
                
                navigator.sendBeacon('/save_screen_recording', formData);
            }
        } catch (error) {
            console.error('Error during unload save:', error);
        }
    }
});