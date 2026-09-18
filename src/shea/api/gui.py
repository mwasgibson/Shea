from fastapi import FastAPI
from fastapi.responses import HTMLResponse

html_content = """
<!DOCTYPE html>
<html>
    <head>
        <title>Shea Admin Dashboard</title>
        <style>
            :root { --bg: #f4f4f9; --nav-bg: #2c3e50; --text: #333; --border: #ddd; }
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; display: flex; height: 100vh; background: var(--bg); color: var(--text); }
            nav { width: 250px; background: var(--nav-bg); color: white; display: flex; flex-direction: column; padding-top: 20px; }
            nav h2 { text-align: center; margin-bottom: 30px; letter-spacing: 1px; }
            nav a { padding: 15px 20px; color: #bdc3c7; text-decoration: none; font-weight: bold; border-left: 4px solid transparent; transition: all 0.2s; cursor: pointer; }
            nav a:hover, nav a.active { background: #34495e; color: white; border-left-color: #3498db; }
            main { flex: 1; padding: 30px; overflow-y: auto; }
            .panel { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 20px; display: none; }
            .panel.active { display: block; }
            
            /* Chat */
            #log { height: 400px; overflow-y: auto; border: 1px solid var(--border); padding: 15px; margin-bottom: 15px; background: #fafafa; border-radius: 4px; }
            #input-box { width: calc(100% - 100px); padding: 12px; border: 1px solid var(--border); border-radius: 4px; font-size: 14px; }
            button { width: 80px; padding: 12px; background: #3498db; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
            button:hover { background: #2980b9; }
            
            /* Tables */
            table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid var(--border); }
            th { background-color: #f8f9fa; font-weight: 600; }
            
            /* Dashboard Grid */
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }
            .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); text-align: center; border-top: 4px solid #3498db; }
            .card h3 { margin: 0; color: #7f8c8d; font-size: 14px; text-transform: uppercase; }
            .card .value { font-size: 28px; font-weight: bold; margin: 10px 0 0 0; color: #2c3e50; }
            
            pre { background: #eee; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; }
        </style>
    </head>
    <body>
        <nav>
            <h2>SHEA ADMIN</h2>
            <a onclick="showPanel('dashboard')" id="nav-dashboard" class="active">Overview & Health</a>
            <a onclick="showPanel('chat')" id="nav-chat">Interactive Chat</a>
            <a onclick="showPanel('tasks')" id="nav-tasks">Task Orchestrator</a>
            <a onclick="showPanel('audit')" id="nav-audit">Audit Trail</a>
        </nav>
        
        <main>
            <!-- Dashboard Panel -->
            <div id="dashboard" class="panel active">
                <h2>System Health & Metrics</h2>
                <div class="grid">
                    <div class="card"><h3>CPU Load (1m)</h3><div class="value" id="val-load">--</div></div>
                    <div class="card"><h3>RAM Usage</h3><div class="value" id="val-ram">--</div></div>
                    <div class="card"><h3>Active Tasks</h3><div class="value" id="val-tasks">--</div></div>
                    <div class="card"><h3>Provider Health</h3><div class="value" id="val-provider">--</div></div>
                </div>
                <div class="grid">
                    <div class="card"><h3>Security Blocks</h3><div class="value" id="val-blocks">--</div></div>
                    <div class="card"><h3>Requests / Min</h3><div class="value" id="val-rpm">--</div></div>
                    <div class="card"><h3>Rate Limit Rem.</h3><div class="value" id="val-rate">--</div></div>
                </div>
            </div>

            <!-- Chat Panel -->
            <div id="chat" class="panel">
                <h2>Interactive Session</h2>
                <div id="log"></div>
                <form id="chat-form">
                    <input type="text" id="input-box" placeholder="Ask Shea..." autocomplete="off"/>
                    <button type="submit">Send</button>
                </form>
            </div>
            
            <!-- Tasks Panel -->
            <div id="tasks" class="panel">
                <h2>Task Orchestrator</h2>
                <button onclick="loadTasks()" style="width:auto; margin-bottom: 10px;">Refresh Tasks</button>
                <table>
                    <thead><tr><th>Task ID</th><th>State</th><th>Session</th><th>Created</th><th>Updated</th></tr></thead>
                    <tbody id="tasks-body"></tbody>
                </table>
            </div>

            <!-- Audit Panel -->
            <div id="audit" class="panel">
                <h2>Tamper-Evident Audit Trail</h2>
                <button onclick="loadAudit()" style="width:auto; margin-bottom: 10px;">Refresh Audit Logs</button>
                <table>
                    <thead><tr><th>Seq</th><th>Event Type</th><th>Action</th><th>Target</th><th>Result</th><th>Timestamp</th></tr></thead>
                    <tbody id="audit-body"></tbody>
                </table>
            </div>
        </main>

        <script>
            function showPanel(panelId) {
                document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
                document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
                document.getElementById(panelId).classList.add('active');
                document.getElementById('nav-' + panelId).classList.add('active');
                
                if(panelId === 'tasks') loadTasks();
                if(panelId === 'audit') loadAudit();
                if(panelId === 'dashboard') loadHealth();
            }

            // Chat Logic
            const log = document.getElementById('log');
            document.getElementById('chat-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                const inputBox = document.getElementById('input-box');
                const text = inputBox.value;
                if (!text.trim()) return;
                inputBox.value = '';
                
                log.innerHTML += `<div style="margin-bottom:10px;"><b>You:</b> ${text}</div>`;
                log.scrollTop = log.scrollHeight;
                
                try {
                    const response = await fetch('/interact', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ text: text })
                    });
                    const result = await response.json();
                    
                    if (result.error) {
                        log.innerHTML += `<div style="color:red; margin-bottom:10px;"><b>Error:</b> ${result.error}</div>`;
                    } else {
                        log.innerHTML += `<div style="margin-bottom:10px;"><b>Shea [Task ${result.task_id}]:</b> ${result.task_state} (Check terminal/logs for full output)</div>`;
                    }
                } catch (err) {
                    log.innerHTML += `<div style="color:red;"><b>Connection Error:</b> ${err}</div>`;
                }
                log.scrollTop = log.scrollHeight;
            });

            // Tasks Logic
            async function loadTasks() {
                const tbody = document.getElementById('tasks-body');
                try {
                    const res = await fetch('/tasks/');
                    const tasks = await res.json();
                    tbody.innerHTML = tasks.map(t => 
                        `<tr>
                            <td style="font-family:monospace;">${t.id}</td>
                            <td><span style="background:#eee;padding:2px 6px;border-radius:3px;">${t.state}</span></td>
                            <td>${t.session_id}</td>
                            <td>${t.created_at}</td>
                            <td>${t.updated_at}</td>
                        </tr>`
                    ).join('');
                } catch (e) {
                    tbody.innerHTML = `<tr><td colspan="5" style="color:red;">Failed to load tasks.</td></tr>`;
                }
            }

            // Audit Logic
            async function loadAudit() {
                const tbody = document.getElementById('audit-body');
                try {
                    const res = await fetch('/observability/audit?limit=100');
                    const data = await res.json();
                    tbody.innerHTML = data.events.map(e => 
                        `<tr>
                            <td>${e.sequence_number}</td>
                            <td>${e.event_type}</td>
                            <td>${e.action}</td>
                            <td style="font-family:monospace;font-size:12px;">${e.target || '-'}</td>
                            <td>${e.result || '-'}</td>
                            <td>${e.created_at}</td>
                        </tr>`
                    ).join('');
                } catch (e) {
                    tbody.innerHTML = `<tr><td colspan="6" style="color:red;">Failed to load audit logs.</td></tr>`;
                }
            }

            // Health Logic
            async function loadHealth() {
                try {
                    const res = await fetch('/observability/health');
                    const h = await res.json();
                    document.getElementById('val-load').innerText = h.load_1m.toFixed(2);
                    document.getElementById('val-ram').innerText = `${h.ram_used_mb.toFixed(0)} MB (${h.ram_percent.toFixed(1)}%)`;
                    document.getElementById('val-tasks').innerText = h.active_tasks;
                    document.getElementById('val-provider').innerText = (h.provider_health * 100).toFixed(0) + "%";
                    document.getElementById('val-blocks').innerText = h.security_blocks;
                    document.getElementById('val-rpm').innerText = h.requests_per_minute.toFixed(1);
                    document.getElementById('val-rate').innerText = h.rate_limit_remaining.toFixed(0);
                } catch (e) {}
            }
            
            // Auto-refresh health
            setInterval(() => {
                if(document.getElementById('dashboard').classList.contains('active')) {
                    loadHealth();
                }
            }, 3000);
            
            loadHealth();
        </script>
    </body>
</html>
"""

def register_gui(app: FastAPI) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def get_gui() -> str:
        return html_content