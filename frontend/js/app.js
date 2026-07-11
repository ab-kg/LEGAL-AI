const API_BASE_URL = `${window.location.origin}/api`;
let sessionId = null;
let trendChart = null;

document.addEventListener('DOMContentLoaded', async () => {
    initTheme();
    initTabs();
    initChat();
    initUpload();

    await checkHealth();
    await createNewSession();
    fetchOverviewStats();
    fetchGlobalActivity();
    initChart();
});

/* ─── Global Activity ─── */
async function fetchGlobalActivity() {
    try {
        const res = await fetch(`${API_BASE_URL}/activity/global`);
        if (res.ok) {
            const data = await res.json();
            renderActivityFeed(data.activity || []);
        }
    } catch (e) {
        console.error("Failed to load global activity:", e);
    }
}

/* ─── Theme ─── */

function initTheme() {
    const toggle = document.getElementById('themeToggle');
    const saved = localStorage.getItem('sc-theme');
    if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
        updateThemeIcon(saved);
    }
    toggle.addEventListener('click', () => {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const next = isDark ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('sc-theme', next);
        updateThemeIcon(next);
        refreshChartTheme();
    });
}

function updateThemeIcon(theme) {
    const toggle = document.getElementById('themeToggle');
    toggle.innerHTML = theme === 'dark'
        ? '<i class="bi bi-sun-fill color-orange"></i>'
        : '<i class="bi bi-moon-stars"></i>';
}

/* ─── Tabs ─── */

function initTabs() {
    document.querySelectorAll('[data-tab]').forEach(tab => {
        tab.addEventListener('click', e => {
            e.preventDefault();
            const targetId = tab.getAttribute('data-tab');
            document.querySelectorAll('[data-tab]').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            document.querySelectorAll(`[data-tab="${targetId}"]`).forEach(t => t.classList.add('active'));
            document.getElementById(targetId).classList.add('active');
            
            const topNavRow = document.getElementById('top-nav-row');
            if (topNavRow) {
                if (targetId === 'legal-chat') {
                    topNavRow.style.display = 'none';
                } else {
                    topNavRow.style.display = 'flex';
                }
            }

            if (targetId === 'contracts') loadContracts();
            if (targetId === 'graph') loadGraph();
            if (targetId === 'overview') {
                fetchOverviewStats();
                fetchGlobalActivity();
            }
        });
    });
}

/* ─── Chat ─── */

function initChat() {
    document.getElementById('btn-send').addEventListener('click', sendMessage);
    document.getElementById('chat-input').addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    const chatUploadBtn = document.getElementById('btn-chat-upload');
    const chatPdfInput = document.getElementById('chat-pdf-upload');
    if (chatUploadBtn && chatPdfInput) {
        chatUploadBtn.addEventListener('click', () => chatPdfInput.click());
        chatPdfInput.addEventListener('change', e => {
            if (e.target.files.length) {
                handleChatFileUpload(e.target.files[0]);
                e.target.value = '';
            }
        });
    }

    document.getElementById('btn-new-session').addEventListener('click', createNewSession);

    // New Header Buttons
    document.getElementById('btn-session-graph')?.addEventListener('click', () => {
        document.querySelector('[data-tab="graph"]').click();
        loadGraph();
    });

    document.getElementById('btn-session-contracts')?.addEventListener('click', async () => {
        if (!sessionId) return;
        appendMessage('user', 'Show contract summary for this session.');
        const loaderId = appendLoader();
        try {
            const res = await fetch(`${API_BASE_URL}/session/${sessionId}/contracts`);
            document.getElementById(loaderId)?.remove();
            if (res.ok) {
                const data = await res.json();
                let html = '';
                if (!data.contracts || data.contracts.length === 0) {
                    html = '<p>No contracts found for this session.</p>';
                } else {
                    html = '<div style="display: flex; flex-direction: column; gap: 16px;">';
                    data.contracts.forEach(c => {
                        html += `
                        <div style="border: 1px solid var(--border-color, #334155); border-radius: 8px; overflow: hidden; background: transparent;">
                            <div style="background: rgba(59, 130, 246, 0.1); padding: 10px 14px; border-bottom: 1px solid var(--border-color, #334155); font-weight: 600; display: flex; align-items: center; gap: 8px;">
                                <i class="bi bi-file-earmark-text" style="color: #3b82f6;"></i>
                                ${c.contract_id || 'Unknown Contract'}
                            </div>
                            <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;">
                                <tbody>
                                    ${Object.entries(c).filter(([k]) => k !== 'contract_id' && k !== 'clauses' && k !== 'parties').map(([k, v]) => `
                                        <tr style="border-bottom: 1px solid var(--border-color, #334155);">
                                            <td style="padding: 8px 14px; font-weight: 500; color: var(--text-muted, #94a3b8); width: 140px; vertical-align: top; text-transform: capitalize;">
                                                ${k.replace(/_/g, ' ')}
                                            </td>
                                            <td style="padding: 8px 14px; vertical-align: top; color: inherit;">
                                                ${v && typeof v === 'object' ? JSON.stringify(v) : (v || '-')}
                                            </td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>`;
                    });
                    html += '</div>';
                }
                appendMessage('bot', html, true);
            } else {
                appendMessage('bot', '<span class="text-red">Failed to fetch contract summary.</span>', true);
            }
        } catch (e) {
            document.getElementById(loaderId)?.remove();
            appendMessage('bot', '<span class="text-red">Error fetching contract summary.</span>', true);
        }
    });

    document.getElementById('btn-session-chunks')?.addEventListener('click', async () => {
        if (!sessionId) return;
        appendMessage('user', 'Show vector chunks for this session.');
        const loaderId = appendLoader();
        try {
            const res = await fetch(`${API_BASE_URL}/session/${sessionId}/chunks`);
            document.getElementById(loaderId)?.remove();
            if (res.ok) {
                const data = await res.json();
                let html = '';
                if (!data.chunks || data.chunks.length === 0) {
                    html = '<p>No vector chunks found for this session.</p>';
                } else {
                    html = '<div style="display: flex; flex-direction: column; gap: 12px;">';
                    html += `<div style="font-weight:600; margin-bottom:4px; font-size:13px;"><i class="bi bi-layers color-orange"></i> Total Chunks: ${data.chunks_count || data.chunks.length}</div>`;
                    data.chunks.slice(0, 10).forEach(c => { // show top 10 max
                        html += `
                        <div style="border: 1px solid var(--border-color, #334155); border-radius: 6px; padding: 10px; background: rgba(245, 158, 11, 0.03);">
                            <div style="font-size: 11px; color: #f59e0b; font-weight: 600; margin-bottom: 6px; display: flex; justify-content: space-between;">
                                <span>Chunk Index: ${c.chunk_index !== undefined ? c.chunk_index : 'N/A'}</span>
                                <span>${c.word_count || 0} words</span>
                            </div>
                            <div style="font-size: 12px; line-height: 1.5; color: inherit; opacity: 0.9;">
                                ${c.text ? c.text.substring(0, 250) + '...' : 'No text available'}
                            </div>
                        </div>`;
                    });
                    if (data.chunks.length > 10) {
                        html += `<div style="text-align:center; font-size:11px; color:var(--text-muted, #94a3b8); margin-top:8px;">+ ${data.chunks.length - 10} more chunks</div>`;
                    }
                    html += '</div>';
                }
                appendMessage('bot', html, true);
            } else {
                appendMessage('bot', '<span class="text-red">Failed to fetch vector chunks.</span>', true);
            }
        } catch (e) {
            document.getElementById(loaderId)?.remove();
            appendMessage('bot', '<span class="text-red">Error fetching vector chunks.</span>', true);
        }
    });
}

/* ─── Upload ─── */

function initUpload() {
    const zone = document.getElementById('upload-zone');
    const input = document.getElementById('pdf-upload');

    zone.addEventListener('click', e => {
        if (e.target !== input) input.click();
    });
    zone.addEventListener('dragover', e => {
        e.preventDefault();
        zone.classList.add('drag-over');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => {
        e.preventDefault();
        zone.classList.remove('drag-over');
        if (e.dataTransfer.files.length) handleFileUpload(e.dataTransfer.files[0]);
    });
    input.addEventListener('change', e => {
        if (e.target.files.length) {
            handleFileUpload(e.target.files[0]);
            e.target.value = '';
        }
    });
}

/* ─── API ─── */

async function checkHealth() {
    const dot = document.getElementById('api-status-dot');
    const text = document.getElementById('api-status-text');
    try {
        const res = await fetch(`${API_BASE_URL}/health`);
        if (res.ok) {
            dot.style.backgroundColor = '#10b981';
            text.textContent = 'API Online';
        } else throw new Error();
    } catch {
        dot.style.backgroundColor = '#ef4444';
        text.textContent = 'Offline';
    }
}

async function createNewSession() {
    try {
        const res = await fetch(`${API_BASE_URL}/session`, { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            sessionId = data.session_id;
            document.getElementById('session-info').textContent = `Session: ${sessionId}`;
            
            document.getElementById('chat-messages').innerHTML = `
                <div class="chat-message-wrapper">
                    <div class="chat-message bot">
                        <div class="chat-avatar"><i class="bi bi-stars"></i></div>
                        <div class="message-content">
                            <p>New isolated session started. Upload contracts or ask questions.</p>
                        </div>
                    </div>
                </div>`;
                
            // Show suggestions again for new session
            const suggestions = document.querySelector('.chat-suggestions');
            if (suggestions) suggestions.style.display = 'flex';
            
            await fetchSessions();
            if (document.getElementById('contracts').classList.contains('active')) loadContracts();
            if (document.getElementById('graph').classList.contains('active')) loadGraph();
        }
    } catch (e) {
        console.error("Failed to create session:", e);
    }
}

async function fetchSessions() {
    try {
        const res = await fetch(`${API_BASE_URL}/sessions`);
        if (res.ok) {
            const data = await res.json();
            const list = document.getElementById('session-list');
            if (!list) return;
            
            list.innerHTML = '';
            if (!data.sessions || data.sessions.length === 0) {
                list.innerHTML = '<div class="text-center text-muted" style="font-size: 11px; padding: 10px;">No recent sessions</div>';
                return;
            }
            
            data.sessions.forEach(s => {
                const item = document.createElement('a');
                item.href = '#';
                item.className = 'nav-item d-flex justify-content-between align-items-center';
                if (s.session_id === sessionId) item.classList.add('active');
                
                const displayTitle = s.title || (s.session_id.substring(0, 8) + '...');
                item.innerHTML = `
                    <div style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" onclick="loadSession('${s.session_id}')" title="${displayTitle}">
                        <i class="bi bi-chat-square-text" style="margin-right:8px;"></i>
                        <span>${displayTitle}</span>
                    </div>
                    <div style="display:flex; gap: 4px; z-index: 10;">
                        <button class="btn-ghost text-muted" style="padding: 2px 6px;" onclick="renameSession('${s.session_id}', '${s.title || ''}', event)" title="Rename Session">
                            <i class="bi bi-pencil"></i>
                        </button>
                        <button class="btn-ghost text-red" style="padding: 2px 6px;" onclick="deleteSession('${s.session_id}', event)" title="Delete Session">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                `;
                list.appendChild(item);
            });
        }
    } catch (e) {
        console.error("Failed to fetch sessions:", e);
    }
}

async function deleteSession(id, event) {
    event.stopPropagation();
    if (!confirm('Are you sure you want to permanently delete this session and its data?')) return;
    
    try {
        const res = await fetch(`${API_BASE_URL}/session/${id}`, { method: 'DELETE' });
        if (res.ok) {
            if (sessionId === id) {
                await createNewSession();
            } else {
                await fetchSessions();
            }
            fetchOverviewStats(); // Refresh chart
            loadContracts();      // Refresh contracts tab
            loadGraph();          // Refresh graph tab
            fetchGlobalActivity();// Refresh activity feed
        }
    } catch (e) {
        console.error("Failed to delete session:", e);
    }
}

async function renameSession(id, currentTitle, event) {
    event.stopPropagation();
    const newTitle = prompt('Enter new session name:', currentTitle || '');
    if (!newTitle || newTitle.trim() === '' || newTitle === currentTitle) return;

    try {
        const res = await fetch(`${API_BASE_URL}/session/${id}/rename`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle.trim() })
        });
        if (res.ok) {
            await fetchSessions();
        }
    } catch (e) {
        console.error("Failed to rename session:", e);
    }
}

async function loadSession(id, switchTab = true) {
    sessionId = id;
    document.getElementById('session-info').textContent = `Session: ${sessionId}`;
    if (switchTab) {
        document.querySelector('[data-tab="legal-chat"]').click();
    }
    fetchSessions(); // Update active state
    
    document.getElementById('chat-messages').innerHTML = '<div class="text-center text-muted mt-4"><div class="chat-loader-dots"><span></span><span></span><span></span></div> Loading history...</div>';
    
    try {
        const res = await fetch(`${API_BASE_URL}/session/${id}`);
        if (res.ok) {
            const data = await res.json();
            document.getElementById('chat-messages').innerHTML = '';
            
            if (!data.messages || data.messages.length === 0) {
                 document.getElementById('chat-messages').innerHTML = `
                <div class="chat-message-wrapper">
                    <div class="chat-message bot">
                        <div class="chat-avatar"><i class="bi bi-stars"></i></div>
                        <div class="message-content"><p>Session loaded. History is empty.</p></div>
                    </div>
                </div>`;
                return;
            }
            data.messages.forEach(msg => {
                appendMessage(msg.role === 'assistant' ? 'bot' : 'user', msg.content);
            });
            // Render activity log
            renderActivityFeed(data.activity || []);
            
            // Hide suggestions since we have history
            const suggestions = document.querySelector('.chat-suggestions');
            if (suggestions && data.messages.length > 0) suggestions.style.display = 'none';
        }
    } catch (e) {
        console.error("Failed to load session messages:", e);
    }
}

async function fetchOverviewStats() {
    try {
        const res = await fetch(`${API_BASE_URL}/overview/summary`);
        if (res.ok) {
            const data = await res.json();
            animateStat('stat-contracts', data.total_contracts || 0);
            
            const distribution = data.session_distribution || [];
            animateStat('stat-sessions', distribution.length || 0);
            const chunks = data.total_chunks || data.total_contracts * 48 || 0;
            animateStat('stat-chunks', formatNumber(chunks));

            const queryDistribution = data.query_distribution || [];
            updateChartData(queryDistribution);
        }
    } catch (e) {
        console.error(e);
    }
}

function updateChartData(distribution) {
    if (!trendChart) return;
    
    const labels = distribution.map(d => {
        if (d.session_id === 'global') return 'Global';
        if (d.title) return d.title.length > 12 ? d.title.substring(0, 12) + '...' : d.title;
        return d.session_id.substring(0, 8) + '...';
    });
    const data = distribution.map(d => d.query_count || 0);
    
    trendChart.data.labels = labels;
    trendChart.data.datasets[0].data = data;
    trendChart.data.datasets[0].label = 'Queries';
    trendChart.update();
}

function animateStat(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    const display = typeof value === 'string' ? value : value;
    if (typeof value !== 'number') {
        el.textContent = display;
        return;
    }
    const start = parseInt(el.textContent) || 0;
    const duration = 600;
    const startTime = performance.now();
    function tick(now) {
        const progress = Math.min((now - startTime) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(start + (value - start) * eased);
        if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
}

function formatNumber(n) {
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return n;
}

/* ─── Chat Logic ─── */

window.prefillChat = function(query) {
    document.querySelector('[data-tab="legal-chat"]').click();
    document.getElementById('chat-input').value = query;
    sendMessage();
};

let chatAbortController = null;

async function sendMessage() {
    if (!sessionId) return alert('Session not ready. Please wait.');
    const sendBtn = document.getElementById('btn-send');
    const input = document.getElementById('chat-input');
    
    // If already generating, act as a stop button
    if (chatAbortController) {
        chatAbortController.abort();
        return;
    }

    const query = input.value.trim();
    if (!query) return;

    input.value = '';
    
    // Switch to stop icon
    sendBtn.innerHTML = '<i class="bi bi-stop-circle-fill"></i>';

    appendMessage('user', query);
    const loaderId = appendLoader();

    chatAbortController = new AbortController();

    try {
        const res = await fetch(`${API_BASE_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, query }),
            signal: chatAbortController.signal
        });

        document.getElementById(loaderId)?.remove();

        if (res.ok) {
            const data = await res.json();
            let html = typeof marked !== 'undefined' ? marked.parse(data.answer) : `<p>${data.answer.replace(/\n/g, '<br>')}</p>`;

            if (data.contexts?.length > 0) {
                html += `<div class="context-box">
                    <strong class="color-blue">Retrieved Context</strong><br>
                    ${data.contexts[0].substring(0, 200)}...
                </div>`;
            }
            if (data.triplets?.length > 0) {
                html += `<div class="context-box graph">
                    <strong class="color-purple">Graph Relationships</strong>
                    <ul>${data.triplets.slice(0, 3).map(t => `<li>${t}</li>`).join('')}</ul>
                </div>`;
            }

            appendMessage('bot', html, true);
            
            // Refresh sidebar to show newly auto-generated title if it's the first query
            fetchSessions();
            addActivity(`Query: "${query.substring(0, 40)}..."`, 'Info');
        } else {
            appendMessage('bot', '<span class="text-red">Could not fetch an answer. Please try again.</span>', true);
        }
    } catch (err) {
        document.getElementById(loaderId)?.remove();
        if (err.name === 'AbortError') {
            appendMessage('bot', '<span class="text-muted"><i>Generation stopped by user.</i></span>', true);
        } else {
            appendMessage('bot', '<span class="text-red">Server offline. Start the FastAPI backend to continue.</span>', true);
        }
    } finally {
        chatAbortController = null;
        sendBtn.innerHTML = '<i class="bi bi-arrow-up"></i>';
        input.focus();
    }
}

function appendMessage(role, content, isHtml = false) {
    const chatMessages = document.getElementById('chat-messages');
    const wrapper = document.createElement('div');
    wrapper.className = 'chat-message-wrapper';

    const msg = document.createElement('div');
    msg.className = `chat-message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'chat-avatar';
    avatar.innerHTML = role === 'bot' ? '<i class="bi bi-stars"></i>' : '<i class="bi bi-person"></i>';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    if (isHtml) {
        contentDiv.innerHTML = content;
    } else if (role === 'bot' && typeof marked !== 'undefined') {
        contentDiv.innerHTML = marked.parse(content);
    } else {
        contentDiv.textContent = content;
    }

    msg.appendChild(avatar);
    msg.appendChild(contentDiv);
    wrapper.appendChild(msg);
    chatMessages.appendChild(wrapper);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    // Hide suggestions after first message
    const suggestions = document.querySelector('.chat-suggestions');
    if (suggestions && role === 'user') {
        suggestions.style.display = 'none';
    }
}

function appendLoader() {
    const id = 'loader-' + Date.now();
    const chatMessages = document.getElementById('chat-messages');
    const wrapper = document.createElement('div');
    wrapper.id = id;
    wrapper.className = 'chat-message-wrapper';
    wrapper.innerHTML = `
        <div class="chat-message bot">
            <div class="chat-avatar"><i class="bi bi-stars"></i></div>
            <div class="message-content">
                <div class="chat-loader">
                    <div class="chat-loader-dots"><span></span><span></span><span></span></div>
                    Analyzing contracts...
                </div>
            </div>
        </div>`;
    chatMessages.appendChild(wrapper);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return id;
}

/* ─── File Upload ─── */

async function handleFileUpload(file) {
    if (!sessionId) return alert('Session not ready. Please wait.');
    if (file.type !== 'application/pdf') return alert('Only PDF files are supported.');

    const zone = document.getElementById('upload-zone');
    const status = document.getElementById('upload-status');
    const filename = document.getElementById('upload-filename');
    const progress = document.getElementById('upload-progress');
    const message = document.getElementById('upload-message');

    zone.style.display = 'none';
    status.style.display = 'block';
    filename.textContent = file.name;
    progress.style.width = '25%';
    message.textContent = 'Uploading and parsing document...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        progress.style.width = '55%';
        message.textContent = 'Generating embeddings & knowledge graph...';

        const res = await fetch(`${API_BASE_URL}/session/${sessionId}/ingest`, {
            method: 'POST',
            body: formData
        });

        if (res.ok) {
            progress.style.width = '100%';
            progress.style.background = 'linear-gradient(90deg, #10b981, #059669)';
            message.textContent = 'Successfully indexed into MongoDB Atlas!';
            addActivity(`Ingested ${file.name}`, 'Success');
            fetchOverviewStats();
            loadContracts();
            fetchSessions();
            setTimeout(resetUpload, 3000);
        } else throw new Error();
    } catch {
        progress.style.background = '#ef4444';
        message.textContent = 'Error processing document.';
        setTimeout(resetUpload, 3000);
    }

    function resetUpload() {
        zone.style.display = 'block';
        status.style.display = 'none';
        progress.style.width = '0%';
        progress.style.background = '';
    }
}

async function handleChatFileUpload(file) {
    if (!sessionId) return alert('Session not ready. Please wait.');
    if (file.type !== 'application/pdf') return alert('Only PDF files are supported.');

    appendMessage('user', `Uploading document: ${file.name}`);
    const loaderId = appendLoader();

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch(`${API_BASE_URL}/session/${sessionId}/ingest`, {
            method: 'POST',
            body: formData
        });

        document.getElementById(loaderId)?.remove();

        if (res.ok) {
            appendMessage('bot', `<span class="text-green"><i class="bi bi-check-circle-fill"></i> Successfully uploaded and indexed <strong>${file.name}</strong>.</span>`, true);
            addActivity(`Ingested ${file.name}`, 'Success');
            fetchOverviewStats();
            loadContracts();
            fetchSessions();
        } else {
            appendMessage('bot', `<span class="text-red">Failed to upload document.</span>`, true);
        }
    } catch {
        document.getElementById(loaderId)?.remove();
        appendMessage('bot', `<span class="text-red">Error uploading document.</span>`, true);
    }
}

/* ─── Contracts ─── */

let currentContractsSessionId = null;

window.loadContracts = async function() {
    const listBody = document.getElementById('contracts-sessions-body');
    const listView = document.getElementById('contracts-list-view');
    const detailView = document.getElementById('contracts-detail-view');
    
    listView.style.display = 'block';
    detailView.style.display = 'none';
    
    listBody.innerHTML = '<tr><td colspan="2" class="text-center text-muted" style="padding:24px">Loading sessions...</td></tr>';

    try {
        const res = await fetch(`${API_BASE_URL}/overview/summary`);
        if (res.ok) {
            const data = await res.json();
            const sessions = data.session_distribution || [];
            
            if (sessions.length === 0) {
                listBody.innerHTML = '<tr><td colspan="2" class="text-center text-muted" style="padding:24px">No sessions with indexed contracts found.</td></tr>';
                return;
            }
            
            listBody.innerHTML = sessions.map(s => {
                const title = s.title || (s.session_id === 'global' ? 'Global Context' : s.session_id);
                return `
                <tr style="cursor: pointer;" onclick="viewSessionContracts('${s.session_id}', '${title.replace(/'/g, "\\'")}')" class="hover-bg-subtle">
                    <td>
                        <div class="d-flex align-items-center">
                            <i class="bi bi-folder2-open color-blue" style="margin-right: 12px; font-size: 16px;"></i>
                            <strong>${title}</strong>
                        </div>
                        <div style="font-size:11px; color:var(--text-muted); margin-left:28px;">ID: ${s.session_id}</div>
                    </td>
                    <td style="text-align:right">
                        <span class="badge" style="background: rgba(59, 130, 246, 0.1); color: #3b82f6; padding: 4px 8px; border-radius: 12px; font-weight: 600; margin-right: 8px;">
                            ${s.contracts_count} Contracts
                        </span>
                        ${s.session_id !== 'global' ? `<button class="btn-ghost text-red" style="padding: 4px; position: relative; z-index: 10;" onclick="event.stopPropagation(); deleteSession('${s.session_id}', event); setTimeout(loadContracts, 500);" title="Delete Session Data"><i class="bi bi-trash"></i></button>` : ''}
                    </td>
                </tr>`;
            }).join('');
        }
    } catch {
        listBody.innerHTML = '<tr><td colspan="2" class="text-center text-red" style="padding:24px">Error loading sessions.</td></tr>';
    }
};

window.showContractsList = function() {
    document.getElementById('contracts-list-view').style.display = 'block';
    document.getElementById('contracts-detail-view').style.display = 'none';
    currentContractsSessionId = null;
};

window.viewSessionContracts = async function(id, title) {
    if (!id) return;
    currentContractsSessionId = id;
    
    document.getElementById('contracts-list-view').style.display = 'none';
    document.getElementById('contracts-detail-view').style.display = 'block';
    if (title) document.getElementById('contracts-detail-title').textContent = title + " - Contracts";
    
    const container = document.getElementById('contracts-detail-container');
    container.innerHTML = '<div class="text-center text-muted" style="padding:24px"><div class="chat-loader-dots"><span></span><span></span><span></span></div> Loading contracts...</div>';

    try {
        const res = await fetch(`${API_BASE_URL}/session/${id}/contracts`);
        if (res.ok) {
            const data = await res.json();
            if (!data.contracts?.length) {
                container.innerHTML = '<div class="text-center text-muted" style="padding:24px">No contracts indexed in this session.</div>';
                return;
            }
            
            let html = '';
            data.contracts.forEach(c => {
                html += `
                <div style="border: 1px solid var(--border-color, #334155); border-radius: 8px; overflow: hidden; background: transparent;">
                    <div style="background: rgba(59, 130, 246, 0.1); padding: 10px 14px; border-bottom: 1px solid var(--border-color, #334155); font-weight: 600; display: flex; align-items: center; justify-content: space-between;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <i class="bi bi-file-earmark-text" style="color: #3b82f6;"></i>
                            ${c.contract_id || 'Unknown Contract'}
                        </div>
                        <span class="activity-status text-green" style="font-size:11px; padding:2px 8px; border-radius:12px; background:rgba(16, 185, 129, 0.1);">Indexed</span>
                    </div>
                    <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;">
                        <tbody>
                            ${Object.entries(c).filter(([k]) => k !== 'contract_id' && k !== 'clauses' && k !== 'parties').map(([k, v]) => `
                                <tr style="border-bottom: 1px solid var(--border-color, #334155);">
                                    <td style="padding: 10px 14px; font-weight: 500; color: var(--text-muted, #94a3b8); width: 140px; vertical-align: top; text-transform: capitalize;">
                                        ${k.replace(/_/g, ' ')}
                                    </td>
                                    <td style="padding: 10px 14px; vertical-align: top; color: inherit; line-height: 1.5;">
                                        ${v && typeof v === 'object' ? JSON.stringify(v) : (v || '-')}
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>`;
            });
            container.innerHTML = html;
        } else {
             container.innerHTML = '<div class="text-center text-red" style="padding:24px">Failed to load contracts.</div>';
        }
    } catch {
        container.innerHTML = '<div class="text-center text-red" style="padding:24px">Error connecting to server.</div>';
    }
};

/* ─── Graph ─── */

let currentGraphSessionId = null;

window.loadGraph = async function() {
    const listBody = document.getElementById('graph-sessions-body');
    const listView = document.getElementById('graph-list-view');
    const detailView = document.getElementById('graph-detail-view');
    
    listView.style.display = 'block';
    detailView.style.display = 'none';
    
    listBody.innerHTML = '<tr><td colspan="2" class="text-center text-muted" style="padding:24px">Loading sessions...</td></tr>';

    try {
        const res = await fetch(`${API_BASE_URL}/overview/summary`);
        if (res.ok) {
            const data = await res.json();
            const sessions = data.session_distribution || [];
            
            if (sessions.length === 0) {
                listBody.innerHTML = '<tr><td colspan="2" class="text-center text-muted" style="padding:24px">No sessions with graph data found.</td></tr>';
                return;
            }
            
            listBody.innerHTML = sessions.map(s => {
                const title = s.title || (s.session_id === 'global' ? 'Global Context' : s.session_id);
                return `
                <tr style="cursor: pointer;" onclick="viewSessionGraph('${s.session_id}', '${title.replace(/'/g, "\\'")}')" class="hover-bg-subtle">
                    <td>
                        <div class="d-flex align-items-center">
                            <i class="bi bi-diagram-3 color-purple" style="margin-right: 12px; font-size: 16px;"></i>
                            <strong>${title}</strong>
                        </div>
                        <div style="font-size:11px; color:var(--text-muted); margin-left:28px;">ID: ${s.session_id}</div>
                    </td>
                    <td style="text-align:right">
                        <span class="badge" style="background: rgba(168, 85, 247, 0.1); color: #a855f7; padding: 4px 8px; border-radius: 12px; font-weight: 600;">
                            ${s.contracts_count} Contracts Indexed
                        </span>
                    </td>
                </tr>`;
            }).join('');
        }
    } catch {
        listBody.innerHTML = '<tr><td colspan="2" class="text-center text-red" style="padding:24px">Error loading sessions.</td></tr>';
    }
};

window.showGraphList = function() {
    document.getElementById('graph-list-view').style.display = 'block';
    document.getElementById('graph-detail-view').style.display = 'none';
    document.getElementById('graph').style.height = ''; // Remove full-screen constraint so page can scroll
    currentGraphSessionId = null;
    
    // Clear graph to save memory
    const container = document.getElementById('graph-container');
    container.innerHTML = '<div id="graph-placeholder"><i class="bi bi-share"></i><p class="text-muted">Click <strong>Render Graph</strong> to visualize contract entity relationships</p></div>';
};

window.viewSessionGraph = async function(id, title) {
    if (!id) return;
    currentGraphSessionId = id;
    
    document.getElementById('graph-list-view').style.display = 'none';
    document.getElementById('graph-detail-view').style.display = 'flex';
    document.getElementById('graph').style.height = '100%'; // Apply full-screen constraint so canvas fills screen
    if (title) document.getElementById('graph-detail-title').textContent = title + " - Graph";

    const container = document.getElementById('graph-container');
    container.innerHTML = '<div class="text-center text-muted" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%)"><i class="bi bi-arrow-repeat spin" style="font-size:28px"></i><p style="margin-top:12px">Fetching graph from Atlas...</p></div>';

    try {
        const res = await fetch(`${API_BASE_URL}/session/${id}/graph`);
        if (res.ok) {
            const data = await res.json();
            if (!data.nodes?.length) {
                container.innerHTML = '<div class="text-center text-muted" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%)"><p>Graph is empty. Upload a contract first.</p></div>';
                return;
            }

            container.innerHTML = '';
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

            const nodes = new vis.DataSet(data.nodes.map(n => ({
                id: n._id,
                label: n._id.length > 22 ? n._id.substring(0, 22) + '…' : n._id,
                color: {
                    background: n.entity_type === 'Contract' ? '#3b82f6' : '#10b981',
                    border: n.entity_type === 'Contract' ? '#2563eb' : '#059669',
                    highlight: { background: '#8b5cf6', border: '#7c3aed' }
                },
                font: { color: isDark ? '#e2e8f0' : '#1e293b', size: 12 }
            })));

            const edges = new vis.DataSet(data.edges.map(e => ({
                from: e.source,
                to: e.target,
                label: e.label,
                font: { size: 10, align: 'middle', color: isDark ? '#94a3b8' : '#64748b' },
                color: { color: isDark ? '#475569' : '#cbd5e1', highlight: '#3b82f6' },
                arrows: 'to'
            })));

            new vis.Network(container, { nodes, edges }, {
                physics: {
                    stabilization: { iterations: 150 },
                    barnesHut: { gravitationalConstant: -8000, springLength: 180 }
                },
                nodes: { shape: 'dot', size: 18, borderWidth: 2 },
                interaction: { hover: true, tooltipDelay: 200 }
            });
        } else {
             container.innerHTML = '<div class="text-center text-red" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%)"><p>Failed to fetch graph data.</p></div>';
        }
    } catch {
        container.innerHTML = '<div class="text-center text-red" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%)"><p>Error connecting to server.</p></div>';
    }
};

/* ─── Activity Feed ─── */

function addActivity(title, status) {
    const feed = document.getElementById('activity-feed');
    const color = status === 'Success' ? 'green' : status === 'Saved' ? 'orange' : 'blue';
    const icon = status === 'Success' ? 'bi-check-circle-fill' : 'bi-info-circle-fill';
    feed.insertAdjacentHTML('afterbegin', `
        <div class="activity-item">
            <div class="activity-icon color-${color}"><i class="bi ${icon}"></i></div>
            <div class="activity-details"><h4>${title}</h4><span>Just now</span></div>
            <div class="activity-status text-${color}">${status}</div>
        </div>`);
}

function renderActivityFeed(activities) {
    const feed = document.getElementById('activity-feed');
    feed.innerHTML = '';
    if (!activities || activities.length === 0) {
        feed.innerHTML = '<div class="text-center text-muted py-4">No activity yet.</div>';
        return;
    }
    // Reverse to show most recent at the top
    [...activities].reverse().forEach(act => {
        const title = act.title;
        const status = act.status;
        const color = status === 'Success' ? 'green' : status === 'Saved' ? 'orange' : 'blue';
        const icon = status === 'Success' ? 'bi-check-circle-fill' : 'bi-info-circle-fill';
        const dateStr = new Date(act.timestamp).toLocaleString([], {hour: '2-digit', minute:'2-digit', month: 'short', day: 'numeric'});
        feed.insertAdjacentHTML('beforeend', `
            <div class="activity-item">
                <div class="activity-icon color-${color}"><i class="bi ${icon}"></i></div>
                <div class="activity-details"><h4>${title}</h4><span>${dateStr}</span></div>
                <div class="activity-status text-${color}">${status}</div>
            </div>`);
    });
}

/* ─── Chart ─── */

function initChart() {
    const ctx = document.getElementById('trendChart');
    if (!ctx) return;
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const gridColor = isDark ? 'rgba(148,163,184,0.1)' : 'rgba(0,0,0,0.05)';

    trendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            datasets: [{
                label: 'Queries',
                data: [12, 19, 25, 32, 45, 56, 80],
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.08)',
                borderWidth: 2.5,
                fill: true,
                tension: 0.42,
                pointBackgroundColor: '#3b82f6',
                pointBorderColor: '#fff',
                pointBorderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: gridColor },
                    ticks: { color: isDark ? '#94a3b8' : '#64748b', font: { size: 11 } }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: isDark ? '#94a3b8' : '#64748b', font: { size: 11 } }
                }
            }
        }
    });
}

function refreshChartTheme() {
    if (!trendChart) return;
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const gridColor = isDark ? 'rgba(148,163,184,0.1)' : 'rgba(0,0,0,0.05)';
    const tickColor = isDark ? '#94a3b8' : '#64748b';
    trendChart.options.scales.y.grid.color = gridColor;
    trendChart.options.scales.y.ticks.color = tickColor;
    trendChart.options.scales.x.ticks.color = tickColor;
    trendChart.update();
}
