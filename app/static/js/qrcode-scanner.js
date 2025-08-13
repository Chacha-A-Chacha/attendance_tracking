document.addEventListener('DOMContentLoaded', () => {
    const video = document.getElementById('qr-video');
    const scanResult = document.getElementById('scan-result');
    const sessionSelect = document.getElementById('session-select');
    
    // Access the camera
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } })
        .then(function(stream) {
            video.srcObject = stream;
            video.setAttribute('playsinline', true);
            video.play();
            requestAnimationFrame(tick);
        });
    
    function tick() {
        if (video.readyState === video.HAVE_ENOUGH_DATA) {
            // Use jsQR library to scan for QR codes
            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
            
            const code = jsQR(imageData.data, imageData.width, imageData.height);
            
            if (code) {
                // We found a QR code
                verifyAttendance(code.data, sessionSelect.value);
            }
        }
        
        requestAnimationFrame(tick);
    }
    
    function verifyAttendance(uniqueId, sessionTime) {
        fetch('/check-in/verify', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                unique_id: uniqueId,
                session_time: sessionTime
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                scanResult.innerHTML = `
                    <div class="success">
                        <h3>Welcome, ${data.participant.name}!</h3>
                        <p>You are in the correct session.</p>
                        <p>Your classroom: ${data.participant.classroom}</p>
                    </div>
                `;
            } else {
                scanResult.innerHTML = `
                    <div class="error">
                        <h3>Hello, ${data.participant.name}</h3>
                        <p>This is not your scheduled session.</p>
                        <p>Your session: ${data.correct_session}</p>
                        <p>Your classroom: ${data.participant.classroom}</p>
                    </div>
                `;
            }
            
            // Clear the result after 5 seconds
            setTimeout(() => {
                scanResult.innerHTML = '';
            }, 5000);
        });
    }
});
