$(document).ready(function() {
    // Connect to the WebSocket server
    var websocket = new WebSocket('ws://172.31.219.44:5001/ws');

    websocket.onmessage = function(event) {
        var data = JSON.parse(event.data);
        var messageContainer = $('#message-container');
        var messageElement = $('<p>').text(data.message);
        messageContainer.append(messageElement);
    };

    $('#load-button').click(function() {
        var sceneInput = $('#scene-input');
        var filePath = sceneInput.val();
        if (filePath) {
            websocket.send(JSON.stringify({type: 'load_scene', file_path: filePath}));
            sceneInput.val('');
        }
    });

    $('#send-button').click(function() {
        var messageInput = $('#message-input');
        var message = messageInput.val();
        if (message) {
            websocket.send(JSON.stringify({type: 'interact', text: message}));
            messageInput.val('');
        }
    });
});