const API = "http://localhost:8000";
let currentChatId = null;
let chatHistory = [];

async function post(path, body) {
    const r = await fetch(API + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
    });
    return r.json();
}

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    initializeEventListeners();
    newChat();
});

function initializeEventListeners() {
    // Process step event listeners
    document.getElementById("btnAdd").onclick = handleAddFeeds;
    document.getElementById("btnProcess").onclick = handleProcessPodcast;
    document.getElementById("btnPersona").onclick = handleGeneratePersona;

    // Chat input listeners
    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendButton');
    
    messageInput.addEventListener('input', () => {
        autoResize(messageInput);
        updateSendButton();
    });
    
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Podcasts input listener
    document.getElementById('podcastsInput').addEventListener('input', updateSendButton);
}

function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
}

function updateSendButton() {
    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendButton');
    const hasContent = messageInput.value.trim().length > 0;
    
    sendButton.disabled = !hasContent;
}

// Sidebar process steps
function toggleStep(stepId) {
    const step = document.getElementById(stepId);
    step.classList.toggle('expanded');
    step.classList.toggle('collapsed');
}

async function handleAddFeeds() {
    const btn = document.getElementById("btnAdd");
    const output = document.getElementById("outAdd");
    const feeds = document.getElementById("feeds").value
        .split("\n")
        .map(s => s.trim())
        .filter(Boolean)
        .slice(0, 20);

    if (feeds.length === 0) {
        output.textContent = "⚠️ Please enter at least one RSS feed URL.";
        return;
    }

    const latestN = parseInt(document.getElementById("latestN").value || "20", 10);
    
    btn.disabled = true;
    btn.classList.add('loading');
    output.textContent = "🔄 Parsing RSS feeds...";

    try {
        const res = await post("/add_podcasts", { feeds, latest_n: latestN });
        
        let outputText = "";
        if (res.parsed) {
            for (const [podcast, info] of Object.entries(res.parsed)) {
                if (info.episodes) {
                    outputText += `✅ Added: ${podcast} (${info.episodes} episodes)\n`;
                    // Auto-populate next step
                    document.getElementById("podcastName").value = podcast;
                } else if (info.error) {
                    outputText += `❌ Failed: ${podcast} → ${info.error}\n`;
                }
            }
        }
        output.textContent = outputText || "⚠️ No podcasts added.";
        
        if (outputText.includes('✅')) {
            addChatMessage('assistant', `Successfully parsed ${Object.keys(res.parsed).length} RSS feeds. You can now process the podcasts using step 2.`);
        }
        
    } catch (error) {
        output.textContent = `❌ Error: ${error.message}`;
    } finally {
        btn.disabled = false;
        btn.classList.remove('loading');
    }
}

async function handleProcessPodcast() {
    const btn = document.getElementById("btnProcess");
    const output = document.getElementById("outProcess");
    const podcast = document.getElementById("podcastName").value.trim();
    
    if (!podcast) {
        output.textContent = "⚠️ Please enter a podcast name.";
        return;
    }

    btn.disabled = true;
    btn.classList.add('loading');
    output.textContent = "🔄 Processing podcast (this may take several minutes)...";

    try {
        const res = await post("/process_podcast?podcast=" + encodeURIComponent(podcast), {});
        
        let outputText = "";
        if (res.success) {
            outputText = `🎧 Processed podcast: ${podcast}\nEpisodes processed: ${res.episodes || "ALL"}`;
            // Auto-populate next step
            document.getElementById("podcastPersona").value = podcast;
            addChatMessage('assistant', `Successfully processed "${podcast}". You can now generate a persona using step 3.`);
        } else {
            outputText = `❌ Failed to process podcast: ${podcast}\nError: ${res.error || "Unknown error"}`;
        }
        output.textContent = outputText;
        
    } catch (error) {
        output.textContent = `❌ Error: ${error.message}`;
    } finally {
        btn.disabled = false;
        btn.classList.remove('loading');
    }
}

async function handleGeneratePersona() {
    const btn = document.getElementById("btnPersona");
    const output = document.getElementById("outPersona");
    const podcast = document.getElementById("podcastPersona").value.trim();
    
    if (!podcast) {
        output.textContent = "⚠️ Please enter a podcast name.";
        return;
    }

    btn.disabled = true;
    btn.classList.add('loading');
    output.textContent = "🔄 Generating AI persona...";

    try {
        const res = await post("/persona?podcast=" + encodeURIComponent(podcast), {});
        
        let outputText = "";
        if (res.success && res.persona) {
            // Handle both string and object persona responses
            const personaText = typeof res.persona === 'string' 
                ? res.persona 
                : JSON.stringify(res.persona, null, 2);
            
            const truncatedPersona = personaText.length > 200 
                ? personaText.substring(0, 200) + '...' 
                : personaText;
                
            outputText = ` Persona generated for ${podcast}:\n${truncatedPersona}`;
            addChatMessage('assistant', `Successfully generated AI persona for "${podcast}". You can now start debates using this personality in the chat!`);
        } else {
            outputText = `❌ Failed to generate persona for ${podcast}\nError: ${res.error || "Unknown error"}`;
        }
        output.textContent = outputText;
        
    } catch (error) {
        output.textContent = `❌ Error: ${error.message}`;
    } finally {
        btn.disabled = false;
        btn.classList.remove('loading');
    }
}

// Chat functionality
function newChat() {
    currentChatId = Date.now().toString();
    const messagesContainer = document.getElementById('messagesContainer');
    
    // Clear messages and show welcome
    messagesContainer.innerHTML = `
        <div class="welcome-message" id="welcomeMessage">
            <div class="welcome-content">
                <h1>How can I help you today?</h1>
                <p>Start by processing some podcasts using the sidebar, then ask me to create debates between different podcast personalities.</p>
            </div>
        </div>
        <div class="typing-indicator" id="typingIndicator">
            <div class="typing-dots">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        </div>
    `;
    
    // Clear inputs
    document.getElementById('podcastsInput').value = '';
    document.getElementById('messageInput').value = '';
    updateSendButton();
    
    // Add to history
    addToChatHistory('New Chat', currentChatId);
}

function setExamplePrompt(podcasts, message) {
    document.getElementById('podcastsInput').value = podcasts;
    document.getElementById('messageInput').value = message;
    updateSendButton();
    document.getElementById('messageInput').focus();
}

function addChatMessage(role, content, podcasts = '') {
    const welcomeMessage = document.getElementById('welcomeMessage');
    if (welcomeMessage) {
        welcomeMessage.remove();
    }

    const messagesContainer = document.getElementById('messagesContainer');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}-message`;
    
    if (role === 'user') {
        messageDiv.innerHTML = `
            <div class="message-content">
                <div class="message-avatar">U</div>
                <div class="message-text">
                    ${podcasts ? `<strong>Podcasts:</strong> ${podcasts}<br><br>` : ''}
                    <strong>Topic:</strong> ${content}
                </div>
            </div>
        `;
    } else {
        messageDiv.innerHTML = `
            <div class="message-content">
                <div class="message-avatar">AI</div>
                <div class="message-text">${content}</div>
            </div>
        `;
    }

    const typingIndicator = document.getElementById('typingIndicator');
    messagesContainer.insertBefore(messageDiv, typingIndicator);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function showTypingIndicator() {
    const typingIndicator = document.getElementById('typingIndicator');
    typingIndicator.style.display = 'block';
    document.getElementById('messagesContainer').scrollTop = document.getElementById('messagesContainer').scrollHeight;
}

function hideTypingIndicator() {
    document.getElementById('typingIndicator').style.display = 'none';
}

function formatDebateResponse(res) {
    let output = "";
    
    if (res.synthesis) {
        output += `<div class="synthesis-section">
            <div class="synthesis-title"> Synthesis & Analysis</div>
            <div>${res.synthesis.replace(/\n/g, '<br>')}</div>
        </div>`;
    }
    
    if (res.individual_responses && res.individual_responses.length > 0) {
        res.individual_responses.forEach(r => {
            output += `
                <div class="debate-response">
                    <div class="debate-persona">🎙️ ${r.podcast}</div>
                    <div>${r.response.replace(/\n/g, '<br>')}</div>
                </div>
            `;
        });
    }
    
    return output || "❌ No debate results generated.";
}

async function sendMessage() {
    const podcastsInput = document.getElementById('podcastsInput');
    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendButton');

    const podcasts = podcastsInput.value.trim();
    const message = messageInput.value.trim();

    if (!message) return;

    sendButton.disabled = true;
    
    // Add user message
    addChatMessage('user', message, podcasts || 'My Discussion');
    
    // Update chat history title
    updateChatHistoryTitle(currentChatId, message.substring(0, 30) + '...');
    
    // Clear input
    messageInput.value = '';
    autoResize(messageInput);
    updateSendButton();
    
    // Show typing
    showTypingIndicator();

    try {
        // Parse podcast names
        const names = podcasts ? podcasts.split(',').map(s => s.trim()).filter(Boolean) : [];
        
        // Make API call
        const res = await post('/query_multi', {
            podcast_names: names,
            query: message
        });

        hideTypingIndicator();
        
        if (res.error) {
            addChatMessage('assistant', `❌ Error: ${res.error}`);
        } else {
            const formattedResponse = formatDebateResponse(res);
            addChatMessage('assistant', formattedResponse);
        }
        
    } catch (error) {
        hideTypingIndicator();
        addChatMessage('assistant', `❌ Network error: ${error.message}`);
    } finally {
        sendButton.disabled = false;
    }
}

function addToChatHistory(title, chatId) {
    const chatHistoryList = document.getElementById('chatHistoryList');
    
    // Remove existing active class
    document.querySelectorAll('.chat-history-item').forEach(item => {
        item.classList.remove('active');
    });
    
    // Check if chat already exists
    let existingChat = document.querySelector(`[data-chat-id="${chatId}"]`);
    if (!existingChat) {
        const chatItem = document.createElement('div');
        chatItem.className = 'chat-history-item';
        chatItem.dataset.chatId = chatId;
        chatItem.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span class="chat-title">${title}</span>
        `;
        
        chatItem.onclick = () => loadChat(chatId);
        chatHistoryList.insertBefore(chatItem, chatHistoryList.firstChild);
        existingChat = chatItem;
    }
    
    existingChat.classList.add('active');
}

function updateChatHistoryTitle(chatId, newTitle) {
    const chatItem = document.querySelector(`[data-chat-id="${chatId}"]`);
    if (chatItem) {
        const titleElement = chatItem.querySelector('.chat-title');
        if (titleElement && titleElement.textContent === 'New Chat') {
            titleElement.textContent = newTitle;
        }
    }
}

function loadChat(chatId) {
    // This would load a specific chat - for now just highlight it
    document.querySelectorAll('.chat-history-item').forEach(item => {
        item.classList.remove('active');
    });
    
    const chatItem = document.querySelector(`[data-chat-id="${chatId}"]`);
    if (chatItem) {
        chatItem.classList.add('active');
        currentChatId = chatId;
    }
}

// Mobile sidebar toggle (for responsive design)
function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    sidebar.classList.toggle('open');
}

// Add mobile menu button if needed
if (window.innerWidth <= 768) {
    const mobileMenuBtn = document.createElement('button');
    mobileMenuBtn.innerHTML = '☰';
    mobileMenuBtn.onclick = toggleSidebar;
    mobileMenuBtn.style.cssText = `
        position: fixed;
        top: 10px;
        left: 10px;
        z-index: 1001;
        background: var(--bg-secondary);
        border: 1px solid var(--border);
        color: var(--text-primary);
        padding: 8px 12px;
        border-radius: 6px;
        cursor: pointer;
    `;
    document.body.appendChild(mobileMenuBtn);
}

// Handle window resize
window.addEventListener('resize', () => {
    if (window.innerWidth > 768) {
        document.querySelector('.sidebar').classList.remove('open');
    }
});