import { randomBytes } from 'node:crypto'
import { isRecoveryRequestAllowed, recoveryHeaders, recoveryOrigin } from '@services/auth/recoveryServer'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    if (!isRecoveryRequestAllowed(request, recoveryOrigin(), false)) return new Response('Invalid recovery host.', { status: 421, headers: recoveryHeaders })
  } catch {
    return new Response('Recovery is not configured. Contact your administrator.', { status: 503, headers: recoveryHeaders })
  }
  const nonce = randomBytes(24).toString('base64')
  return new Response(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Choose a new password · LearnHouse</title>
<style nonce="${nonce}">
*{box-sizing:border-box}body{margin:0;background:#fafafa;color:#18181b;font:16px/1.5 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{min-height:100svh;display:grid;place-items:center;padding:32px 20px}.card{width:100%;max-width:440px;background:#fff;border:1px solid #e4e4e7;border-radius:16px;padding:36px}.brand{font-size:17px;font-weight:750;letter-spacing:-.5px;margin:0 0 36px}h1{font-size:28px;line-height:1.15;letter-spacing:-1px;margin:0 0 14px}p{color:#52525b;font-size:14px;margin:0 0 24px}label{display:block;font-size:14px;font-weight:600;margin:20px 0 7px}input{width:100%;border:1px solid #d4d4d8;border-radius:9px;padding:12px;font:inherit;min-height:46px}input:focus-visible,button:focus-visible,a:focus-visible{outline:3px solid #a1a1aa;outline-offset:3px}.help{font-size:12px;margin:8px 0 0;color:#71717a}button{width:100%;border:0;border-radius:9px;background:#18181b;color:white;padding:13px;font:inherit;font-size:14px;font-weight:600;line-height:1.4;cursor:pointer;margin-top:24px;min-height:46px}button:disabled{opacity:.5;cursor:not-allowed}#status{margin:18px 0 0;min-height:21px;color:#b91c1c}#status.success{color:#166534}.signin{display:block;text-align:center;margin-top:24px;color:#3f3f46;font-size:14px;text-underline-offset:4px}[hidden]{display:none!important}@media(max-width:480px){.card{padding:28px 24px}main{padding:20px 14px}}
</style></head><body><main><section class="card" aria-labelledby="title"><div class="brand">LearnHouse</div><h1 id="title">Choose a new password</h1><p id="intro">Your administrator shared a one-use recovery link. Only you choose your password.</p>
<form id="recovery" action="/api/recovery/redeem" method="post"><label for="password">New password</label><input id="password" type="password" autocomplete="new-password" required minlength="8" maxlength="1024" aria-describedby="requirements"><p class="help" id="requirements">At least 8 characters, with uppercase and lowercase letters, a number, and a special character.</p><label for="confirm">Confirm new password</label><input id="confirm" type="password" autocomplete="new-password" required maxlength="1024"><button id="submit" type="submit" disabled>Save new password</button></form><p id="status" role="status" aria-live="polite"></p><a class="signin" href="/login">Back to sign in</a></section></main>
<script nonce="${nonce}">
(() => {
  let secret = new URLSearchParams(window.location.hash.slice(1)).get('token') || '';
  window.history.replaceState(null, '', '/recover');
  const form = document.getElementById('recovery');
  const password = document.getElementById('password');
  const confirm = document.getElementById('confirm');
  const submit = document.getElementById('submit');
  const status = document.getElementById('status');
  if (!/^[A-Za-z0-9_-]{43}$/.test(secret)) {
    secret = ''; form.hidden = true;
    status.textContent = 'Open the complete recovery link your administrator shared. If it has expired, ask for a new link.';
    return;
  }
  submit.disabled = false;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (submit.disabled) return;
    status.textContent = '';
    if (password.value !== confirm.value) { status.textContent = 'The passwords do not match.'; confirm.focus(); return; }
    if (password.value.length < 8 || !/[A-Z]/.test(password.value) || !/[a-z]/.test(password.value) || !/[0-9]/.test(password.value) || !/[!@#$%^&*()_+\\-=\\[\\]{}|;':",./<>?]/.test(password.value)) { status.textContent = 'Use a password that meets all the requirements above.'; password.focus(); return; }
    submit.disabled = true; submit.textContent = 'Saving…';
    try {
      const response = await fetch('/api/recovery/redeem', { method: 'POST', credentials: 'omit', cache: 'no-store', redirect: 'error', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ secret, new_password: password.value }) });
      if (response.ok) {
        secret = ''; password.value = ''; confirm.value = ''; form.hidden = true;
        document.getElementById('title').textContent = 'Your password is updated';
        document.getElementById('intro').textContent = 'This recovery link has been used. Sign in normally with your new password. Your two-factor authentication settings are unchanged.';
        status.className = 'success'; status.textContent = 'You can sign in now.';
      } else {
        const failure = await response.json().catch(() => null);
        status.textContent = failure?.code === 'WEAK_PASSWORD' ? 'Use a password that meets all the requirements above.' : response.status === 429 ? 'Too many attempts. Wait a few minutes before trying again.' : response.status === 400 ? 'This link is invalid or expired. Ask your administrator for a new link.' : 'Recovery is temporarily unavailable. Please try again.';
      }
    } catch { status.textContent = 'Could not reach the server. Check your connection and try again.'; }
    finally { if (secret) { submit.disabled = false; submit.textContent = 'Save new password'; } }
  });
  window.addEventListener('pagehide', () => { secret = ''; password.value = ''; confirm.value = ''; submit.disabled = true; form.hidden = true; status.textContent = 'Reopen the complete link your administrator shared.'; });
})();
</script></body></html>`, { headers: {
    ...recoveryHeaders,
    'Content-Type': 'text/html; charset=utf-8',
    'X-Robots-Tag': 'noindex, nofollow',
    'Content-Security-Policy': `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'`,
  } })
}
