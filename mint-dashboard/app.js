(function() {
    const API_BASE = window.location.origin;
    let nsec = null;
    let npub = null;
    let mintUrl = null;

    const nsecInput = document.getElementById('nsec-input');
    const loginBtn = document.getElementById('login-btn');
    const loginSection = document.getElementById('login-section');
    const dashboardSection = document.getElementById('dashboard-section');
    const authStatus = document.getElementById('auth-status');
    const mintDetails = document.getElementById('mint-details');
    const quotesBody = document.getElementById('quotes-body');
    const auditBody = document.getElementById('audit-body');
    const refreshBtn = document.getElementById('refresh-btn');

    function hexToBytes(hex) {
        const bytes = new Uint8Array(hex.length / 2);
        for (let i = 0; i < hex.length; i += 2) bytes[i / 2] = parseInt(hex.substr(i, 2), 16);
        return bytes;
    }

    async function decodeNsec(nsecStr) {
        try {
            const { nip19 } = await import('https://esm.sh/nostr-tools@2.7.0');
            const decoded = nip19.decode(nsecStr);
            if (decoded.type === 'nsec') return hexToBytes(decoded.data);
        } catch(e) {}
        if (/^[0-9a-f]{64}$/.test(nsecStr)) return hexToBytes(nsecStr);
        throw new Error('Invalid nsec');
    }

    async function getPubkey(privkeyBytes) {
        try {
            const { finalizeEvent, generateSecretKey, getPublicKey } = await import('https://esm.sh/nostr-tools@2.7.0');
            const { schnorr } = await import('https://esm.sh/@noble/curves@1.4.0/secp256k1');
            return schnorr.getPublicKey(privkeyBytes);
        } catch(e) {
            throw new Error('Cannot derive pubkey: ' + e.message);
        }
    }

    async function signEvent(evt, privkeyBytes) {
        const { finalizeEvent } = await import('https://esm.sh/nostr-tools@2.7.0');
        return finalizeEvent(evt, privkeyBytes);
    }

    async function publishEvent(event) {
        const relay = 'wss://relay.orangesync.tech';
        const ws = new WebSocket(relay);
        return new Promise((resolve, reject) => {
            ws.onopen = () => {
                ws.send(JSON.stringify(['EVENT', event]));
            };
            ws.onmessage = (msg) => {
                const data = JSON.parse(msg.data);
                if (data[0] === 'OK') { ws.close(); resolve(data); }
            };
            ws.onerror = (e) => { ws.close(); reject(e); };
            setTimeout(() => { ws.close(); reject(new Error('timeout')); }, 10000);
        });
    }

    async function login() {
        try {
            const nsecStr = nsecInput.value.trim();
            if (!nsecStr) return;
            const privkeyBytes = await decodeNsec(nsecStr);
            const pubkeyBytes = await getPubkey(privkeyBytes);
            const pubkeyHex = Array.from(pubkeyBytes).map(b => b.toString(16).padStart(2, '0')).join('');

            const resp = await fetch(`${API_BASE}/mints`);
            const data = await resp.json();
            const mint = data.mints.find(m => m.hex_pubkey === pubkeyHex);

            if (!mint) {
                authStatus.innerHTML = '<span class="error">No mint found for this npub</span>';
                return;
            }

            nsec = privkeyBytes;
            npub = pubkeyHex;
            mintUrl = mint.url;

            loginSection.style.display = 'none';
            dashboardSection.style.display = 'block';
            authStatus.innerHTML = `Logged in: <code>${mint.subdomain}.mints</code>`;

            mintDetails.innerHTML = `
                <p>URL: <code>${mint.url}</code></p>
                <p>REST Port: ${mint.rest_port}</p>
                <p>gRPC Port: ${mint.grpc_port}</p>
            `;

            loadQuotes(mint);
            loadAudit();
        } catch (e) {
            authStatus.innerHTML = `<span class="error">Login failed: ${e.message}</span>`;
        }
    }

    async function loadQuotes(mint) {
        try {
            const resp = await fetch(`${API_BASE}/mints/${mint.subdomain}`);
            const mintData = await resp.json();

            const mintApiUrl = mint.url.replace('https://', '').replace('http://', '');
            const mintResp = await fetch(`https://${mintApiUrl}/v1/info`);
            quotesBody.innerHTML = '<tr><td colspan="5">Mint info loaded. Use a Cashu wallet to create quotes, then approve them here.</td></tr>';
        } catch (e) {
            quotesBody.innerHTML = `<tr><td colspan="5" class="error">Error: ${e.message}</td></tr>`;
        }
    }

    async function loadAudit() {
        try {
            const resp = await fetch(`${API_BASE}/audit?count=50`);
            const data = await resp.json();
            auditBody.innerHTML = '';
            for (const entry of (data.entries || []).reverse()) {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${entry.iso_time || ''}</td>
                    <td><code>${entry.quote_id || ''}</code></td>
                    <td>${entry.amount || ''} ${entry.unit || ''}</td>
                    <td class="${entry.success ? 'success' : 'error'}">${entry.success ? 'OK' : entry.error || 'FAIL'}</td>
                `;
                auditBody.appendChild(tr);
            }
        } catch (e) {
            auditBody.innerHTML = `<tr><td colspan="4" class="error">${e.message}</td></tr>`;
        }
    }

    async function approveQuote(quoteId, amount, unit) {
        try {
            const event = await signEvent({
                kind: 38010,
                created_at: Math.floor(Date.now() / 1000),
                tags: [
                    ['t', 'mint-approval'],
                    ['mint', mintUrl],
                    ['quote', quoteId],
                    ['amount', String(amount)],
                    ['unit', unit || 'sat'],
                ],
                content: `Mint approval for quote ${quoteId} (${amount} ${unit || 'sat'})`,
            }, nsec);

            await publishEvent(event);
            alert(`Approved quote ${quoteId}. Event: ${event.id}`);
            loadAudit();
        } catch (e) {
            alert(`Approval failed: ${e.message}`);
        }
    }

    loginBtn.addEventListener('click', login);
    nsecInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') login(); });
    refreshBtn.addEventListener('click', () => { if (mintUrl) loadAudit(); });

    window.tollgateApprove = approveQuote;
})();
