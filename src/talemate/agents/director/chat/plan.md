i need you to add the bare minimum needed for me to chat with the director agent

that means:

- impliment the agent mixin for it at director/chat/mixin.py
    - stores individual chats via agent scene state (uuid per chat)
    - new chat is created by user via the Director console in the UX
        - add a new "Chats" tab to the Director console
        - allow switching between chats
        - allow removal of chats
- implement the websocket handler for the chat functionality in director/chat/websocket_handler.py
    - this then needs to be added as a mixing to director/websocket_handler.py
    - it should handle new messages from the user to the director
    - this should handle chat history retrieval (logic should be in director/chat/mixin.py)
    - this should handle new chat creation(logic should be in director/chat/mixin.py)
    - this should handle chat removal(logic should be in director/chat/mixin.py)
    - a message to the director should prompt a response from the director via a simple Prompt.request call
        - the template should be a very minimalistic jinjas2 template in prompt/templates/director/chat.jinja2 that contaisn the history of the chat and a current limited snapshot of the scene.


Expectations:

When this is done i expect that - once a scene is loaded - i can open the director console and see a new "Chats" tab.
I can then create a new chat by clicking on the "New Chat" button.
I can then see the chat history in the chat tab. (Chat <uuid>)
I can then type a message to the director and it should respond.
I can then remove a chat by clicking on the "Remove Chat" button.
I should be able to have a back and forth chat with the director about the scene.

For python changes - I want you to stay confinded to the agents/director/chat directory as MUCH as you can.

For the frontend you're less restricted, just know that the current entry point for the director console is in talemate_frontend/src/components/DirectorConsole.vue