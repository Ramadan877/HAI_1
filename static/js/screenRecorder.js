let mediaRecorder = null;
let recordedChunks = [];
let isRecording = false;

async function startScreenRecording() {
    try {
        const stream = await navigator.mediaDevices.getDisplayMedia({
            video: {
                cursor: "always"
            },
            audio: false
        });
        
        mediaRecorder = new MediaRecorder(stream, {
            mimeType: 'video/webm;codecs=vp9'
        });
        
        recordedChunks = [];
        
        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                recordedChunks.push(event.data);
                console.log('Recording chunk received:', event.data.size);
            }
        };
        
        mediaRecorder.onstop = async () => {
            console.log('Recording stopped, chunks collected:', recordedChunks.length);
            if (recordedChunks.length > 0) {
                const blob = new Blob(recordedChunks, { type: 'video/webm' });
                console.log('Blob created, size:', blob.size);
                await saveScreenRecording(blob);
            } else {
                console.error('No recording chunks available');
            }
            recordedChunks = [];
            
            stream.getTracks().forEach(track => track.stop());
        };
        
        mediaRecorder.start(1000);
        isRecording = true;
        console.log('Recording started');
        
        stream.getVideoTracks()[0].onended = () => {
            console.log('Screen sharing ended by user');
            if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                mediaRecorder.stop();
                isRecording = false;
            }
        };
        
    } catch (error) {
        console.error('Error starting screen recording:', error);
    }
}

async function stopScreenRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        console.log('Stopping recording...');
        mediaRecorder.stop();
        isRecording = false;
    }
}

async function saveScreenRecording(blob) {
    try {
        console.log('Preparing to save recording...');
        const formData = new FormData();
        formData.append('screen_recording', blob, 'screen_recording.webm');
        
        const currentTrialType = window.currentTrialType;
        const participantId = window.participantId;
        
        if (!currentTrialType || !participantId) {
            console.error('Missing trial type or participant ID:', { currentTrialType, participantId });
            return;
        }
        
        const trialFolderMap = {
            'Trial_1': 'main_task_1',
            'Trial_2': 'main_task_2',
            'Test': 'test_task'
        };
        
        const trialFolderName = trialFolderMap[currentTrialType] || currentTrialType.toLowerCase();
        
        formData.append('trial_type', trialFolderName);
        formData.append('participant_id', participantId);
        
        console.log('Saving screen recording for:', {
            participant_id: participantId,
            trial_type: trialFolderName,
            blob_size: blob.size
        });
        
        const response = await fetch('/save_screen_recording', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const result = await response.json();
        console.log('Screen recording saved:', result);
    } catch (error) {
        console.error('Error saving screen recording:', error);
    }
}

async function cleanupScreenRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        try {
            console.log('Cleaning up recording...');
            mediaRecorder.stop();
            
            await new Promise((resolve) => {
                mediaRecorder.onstop = () => {
                    if (recordedChunks.length > 0) {
                        const blob = new Blob(recordedChunks, { type: 'video/webm' });
                        saveScreenRecording(blob).then(resolve);
                    } else {
                        resolve();
                    }
                };
            });
            
            recordedChunks = [];
            
            if (mediaRecorder.stream) {
                mediaRecorder.stream.getTracks().forEach(track => track.stop());
            }
            
            mediaRecorder = null;
            isRecording = false;
        } catch (error) {
            console.error('Error during cleanup:', error);
        }
    }
}

window.addEventListener('beforeunload', async (event) => {
    if (isRecording) {
        await cleanupScreenRecording();
    }
});

document.addEventListener('visibilitychange', async () => {
    if (document.visibilityState === 'hidden' && isRecording) {
        await cleanupScreenRecording();
    }
});