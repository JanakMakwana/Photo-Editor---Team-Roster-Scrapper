import React, { useState } from 'react';
import { User } from '../types';
import { Layers, ShieldCheck, Sparkles, CheckCircle2, ArrowRight, Fingerprint, Lock, Mail, Key } from 'lucide-react';

interface AuthGatewayProps {
  onLoginSuccess: (user: User) => void;
}

export const AuthGateway: React.FC<AuthGatewayProps> = ({ onLoginSuccess }) => {
  const [activeTab, setActiveTab] = useState<'login' | 'activate'>('login');

  // Login form state
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');
  const [loading, setLoading] = useState(false);

  // Activation form state
  const [inviteToken, setInviteToken] = useState('');
  const [fullName, setFullName] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [activateError, setActivateError] = useState('');

  // MFA modal state
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
        body: JSON.stringify({ email, password })
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Authentication failed.');
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
        body: JSON.stringify({ temp_token: mfaTempToken, code: mfaCode })
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Invalid code.');
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
          invite_token: inviteToken,
          password: newPassword,
          full_name: fullName
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
      background: 'var(--bg-base)'
    }}>
      <div style={{
        width: '100%',
        maxWidth: '1000px',
        display: 'grid',
        gridTemplateColumns: '1.1fr 1fr',
        gap: '40px',
        alignItems: 'center'
      }}>
        {/* Left Column: Product Value & SaaS Proposition */}
        <div style={{ textAlign: 'left' }}>
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            background: 'var(--brand-accent-subtle)',
            border: '1px solid var(--brand-accent-border)',
            borderRadius: 'var(--r-pill)',
            padding: '4px 14px',
            fontSize: '0.78rem',
            fontWeight: 700,
            color: 'var(--brand-accent)',
            marginBottom: '20px'
          }}>
            <Sparkles size={14} />
            <span>Ecstaticloud Technologies &bull; Commercial Edition</span>
          </div>

          <h1 style={{
            fontSize: '2.5rem',
            fontWeight: 800,
            lineHeight: 1.15,
            marginBottom: '16px',
            color: 'var(--text)'
          }}>
            Standardized 180×180 Headshots & <span style={{ color: 'var(--brand-accent)' }}>Athletic Roster Studio</span>
          </h1>

          <p style={{
            fontSize: '0.98rem',
            color: 'var(--text-secondary)',
            lineHeight: 1.6,
            marginBottom: '28px'
          }}>
            Commercial multi-tenant roster ingestion, player number assignment, and automated face-centering 180×180 workbench. Built from scratch with full proprietary rights owned by Ecstaticloud Technologies.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            {[
              { title: 'Standardized 180×180 Framing', desc: 'Automated face bounding-box detection with live HUD guidelines.' },
              { title: 'AI Cutout & Retouch Brushes', desc: 'Background removal with interactive Recover and Erase brushes.' },
              { title: 'Multi-League Sports Scraping', desc: 'Extract rosters from URLs (HUDL, EliteProspects, NHL, College).' },
              { title: 'Number Assignment & ZIP Export', desc: 'Assign jersey numbers and download standardized transparent PNGs.' }
            ].map((f, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                <div style={{
                  width: 22,
                  height: 22,
                  borderRadius: '50%',
                  background: '#ecfdf5',
                  border: '1px solid #a7f3d0',
                  color: '#059669',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginTop: 2
                }}>
                  <CheckCircle2 size={14} />
                </div>
                <div>
                  <div style={{ fontSize: '0.86rem', fontWeight: 700, color: 'var(--text)' }}>{f.title}</div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{f.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right Column: Authentication Card */}
        <div className="saas-card" style={{ padding: '32px' }}>
          {/* Header */}
          <div style={{ textAlign: 'center', marginBottom: '20px' }}>
            <div style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              background: 'linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 4px 14px rgba(37,99,235,0.25)',
              marginBottom: '12px'
            }}>
              <Layers size={22} color="#ffffff" strokeWidth={2.2} />
            </div>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 800 }}>VeloRoster AI Portal</h2>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              Sign in with your organization credentials
            </p>
          </div>

          {/* Segmented Switcher */}
          <div className="workflow-segmented-bar" style={{ width: '100%', marginBottom: '20px', justifyContent: 'center' }}>
            <button
              className={`workflow-tab-btn ${activeTab === 'login' ? 'active' : ''}`}
              onClick={() => setActiveTab('login')}
              style={{ flex: 1, justifyContent: 'center' }}
            >
              <Lock size={14} />
              <span>Sign In</span>
            </button>
            <button
              className={`workflow-tab-btn ${activeTab === 'activate' ? 'active' : ''}`}
              onClick={() => setActiveTab('activate')}
              style={{ flex: 1, justifyContent: 'center' }}
            >
              <Key size={14} />
              <span>Activate Seat</span>
            </button>
          </div>

          {/* Tab 1: Credentials Sign In */}
          {activeTab === 'login' && (
            <form onSubmit={handleLoginSubmit}>
              <div className="saas-form-group">
                <label className="saas-form-label">Corporate Email Address</label>
                <div className="input-icon-wrapper">
                  <Mail className="input-icon" size={16} />
                  <input
                    type="email"
                    className="saas-input"
                    placeholder="name@organization.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="saas-form-group">
                <label className="saas-form-label">Password</label>
                <div className="input-icon-wrapper">
                  <Lock className="input-icon" size={16} />
                  <input
                    type="password"
                    className="saas-input"
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>
              </div>

              {loginError && (
                <div style={{
                  padding: '10px 14px',
                  background: 'var(--danger-subtle)',
                  border: '1px solid var(--danger-border)',
                  color: 'var(--danger)',
                  borderRadius: 'var(--r-md)',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  marginBottom: '16px'
                }}>
                  {loginError}
                </div>
              )}

              <button
                type="submit"
                className="btn btn-primary"
                style={{ width: '100%', padding: '11px', fontSize: '0.9rem' }}
                disabled={loading}
              >
                <span>{loading ? 'Authenticating...' : 'Enter Studio Workspace'}</span>
                <ArrowRight size={15} />
              </button>

              <div style={{
                marginTop: '20px',
                paddingTop: '16px',
                borderTop: '1px solid var(--border-subtle)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}>
                <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>Evaluation Demo:</span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={fillDemoAdmin}
                >
                  Fill SuperAdmin
                </button>
              </div>
            </form>
          )}

          {/* Tab 2: Activate Token */}
          {activeTab === 'activate' && (
            <form onSubmit={handleActivateSubmit}>
              <div className="saas-form-group">
                <label className="saas-form-label">Invitation Token</label>
                <input
                  type="text"
                  className="saas-input"
                  placeholder="Paste 32-character token"
                  value={inviteToken}
                  onChange={(e) => setInviteToken(e.target.value)}
                  required
                />
              </div>

              <div className="saas-form-group">
                <label className="saas-form-label">Your Full Name</label>
                <input
                  type="text"
                  className="saas-input"
                  placeholder="e.g. Jordan Miller"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                />
              </div>

              <div className="saas-form-group">
                <label className="saas-form-label">Create Password</label>
                <input
                  type="password"
                  className="saas-input"
                  placeholder="Minimum 6 characters"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                />
              </div>

              <div className="saas-form-group">
                <label className="saas-form-label">Confirm Password</label>
                <input
                  type="password"
                  className="saas-input"
                  placeholder="Repeat password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                />
              </div>

              {activateError && (
                <div style={{
                  padding: '10px 14px',
                  background: 'var(--danger-subtle)',
                  border: '1px solid var(--danger-border)',
                  color: 'var(--danger)',
                  borderRadius: 'var(--r-md)',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  marginBottom: '16px'
                }}>
                  {activateError}
                </div>
              )}

              <button
                type="submit"
                className="btn btn-primary"
                style={{ width: '100%', padding: '11px', fontSize: '0.9rem' }}
                disabled={loading}
              >
                <span>{loading ? 'Activating Seat...' : 'Activate Seat & Open Studio'}</span>
                <ArrowRight size={15} />
              </button>
            </form>
          )}
        </div>
      </div>

      {/* MFA Two-Factor Modal */}
      {mfaTempToken && (
        <div className="modal-backdrop">
          <div className="modal-card" style={{ maxWidth: 420 }}>
            <div className="modal-header">
              <h3 className="modal-title">Two-Factor Authentication</h3>
            </div>
            <form onSubmit={handleMfaSubmit} className="modal-body">
              <p style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', marginBottom: '16px' }}>
                Enter the 6-digit verification code from your authenticator application.
              </p>
              <div className="saas-form-group">
                <input
                  type="text"
                  className="saas-input"
                  placeholder="123456"
                  maxLength={6}
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value)}
                  style={{ textAlign: 'center', fontSize: '1.4rem', letterSpacing: '0.2em', fontFamily: 'var(--font-mono)' }}
                  autoFocus
                  required
                />
              </div>
              {mfaError && (
                <div style={{ color: 'var(--danger)', fontSize: '0.8rem', marginBottom: '12px' }}>{mfaError}</div>
              )}
              <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ flex: 1 }}
                  onClick={() => setMfaTempToken(null)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  style={{ flex: 1 }}
                  disabled={loading}
                >
                  {loading ? 'Verifying...' : 'Verify'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
