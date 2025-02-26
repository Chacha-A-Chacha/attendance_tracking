// filepath: /attendance_tracking/static/js/qrcode-scanner.js
document.addEventListener('DOMContentLoaded', function() {
    const video = document.createElement('video');
    const canvasElement = document.createElement('canvas');
    const canvas = canvasElement.getContext('2d');
    const qrCodeResult = document.getElementById('qr-code-result');

    // Start the video stream
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
        .then(function(stream) {
            video.srcObject = stream;
            video.setAttribute('playsinline', true); // required to tell iOS safari we don't want fullscreen
            video.play();
            requestAnimationFrame(tick);
        });

    function tick() {
        if (video.readyState === video.HAVE_ENOUGH_DATA) {
            canvasElement.height = video.videoHeight;
            canvasElement.width = video.videoWidth;
            canvas.drawImage(video, 0, 0, canvasElement.width, canvasElement.height);
            const imageData = canvas.getImageData(0, 0, canvasElement.width, canvasElement.height);
            const code = jsQR(imageData.data, imageData.width, imageData.height);

            if (code) {
                qrCodeResult.textContent = code.data; // Display the QR code result
                // Optionally, stop the video stream after successful scan
                video.srcObject.getTracks().forEach(track => track.stop());
            }
        }
        requestAnimationFrame(tick);
    }
});