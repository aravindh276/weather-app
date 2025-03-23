// Function to get current time
function updateTime() {
    const now = new Date();
    document.getElementById('datetime').innerText = now.toLocaleString();
}
updateTime();
setInterval(updateTime, 1000);

// Function to fetch temperature based on location
function getTemperature(lat, lon) {
    const apiKey = '898da392574d16001c5d4d7d0277d1e9';
    fetch(`https://api.openweathermap.org/data/2.5/weather?lat=${lat}&lon=${lon}&units=metric&appid=${apiKey}`)
        .then(response => response.json())
        .then(data => {
            document.getElementById('temperature').innerText = `Temperature: ${data.main.temp} °C`;
            document.getElementById('location').innerText = `Location: ${data.name}`;
        })
        .catch(error => {
            console.error('Error fetching weather data:', error);
            document.getElementById('temperature').innerText = 'Unable to load temperature data.';
        });
}

// Get user's current location
if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(position => {
        getTemperature(position.coords.latitude, position.coords.longitude);
    }, () => {
        document.getElementById('location').innerText = 'Location access denied.';
        document.getElementById('temperature').innerText = 'Cannot load temperature without location.';
    });
} else {
    document.getElementById('location').innerText = 'Geolocation not supported by your browser.';
}


