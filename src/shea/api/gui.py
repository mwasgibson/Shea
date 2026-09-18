from fastapi import FastAPI
from fastapi.responses import HTMLResponse

html_content = """
<!DOCTYPE html>
<html>
    <head>
        <title>Shea Interaction GUI</title>
        <style>
            body { font-family: sans-serif; max-width: 800px; margin: 40px auto; }
            #log { height: 400px; overflow-y: scroll; border: 1px solid #ccc; padding: 10px; margin-bottom: 10px; background: #f9f9f9; }
            #input-box { width: 100%; padding: 10px; }
            button { padding: 10px 20px; }
        </style>
    </head>
    <body>
        <h1>Shea Interaction GUI</h1>
        <div id="log"></div>
        <form id="chat-form">
            <input type="text" id="input-box" placeholder="Ask Shea..." autocomplete="off"/>
            <br><br>
            <button type="submit">Send</button>
        </form>
        <script>
            const log = document.getElementById('log');
            document.getElementById('chat-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                const inputBox = document.getElementById('input-box');
                const text = inputBox.value;
                inputBox.value = '';
                
                log.innerHTML += `<div><b>You:</b> ${text}</div>`;
                
                const response = await fetch('/interact', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: text })
                });
                const result = await response.json();
                
                log.innerHTML += `<div><b>Shea:</b> Task ${result.task_id} completed. (Check logs for steps)</div>`;
                log.scrollTop = log.scrollHeight;
            });
        </script>
    </body>
</html>
"""

def register_gui(app: FastAPI) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def get_gui() -> str:
        return html_content
