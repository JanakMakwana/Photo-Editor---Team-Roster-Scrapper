import React, { useState } from 'react';
import { User } from '../types';
import { Layers, ShieldCheck, Mail, Lock, Key, ArrowRight, CheckCircle2 } from 'lucide-react';

interface AuthGatewayProps {
  onLoginSuccess: (user: User) => void;
}

export const AuthGateway: React.FC<AuthGatewayProps> = ({ onLoginSuccess }) => {
  const [activeTab, setActiveTab] = useState<'login' | 'activate'>('login');

  // Login form
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');
  const [loading, setLoading] = useState(false);

  // Activation form
  const [inviteToken, setInviteToken] = useState('');
  const [fullName, setFullName] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [activateError, setActivateError] = useState('');

  // MFA modal
  const [mfaTempToken, setMfaTempToken] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState('');
  const [mfaError, setMfaError] = useState('');

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError('');
    setLoading(true);

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), password })
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Invalid email or password.');
      }

      if (data.status === 'mfa_required') {
        setMfaTempToken(data.temp_token);
        setLoading(false);
        return;
      }

      if (data.user) {
        onLoginSuccess(data.user);
      }
    } catch (err: any) {
      setLoginError(err.message || 'Login failed.');
    } finally {
      setLoading(false);
    }
  };

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMfaError('');
    setLoading(true);

    try {
      const res = await fetch('/api/auth/mfa/verify_login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ temp_token: mfaTempToken, code: mfaCode.trim() })
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Invalid verification code.');
      }

      if (data.user) {
        onLoginSuccess(data.user);
      }
    } catch (err: any) {
      setMfaError(err.message || 'MFA validation failed.');
    } finally {
      setLoading(false);
    }
  };

  const handleActivateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setActivateError('');

    if (newPassword.length < 6) {
      setActivateError('Password must be at least 6 characters.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setActivateError('Passwords do not match.');
      return;
    }

    setLoading(true);
    try {
      const res = await fetch('/api/auth/activate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          invite_token: inviteToken.trim(),
          password: newPassword,
          full_name: fullName.trim()
        })
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Activation failed.');
      }

      if (data.user) {
        onLoginSuccess(data.user);
      }
    } catch (err: any) {
      setActivateError(err.message || 'Activation failed.');
    } finally {
      setLoading(false);
    }
  };

  const fillDemoAdmin = () => {
    setEmail('admin@athletics.com');
    setPassword('admin');
  };

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '24px',
      background: 'var(--bg-app)'
    }}>
      <div style={{ width: '100%', maxWidth: '440px' }}>
        {/* Brand Header */}
        <div style={{ textAlign: 'center', marginBottom: '28px' }}>
          <div style={{
            width: 44,
            height: 44,
            borderRadius: '12px',
            background: 'linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#ffffff',
            boxShadow: '0 4px 14px rgba(37, 99, 235, 0.3)',
            marginBottom: '14px'
          }}>
            <Layers size={24} strokeWidth={2.2} />
          </div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--text-main)', marginBottom: '4px' }}>
            VeloRoster <span style={{ color: 'var(--brand)' }}>AI</span>
          </h1>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            Standardized Athletic Headshots & Roster Management
          </p>
        </div>

        {/* Auth Card */}
        <div className="card" style={{ padding: '28px' }}>
          {/* Segmented Tab */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            background: 'var(--bg-subtle)',
            padding: '3px',
            borderRadius: 'var(--radius-md)',
            marginBottom: '24px'
          }}>
            <button
              type="button"
              onClick={() => setActiveTab('login')}
              style={{
                border: 'none',
                background: activeTab === 'login' ? '#ffffff' : 'transparent',
                color: activeTab === 'login' ? 'var(--text-main)' : 'var(--text-secondary)',
                fontWeight: 600,
                fontSize: '0.8125rem',
                padding: '8px',
                borderRadius: 'var(--radius-sm)',
                boxShadow: activeTab === 'login' ? 'var(--shadow-sm)' : 'none',
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('activate')}
              style={{
                border: 'none',
                background: activeTab === 'activate' ? '#ffffff' : 'transparent',
                color: activeTab === 'activate' ? 'var(--text-main)' : 'var(--text-secondary)',
                fontWeight: 600,
                fontSize: '0.8125rem',
                padding: '8px',
                borderRadius: 'var(--radius-sm)',
                boxShadow: activeTab === 'activate' ? 'var(--shadow-sm)' : 'none',
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
            >
              Activate Seat
            </button>
          </div>

          {activeTab === 'login' ? (
            <form onSubmit={handleLoginSubmit}>
              <div className="form-group">
                <label className="form-label">Email Address</label>
                <div className="input-wrapper">
                  <Mail className="input-icon" size={16} />
                  <input
                    type="email"
                    className="input-text"
                    placeholder="name@athletics.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoFocus
                  />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Password</label>
                <div className="input-wrapper">
                  <Lock className="input-icon" size={16} />
                  <input
                    type="password"
                    className="input-text"
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>
              </div>

              {loginError && (
                <div style={{
                  padding: '10px 12px',
                  background: 'var(--danger-light)',
                  border: '1px solid var(--danger-border)',
                  color: 'var(--danger)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '0.8125rem',
                  marginBottom: '16px'
                }}>
                  {loginError}
                </div>
              )}

              <button
                type="submit"
                className="btn btn-primary"
                disabled={loading}
                style={{ width: '100%', height: '42px', marginTop: '6px' }}
              >
                <span>{loading ? 'Authenticating...' : 'Sign In'}</span>
                <ArrowRight size={16} />
              </button>
            </form>
          ) : (
            <form onSubmit={handleActivateSubmit}>
              <div className="form-group">
                <label className="form-label">Invitation Token</label>
                <div className="input-wrapper">
                  <Key className="input-icon" size={16} />
                  <input
                    type="text"
                    className="input-text"
                    placeholder="Paste your 32-character invite token"
                    value={inviteToken}
                    onChange={(e) => setInviteToken(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Full Name</label>
                <input
                  type="text"
                  className="input-text"
                  placeholder="e.g. Alex Morgan"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label">New Password</label>
                <div className="input-wrapper">
                  <Lock className="input-icon" size={16} />
                  <input
                    type="password"
                    className="input-text"
                    placeholder="At least 6 characters"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Confirm Password</label>
                <div className="input-wrapper">
                  <Lock className="input-icon" size={16} />
                  <input
                    type="password"
                    className="input-text"
                    placeholder="Repeat password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                  />
                </div>
              </div>

              {activateError && (
                <div style={{
                  padding: '10px 12px',
                  background: 'var(--danger-light)',
                  border: '1px solid var(--danger-border)',
                  color: 'var(--danger)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '0.8125rem',
                  marginBottom: '16px'
                }}>
                  {activateError}
                </div>
              )}

              <button
                type="submit"
                className="btn btn-primary"
                disabled={loading}
                style={{ width: '100%', height: '42px', marginTop: '6px' }}
              >
                <span>{loading ? 'Activating...' : 'Activate Account'}</span>
                <CheckCircle2 size={16} />
              </button>
            </form>
          )}

          {/* Quick Demo Access */}
          <div style={{
            marginTop: '22px',
            paddingTop: '18px',
            borderTop: '1px solid var(--border-subtle)',
            textAlign: 'center'
          }}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={fillDemoAdmin}
              style={{ fontSize: '0.75rem', color: 'var(--brand)' }}
            >
              Fill Demo SuperAdmin Credentials
            </button>
          </div>
        </div>

        {/* Footer info */}
        <div style={{ textAlign: 'center', marginTop: '20px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          Commercial Athletic Suite &bull; Ecstaticloud Technologies
        </div>
      </div>

      {/* MFA Modal */}
      {mfaTempToken && (
        <div className="modal-backdrop">
          <div className="modal-card">
            <div className="modal-header">
              <h3 style={{ fontSize: '1rem', fontWeight: 700 }}>Two-Factor Authentication</h3>
            </div>
            <form onSubmit={handleMfaSubmit}>
              <div className="modal-body">
                <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '16px' }}>
                  Enter the 6-digit code from your authenticator application.
                </p>
                <div className="form-group">
                  <input
                    type="text"
                    className="input-text"
                    placeholder="000000"
                    maxLength={6}
                    value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value)}
                    autoFocus
                    style={{ textAlign: 'center', letterSpacing: '4px', fontSize: '1.25rem', fontWeight: 700 }}
                  />
                </div>
                {mfaError && (
                  <div style={{ color: 'var(--danger)', fontSize: '0.8125rem', marginTop: '8px' }}>
                    {mfaError}
                  </div>
                )}
              </div>
              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setMfaTempToken(null)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={loading}>
                  Verify & Sign In
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
