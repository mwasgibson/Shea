document.addEventListener("DOMContentLoaded", () => {
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const chatHistory = document.getElementById("chat-history");
  const statusIndicator = document.getElementById("status-indicator");
  const memoryList = document.getElementById("memory-list");
  const btnRefreshMemory = document.getElementById("btn-refresh-memory");

  // Auto-scroll to bottom of chat
  function scrollToBottom() {
    chatHistory.scrollTop = chatHistory.scrollHeight;
  }

  // Append a message to the chat
  function appendMessage(role, text) {
    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${role}`;
    msgDiv.textContent = text;
    chatHistory.appendChild(msgDiv);
    scrollToBottom();
    return msgDiv;
  }

  // Handle form submission
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text) return;

    appendMessage("user", text);
    chatInput.value = "";

    try {
      const res = await fetch("/api/interaction/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, profile_id: "default" }),
      });
      const data = await res.json();
      console.log("Submitted intent:", data);
      // We rely on the SSE stream to show the actual agent responses.
    } catch (err) {
      console.error(err);
      appendMessage("system", "Error: Failed to reach the API.");
    }
  });

  // Handle Server-Sent Events (SSE)
  let eventSource;
  function connectSSE() {
    eventSource = new EventSource("/api/interaction/stream");

    eventSource.onopen = () => {
      statusIndicator.textContent = "Online";
      statusIndicator.className = "status online";
    };

    eventSource.onerror = (err) => {
      console.error("SSE Error:", err);
      statusIndicator.textContent = "Offline";
      statusIndicator.className = "status offline";
      eventSource.close();
      // Try to reconnect in 3s
      setTimeout(connectSSE, 3000);
    };

    // Listen for generic SSE messages
    eventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);

        // Extremely simple dispatcher based on event type
        if (
          payload.event === "PlanStepCompleted" ||
          payload.event === "PlanCompleted"
        ) {
          // Just a placeholder to show action
          appendMessage("system", `System: ${payload.event}`);
        } else if (payload.event === "ToolExecutionRecord") {
          // Need a dedicated UI block for tools
          const msgDiv = document.createElement("div");
          msgDiv.className = `message agent`;
          msgDiv.innerHTML = `<strong>Executed Tool:</strong> <div class="tool-call">${payload.data}</div>`;
          chatHistory.appendChild(msgDiv);
          scrollToBottom();
        } else {
          console.log("Unhandled event:", payload);
        }
      } catch (err) {
        console.error("Parse error on SSE:", err);
      }
    };
  }

  // Refresh memory list
  async function loadMemories() {
    try {
      const res = await fetch("/api/memory/");
      const memories = await res.json();
      memoryList.innerHTML = "";

      if (memories.length === 0) {
        memoryList.innerHTML = '<li class="memory-item">No memories yet.</li>';
        return;
      }

      memories.forEach((m) => {
        const li = document.createElement("li");
        li.className = "memory-item";
        li.innerHTML = `<span class="type">[${m.type}]</span> ${m.content.substring(0, 60)}...`;
        memoryList.appendChild(li);
      });
    } catch (err) {
      console.error("Failed to load memories", err);
    }
  }

  btnRefreshMemory.addEventListener("click", loadMemories);

  // Initialization
  connectSSE();
  loadMemories();
});
