document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('login-form');
    const loginError = document.getElementById('login-error');
    const btnLogin = document.getElementById('btn-login');
    const btnLabel = btnLogin.querySelector('span');

    const tabLogin = document.getElementById('tab-login');
    const tabRegister = document.getElementById('tab-register');
    const subtitle = document.getElementById('auth-subtitle');
    const usernameHint = document.getElementById('username-hint');
    const passwordHint = document.getElementById('password-hint');
    const confirmGroup = document.getElementById('confirm-group');
    const confirmInput = document.getElementById('confirm-password');
    const passwordInput = document.getElementById('password');

    let mode = 'login';

    function setMode(next) {
        mode = next;
        const registering = mode === 'register';

        tabLogin.classList.toggle('active', !registering);
        tabRegister.classList.toggle('active', registering);
        tabLogin.setAttribute('aria-selected', String(!registering));
        tabRegister.setAttribute('aria-selected', String(registering));

        subtitle.textContent = registering
            ? 'Create an account to access your Legal AI GraphRAG'
            : 'Sign in to access your Legal AI GraphRAG';
        btnLabel.textContent = registering ? 'Create Account' : 'Sign In';

        usernameHint.style.display = registering ? 'block' : 'none';
        passwordHint.style.display = registering ? 'block' : 'none';
        confirmGroup.style.display = registering ? 'block' : 'none';
        confirmInput.required = registering;
        passwordInput.setAttribute('autocomplete', registering ? 'new-password' : 'current-password');

        hideError();
    }

    function showError(message) {
        loginError.textContent = message;
        loginError.style.display = 'block';
    }

    function hideError() {
        loginError.style.display = 'none';
    }

    function setBusy(busy, label) {
        btnLogin.disabled = busy;
        btnLogin.innerHTML = busy
            ? `<span>${label}...</span><i class="bi bi-arrow-repeat" style="animation: spin 1s linear infinite;"></i>`
            : `<span>${label}</span><i class="bi bi-arrow-right-short" style="font-size: 20px;"></i>`;
    }

    tabLogin.addEventListener('click', () => setMode('login'));
    tabRegister.addEventListener('click', () => setMode('register'));

    // If the session expired mid-use, apiFetch bounced us here.
    if (new URLSearchParams(window.location.search).get('expired')) {
        showError('Your session expired. Please sign in again.');
    }

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        hideError();

        const username = document.getElementById('username').value.trim();
        const password = passwordInput.value;
        const endpoint = mode === 'register' ? '/api/register' : '/api/login';
        const actionLabel = mode === 'register' ? 'Creating account' : 'Authenticating';

        if (mode === 'register' && password !== confirmInput.value) {
            showError('Passwords do not match.');
            return;
        }

        setBusy(true, actionLabel);

        try {
            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });

            const data = await res.json().catch(() => ({}));

            if (res.ok) {
                sessionStorage.setItem('sc_token', data.token);
                sessionStorage.setItem('sc_user', JSON.stringify({
                    username: data.username,
                    role: data.role
                }));
                window.location.href = '/index.html';
            } else {
                showError(data.detail || (mode === 'register'
                    ? 'Could not create that account.'
                    : 'Invalid username or password.'));
                setBusy(false, mode === 'register' ? 'Create Account' : 'Sign In');
            }
        } catch (err) {
            console.error('Auth error:', err);
            showError('Network error. Please try again.');
            setBusy(false, mode === 'register' ? 'Create Account' : 'Sign In');
        }
    });
});

// Add spin animation to document if not exists
if (!document.querySelector('style#spin-anim')) {
    const style = document.createElement('style');
    style.id = 'spin-anim';
    style.innerHTML = `
    @keyframes spin { 100% { transform: rotate(360deg); } }
    `;
    document.head.appendChild(style);
}
