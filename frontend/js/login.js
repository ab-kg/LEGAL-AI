document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('login-form');
    const loginError = document.getElementById('login-error');
    const btnLogin = document.getElementById('btn-login');

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        
        btnLogin.disabled = true;
        btnLogin.innerHTML = '<span>Authenticating...</span><i class="bi bi-arrow-repeat" style="animation: spin 1s linear infinite;"></i>';
        loginError.style.display = 'none';

        try {
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ username, password })
            });

            if (res.ok) {
                const data = await res.json();
                // Store in sessionStorage so it logs out when tab closes
                sessionStorage.setItem('sc_token', data.token);
                sessionStorage.setItem('sc_user', JSON.stringify({username: data.username, role: data.role}));
                
                // Redirect to main app
                window.location.href = '/index.html';
            } else {
                loginError.style.display = 'block';
                btnLogin.disabled = false;
                btnLogin.innerHTML = '<span>Secure Login</span><i class="bi bi-arrow-right-short" style="font-size: 20px;"></i>';
            }
        } catch (error) {
            console.error('Login error:', error);
            loginError.textContent = 'Network error. Please try again.';
            loginError.style.display = 'block';
            btnLogin.disabled = false;
            btnLogin.innerHTML = '<span>Secure Login</span><i class="bi bi-arrow-right-short" style="font-size: 20px;"></i>';
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
